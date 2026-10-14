"""Posting schedule: occasions, expectations, what gets picked, and the queue the chat bot reads."""
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

from pipeline import schedule as S

KST = S.KST
FIX = Path(__file__).parent / "fixtures"
MORNING = S.Slot(name="morning", at="07:00", until="12:00", count=2, shows=["daybreak", "bigtake"], fallback=["weekly"])
EVENING = S.Slot(name="evening", at="21:00", until="23:30", count=1, shows=["tfts", "sysk"], catalog=["tfts"])


def k(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=KST)


def test_occasion_of_a_run():
    assert S.occasion(MORNING, k(2026, 10, 14, 13, 30)) == k(2026, 10, 15, 7)     # afternoon works for tomorrow
    assert S.occasion(MORNING, k(2026, 10, 15, 6, 0)) == k(2026, 10, 15, 7)
    assert S.occasion(MORNING, k(2026, 10, 15, 9, 30)) == k(2026, 10, 15, 7)      # late window (GRACE 3 h)
    assert S.occasion(MORNING, k(2026, 10, 15, 10, 0)) == k(2026, 10, 16, 7)
    assert S.occasion(EVENING, k(2026, 10, 14, 1, 0)) == k(2026, 10, 14, 21)
    assert S.occasion(EVENING, k(2026, 10, 14, 23, 30)) == k(2026, 10, 14, 21)
    assert S.occasion(EVENING, k(2026, 10, 15, 0, 0)) == k(2026, 10, 15, 21)
    assert S.occasion_key(EVENING, k(2026, 10, 14, 21)) == "2026-10-14-evening"
    assert S.until(EVENING, k(2026, 10, 14, 21)) == k(2026, 10, 14, 23, 30)
    assert S.occasion_from_key(MORNING, "2026-10-15-morning") == k(2026, 10, 15, 7)


def test_expected_from_weekly_pattern():
    # a show that publishes Mondays and Thursdays at 22:00 KST
    pubs = [k(2026, 10, 12, 22) - timedelta(days=7 * w) for w in range(6)] + [k(2026, 10, 8, 22) - timedelta(days=7 * w) for w in range(6)]
    assert S.expected(pubs, k(2026, 10, 16, 21))        # Friday evening: Thursday night's episode
    assert S.expected(pubs, k(2026, 10, 13, 21))        # Tuesday evening
    assert not S.expected(pubs, k(2026, 10, 14, 21))    # Wednesday
    assert not S.expected(pubs, k(2026, 10, 12, 21))    # Monday: it comes an hour after posting time


def C(show, when, title=None, ready=True, done=False):
    return S.Cand(show=show, key=f"{show}:{when:%m%d%H}", title=title or f"{show} episode {when:%m-%d %H}", published=when, ready=ready, done=done)


def test_plan_morning_weekday_and_holding_places():
    o = k(2026, 10, 15, 7)
    pools = {"daybreak": [C("daybreak", k(2026, 10, 14, 18, 40))], "bigtake": [], "weekly": [C("weekly", k(2026, 10, 12, 6))]}
    # evening before: Daybreak is in, Big Take usually lands ~05:30 → its place is held, the fallback stays out
    p = S.plan(MORNING, o, k(2026, 10, 14, 19, 30), [], pools, {"daybreak": True, "bigtake": True})
    assert [(c.show, why) for c, why in p.picks] == [("daybreak", "new")] and p.waiting == ["bigtake"]
    # it arrives: picked
    pools["bigtake"] = [C("bigtake", k(2026, 10, 15, 5, 40))]
    assigned = [p.picks[0][0]]
    p = S.plan(MORNING, o, k(2026, 10, 15, 5, 50), assigned, pools, {"daybreak": True, "bigtake": True})
    assert [(c.show, why) for c, why in p.picks] == [("bigtake", "new")]
    # it never arrives: after 07:15 the fallback takes the place
    pools["bigtake"] = []
    p = S.plan(MORNING, o, k(2026, 10, 15, 6, 50), assigned, pools, {"daybreak": True, "bigtake": True})
    assert p.picks == [] and p.waiting == ["bigtake"]
    p = S.plan(MORNING, o, k(2026, 10, 15, 7, 17), assigned, pools, {"daybreak": True, "bigtake": True})
    assert [(c.show, why) for c, why in p.picks] == [("weekly", "fallback")]


def test_plan_waits_for_todays_briefing_instead_of_taking_yesterdays():
    o = k(2026, 10, 15, 7)                                  # Thursday morning
    older = C("daybreak", k(2026, 10, 13, 18, 38))          # Tuesday evening's edition: within 48 h, but today's is due
    pools = {"daybreak": [older], "bigtake": [], "weekly": []}
    p = S.plan(MORNING, o, k(2026, 10, 14, 14, 0), [], pools, {"daybreak": True, "bigtake": True})
    assert p.picks == [] and p.waiting == ["daybreak", "bigtake"]
    pools["daybreak"] = [C("daybreak", k(2026, 10, 14, 18, 40)), older]
    p = S.plan(MORNING, o, k(2026, 10, 14, 19, 17), [], pools, {"daybreak": True, "bigtake": True})
    assert [c.published for c, _ in p.picks] == [k(2026, 10, 14, 18, 40)]
    # if today's never comes, the older one is still better than nothing once the hold is over
    pools["daybreak"] = [older]
    p = S.plan(MORNING, o, k(2026, 10, 15, 7, 17), [], pools, {"daybreak": True, "bigtake": True})
    assert [(c.published, why) for c, why in p.picks] == [(k(2026, 10, 13, 18, 38), "new")]


def test_plan_weekend_fills_from_fallback_right_away_and_skips_stale_or_duplicate():
    o = k(2026, 10, 18, 7)   # Sunday: no Big Take expected
    pools = {"daybreak": [C("daybreak", k(2026, 10, 16, 18, 58))],          # Friday's edition, 36 h old: still new
             "bigtake": [C("bigtake", k(2026, 10, 15, 5, 40))],             # 3 days old: not new any more
             "weekly": [C("weekly", k(2026, 10, 16, 18), title="A weekly business show"),
                        C("weekly", k(2026, 10, 9, 18))]}                   # 9 days old: too old for a fallback
    # (neither show publishes between Saturday and Sunday mornings)
    p = S.plan(MORNING, o, k(2026, 10, 17, 11, 17), [], pools, {"daybreak": False, "bigtake": False})
    assert [(c.show, why) for c, why in p.picks] == [("daybreak", "new"), ("weekly", "fallback")]
    # a cross-posted copy of something already in the occasion is not picked twice
    pools["weekly"] = [C("weekly", k(2026, 10, 16, 18), title="daybreak episode 10-16 18: Big Take")]
    p = S.plan(MORNING, o, k(2026, 10, 17, 11, 17), [], pools, {"daybreak": False, "bigtake": False})
    assert [(c.show, why) for c, why in p.picks] == [("daybreak", "new")]


def test_plan_evening_new_then_short_stuff_then_archive():
    tfts_new = C("tfts", k(2026, 10, 12, 22))
    archive = [C("tfts", k(2026, 9, 24, 22)), C("tfts", k(2026, 9, 21, 22))]
    # Tuesday: Monday night's TFTS
    p = S.plan(EVENING, k(2026, 10, 13, 21), k(2026, 10, 13, 1, 17), [], {"tfts": [tfts_new] + archive, "sysk": []}, {"tfts": True})
    assert [(c.show, c.published, why) for c, why in p.picks] == [("tfts", k(2026, 10, 12, 22), "new")]
    # Wednesday: Short Stuff comes at 18:00 → wait for it (no archive episode yet) …
    p = S.plan(EVENING, k(2026, 10, 14, 21), k(2026, 10, 14, 13, 17), [], {"tfts": archive, "sysk": []}, {"sysk": True})
    assert p.picks == [] and p.waiting == ["sysk"]
    # … and take it once it is there
    ss = C("sysk", k(2026, 10, 14, 18), title="Short Stuff: The Style Cycle")
    p = S.plan(EVENING, k(2026, 10, 14, 21), k(2026, 10, 14, 19, 17), [], {"tfts": archive, "sysk": [ss]}, {"sysk": True})
    assert [(c.show, why) for c, why in p.picks] == [("sysk", "new")]
    # Thursday: nothing new → the newest archive episode, at the first run
    p = S.plan(EVENING, k(2026, 10, 15, 21), k(2026, 10, 15, 1, 17), [], {"tfts": archive, "sysk": []}, {})
    assert [(c.published, why) for c, why in p.picks] == [(k(2026, 9, 24, 22), "catalog")]
    # an episode still waiting for its transcript holds the place but is not picked
    late = C("tfts", k(2026, 10, 15, 22), ready=False)
    p = S.plan(EVENING, k(2026, 10, 16, 21), k(2026, 10, 16, 9, 17), [], {"tfts": [late] + archive, "sysk": []}, {})
    assert p.picks == [] and p.waiting == ["tfts"]
    # a full occasion adds nothing
    assert S.plan(EVENING, k(2026, 10, 13, 21), k(2026, 10, 13, 3, 17), [tfts_new], {"tfts": archive}, {}).picks == []


# ------------------------------------------------------------------------------------------------ end to end

def _feed(title, items):
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0">',
           f"<channel><title>{title}</title><link>https://example.com/</link><description>d</description>"]
    for i, (t, when, minutes, tr) in enumerate(items):
        out.append(f"<item><title>{t}</title><pubDate>{format_datetime(when.astimezone(timezone.utc))}</pubDate>"
                   f"<guid>{title}-{i}-{when:%Y%m%d%H%M}</guid><link>https://example.com/{i}</link>"
                   f"<itunes:duration>{minutes * 60}</itunes:duration><description>About {t}.</description>"
                   f'<enclosure url="https://example.com/{title}/{i}.mp3" type="audio/mpeg" length="1"/>'
                   + (f'<podcast:transcript url="https://example.com/{title}/{i}.vtt" type="text/vtt"/>' if tr else "")
                   + "</item>")
    out.append("</channel></rss>")
    return "\n".join(out)


def _setup(tmp_path, monkeypatch):
    import pipeline.daily as D
    import pipeline.main as M
    from pipeline import build
    monkeypatch.setattr(M, "STATE_PATH", tmp_path / "state" / "seen.json")
    monkeypatch.setattr(M, "POSTED_PATH", tmp_path / "state" / "posted.json")
    monkeypatch.setattr(M, "SCHEDULE_STATUS_PATH", tmp_path / "state" / "schedule.json")
    monkeypatch.setattr(build, "DATA", tmp_path / "data")
    monkeypatch.setattr(build, "EPISODES_DIR", tmp_path / "data" / "episodes")
    monkeypatch.setattr(build, "INDEX_PATH", tmp_path / "data" / "index.json")
    monkeypatch.setattr(D, "DAILY_DIR", tmp_path / "data" / "daily")
    monkeypatch.setitem(M._overrides, "transcript_text", (FIX / "transistor_demo.vtt").read_text())
    monkeypatch.setitem(M._overrides, "resolve", False)
    monkeypatch.setitem(M._overrides, "audio_meta", {"dai": "yes", "content_duration": None, "ad_markers": [], "source": "fixture"})
    weeks = range(0, 6)
    base = k(2026, 10, 14, 0)
    feeds = {
        "tfts": _feed("tfts", sorted([(f"{331 - 2 * w}. Monday talk {w}", k(2026, 10, 12, 22) - timedelta(days=7 * w), 24, True) for w in weeks]
                                     + [(f"{330 - 2 * w}. Thursday talk {w}", k(2026, 10, 8, 22) - timedelta(days=7 * w), 18, True) for w in weeks]
                                     + [("12. Ancient talk", k(2021, 3, 1, 22), 20, False)], key=lambda x: x[1], reverse=True)),
        "sysk": _feed("sysk", sorted([(f"Short Stuff: Topic {w}", k(2026, 10, 7, 18) - timedelta(days=7 * w), 12, True) for w in weeks]
                                     + [(f"Long one {w}", k(2026, 10, 6, 18) - timedelta(days=7 * w), 48, True) for w in weeks]
                                     + [("Short Stuff: Today", k(2026, 10, 14, 18), 13, True)], key=lambda x: x[1], reverse=True)),
    }
    for name, xml in feeds.items():
        (tmp_path / f"{name}.xml").write_text(xml)
    cfg = {
        "site_url": "https://example.github.io/ps/",
        "schedule": {"evening": {"at": "21:00", "until": "23:30", "count": 1, "label": "🌙 하루 마무리 팟캐스트",
                                 "shows": ["tfts", "sysk"], "catalog": ["tfts"]}},
        "defaults": {"max_minutes": 40, "min_minutes": 6, "max_age_days": 14},
        "shows": [{"slug": "tfts", "name": "Think Fast, Talk Smart", "feed": "x", "speaker_labels": "none", "color": "#a00"},
                  {"slug": "sysk", "name": "Stuff You Should Know", "feed": "x", "title_include": "^short stuff", "max_minutes": 25,
                   "speaker_labels": "none"}],
    }
    import yaml
    (tmp_path / "shows.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return M, D, base


def _run(M, D, tmp_path, when, monkeypatch, feeds=("tfts", "sysk")):
    monkeypatch.setitem(M._overrides, "now", when.astimezone(timezone.utc))
    monkeypatch.setitem(D._now_override, "now", when.astimezone(timezone.utc))
    args = ["--mock", "--no-resolve", "--no-retime", "--config", str(tmp_path / "shows.yaml")]
    for f in feeds:
        args += ["--feed-file", f"{f}={tmp_path / (f + '.xml')}"]
    assert M.main(args) == 0
    assert D.main(["--config", str(tmp_path / "shows.yaml")]) == 0
    return json.loads((tmp_path / "state" / "seen.json").read_text())["episodes"]


def test_schedule_end_to_end_evening(tmp_path, monkeypatch):
    M, D, _ = _setup(tmp_path, monkeypatch)
    q = tmp_path / "data" / "daily" / "queue.json"
    # Tuesday 01:17: Monday night's TFTS → tonight 21:00
    seen = _run(M, D, tmp_path, k(2026, 10, 13, 1, 17), monkeypatch)
    done = {r["title"]: r for r in seen.values() if r.get("status") == "done"}
    assert list(done) == ["331. Monday talk 0"] and done["331. Monday talk 0"]["occasion"] == "2026-10-13-evening"
    posts = json.loads(q.read_text())["posts"]
    assert len(posts) == 1 and posts[0]["post_at"].startswith("2026-10-13T21:00") and posts[0]["slot"] == "evening"
    assert posts[0]["text"].startswith("🌙 하루 마무리 팟캐스트 · Think Fast, Talk Smart (10/12)\n331. Monday talk 0")
    assert posts[0]["until_ms"] - posts[0]["post_at_ms"] == 150 * 60 * 1000
    lines = posts[0]["text"].splitlines()
    assert lines[2] == "⏱ 24분" and lines[-1].startswith("▶ 스크립트·단어·표현 보기: https://example.github.io/ps/episode.html?id=")
    assert "🔑" not in posts[0]["text"] and "📝" not in posts[0]["text"]
    # later runs the same evening add nothing
    _run(M, D, tmp_path, k(2026, 10, 13, 19, 17), monkeypatch)
    assert len(json.loads(q.read_text())["posts"]) == 1
    # Wednesday 13:17: Short Stuff is due at 18:00 → wait; 19:17: it is there
    seen = _run(M, D, tmp_path, k(2026, 10, 14, 13, 17), monkeypatch)
    assert not [r for r in seen.values() if r.get("occasion") == "2026-10-14-evening"]
    st = json.loads((tmp_path / "state" / "schedule.json").read_text())["occasions"]["2026-10-14-evening"]
    assert st["waiting_for"] == ["sysk"] and st["adding"] == [] and "sysk" in st["expected"]
    seen = _run(M, D, tmp_path, k(2026, 10, 14, 19, 17), monkeypatch)
    wed = [r for r in seen.values() if r.get("occasion") == "2026-10-14-evening"]
    assert [r["title"] for r in wed] == ["Short Stuff: Today"]
    # Thursday: nothing new → an earlier TFTS episode (the newest one not shared yet), marked as such
    seen = _run(M, D, tmp_path, k(2026, 10, 15, 1, 17), monkeypatch)
    thu = [r for r in seen.values() if r.get("occasion") == "2026-10-15-evening"]
    assert [(r["title"], r["pick"]) for r in thu] == [("330. Thursday talk 0", "catalog")]
    posts = json.loads(q.read_text())["posts"]
    assert [p["occasion"] for p in posts] == ["2026-10-13-evening", "2026-10-14-evening", "2026-10-15-evening"]
    assert "(지난 회차 · 2026/10/8)" in posts[-1]["text"].splitlines()[0]
    posted = json.loads((tmp_path / "state" / "posted.json").read_text())
    assert len(posted) == 3
    # the archive per occasion exists; no morning slot → no latest.json in the old format
    assert (tmp_path / "data" / "daily" / "2026-10-15-evening.json").exists()
    assert not (tmp_path / "data" / "daily" / "latest.json").exists()


def test_schedule_unposted_episode_is_reused_not_rebuilt(tmp_path, monkeypatch):
    M, D, _ = _setup(tmp_path, monkeypatch)
    args = ["--mock", "--no-resolve", "--no-retime", "--config", str(tmp_path / "shows.yaml"),
            "--feed-file", f"tfts={tmp_path / 'tfts.xml'}", "--feed-file", f"sysk={tmp_path / 'sysk.xml'}"]
    # Saturday 01:17: nothing new → an archive episode is built, but never queued (say the run died before the queue step)
    monkeypatch.setitem(M._overrides, "now", k(2026, 10, 17, 1, 17).astimezone(timezone.utc))
    assert M.main(args) == 0
    seen = json.loads((tmp_path / "state" / "seen.json").read_text())["episodes"]
    (key, first), = [(kk, r) for kk, r in seen.items() if r.get("occasion") == "2026-10-17-evening"]
    assert first["pick"] == "catalog" and first["title"] == "331. Monday talk 0"
    n_files = len(list((tmp_path / "data" / "episodes").glob("*.json")))
    # Sunday 01:17: Saturday's occasion is over → the episode is free again and joins Sunday's without a rebuild
    monkeypatch.setitem(M._overrides, "now", k(2026, 10, 18, 1, 17).astimezone(timezone.utc))
    assert M.main(args) == 0
    seen = json.loads((tmp_path / "state" / "seen.json").read_text())["episodes"]
    assert seen[key]["occasion"] == "2026-10-18-evening" and seen[key]["done_at"] == first["done_at"]
    assert len(list((tmp_path / "data" / "episodes").glob("*.json"))) == n_files
    # queued once it is picked up by the queue step
    monkeypatch.setitem(D._now_override, "now", k(2026, 10, 18, 1, 20).astimezone(timezone.utc))
    assert D.main(["--config", str(tmp_path / "shows.yaml")]) == 0
    posts = json.loads((tmp_path / "data" / "daily" / "queue.json").read_text())["posts"]
    assert [(p["occasion"], p["title"]) for p in posts] == [("2026-10-18-evening", "331. Monday talk 0")]
