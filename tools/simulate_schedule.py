"""Replay the posting schedule over the past days with the real feeds (run on GitHub Actions).

Starts from an empty history N days ago and steps through the pipeline's run times (cron), revealing feed
items as they were published. Episodes are "built" instantly (no API, no audio), then queued like the real
thing. Prints, per occasion, what would have gone out and when each episode was ready.
Output: tools/simulate_schedule.txt
"""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pipeline.daily as D  # noqa: E402
import pipeline.main as M  # noqa: E402
from pipeline import build, schedule as S  # noqa: E402
from pipeline.util import read_json, write_json  # noqa: E402

KST = S.KST


def run_times(start: datetime, end: datetime) -> list[datetime]:
    """KST times of the scheduled pipeline runs (update.yml cron, UTC → KST)."""
    out = []
    d = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while d < end:
        for h in range(1, 24, 2):
            out.append(d.replace(hour=h, minute=17))
        for h, m in ((5, 47), (6, 37), (19, 47)):
            out.append(d.replace(hour=h, minute=m))
        d += timedelta(days=1)
    return sorted(t for t in out if start <= t < end)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    args = ap.parse_args()
    cfg = M.load_config(M.CONFIG_PATH)
    slots = S.load_slots(cfg)
    by_slug = {s["slug"]: s for s in cfg["shows"]}
    tmp = Path(tempfile.mkdtemp())
    session = M.http_session()
    feed_files = {}
    for sl in slots:
        for slug in sl.all_shows():
            if slug not in feed_files:
                p = tmp / f"{slug}.xml"
                p.write_text(M.http_get_text(session, by_slug[slug]["feed"]), encoding="utf-8")
                feed_files[slug] = str(p)
    M.STATE_PATH, M.POSTED_PATH, M.SCHEDULE_STATUS_PATH = tmp / "seen.json", tmp / "posted.json", tmp / "schedule.json"
    build.DATA, build.EPISODES_DIR, build.INDEX_PATH = tmp / "data", tmp / "data" / "episodes", tmp / "data" / "index.json"
    D.DAILY_DIR = tmp / "data" / "daily"
    built_at: dict[str, datetime] = {}

    def fake_produce(session, gen, show, ep, key, rec, seen, state, **kw):
        doc_id = M.episode_id(show["slug"], ep)
        doc = {"id": doc_id, "show": {"slug": show["slug"], "name": show["name"]}, "title": ep.title,
               "published_at": ep.published_iso, "duration_sec": ep.duration_sec, "study": {"one_liner_ko": "", "expressions": []}}
        write_json(build.episode_path(doc_id), doc)
        rec.update({"status": "done", "id": doc_id, "title": ep.title, "published_at": ep.published_iso,
                    "done_at": M._overrides["now"].isoformat()})
        built_at[doc_id] = M._overrides["now"]
        seen[key] = rec
        write_json(M.STATE_PATH, state)
        return True, False

    M.produce = fake_produce
    now = datetime.now(KST)
    start = (now - timedelta(days=args.days)).replace(hour=12, minute=0, second=0, microsecond=0)
    state = {"episodes": {}}
    fake_args = SimpleNamespace(max_new=8, no_translate=True, verbose=False)
    lines = [f"replay {start:%Y-%m-%d %H:%M} → {now:%Y-%m-%d %H:%M} KST (runs at :17 every 2 h + 05:47, 06:37, 19:47)", ""]
    for t in run_times(start, now):
        M._overrides["now"] = t.astimezone(timezone.utc)
        D._now_override["now"] = t.astimezone(timezone.utc)
        M.run_schedule(cfg, slots, state["episodes"], state, session, None, fake_args, t.astimezone(timezone.utc), feed_files)
        write_json(M.STATE_PATH, state)
        D.main([])
    queue = read_json(D.DAILY_DIR / "queue.json", {"posts": []})["posts"]
    # all occasions (queue keeps 3 days; the archive files keep everything)
    occ = sorted(D.DAILY_DIR.glob("20*-*.json"))
    for f in occ:
        data = read_json(f, {})
        posts = data.get("posts") or []
        sl = next((s for s in slots if data["occasion"].endswith(s.name)), None)
        o = S.occasion_from_key(sl, data["occasion"]) if sl else None
        lines.append(f"{data['occasion']} ({o:%a %H:%M} KST)" if o else data["occasion"])
        for p in posts:
            pub = datetime.fromisoformat(p["post_at"]) if p.get("post_at") else None
            b = built_at.get(p["id"])
            late = f"  ← ready {b.astimezone(KST):%a %H:%M}" + (" LATE" if b and o and b > o else "")
            ep_pub = read_json(build.episode_path(p["id"]), {}).get("published_at", "")
            ep_pub = datetime.fromisoformat(ep_pub.replace("Z", "+00:00")).astimezone(KST).strftime("%a %m-%d %H:%M") if ep_pub else "?"
            lines.append(f"   [{p['pick']:8}] {p['show']['slug']:22} pub {ep_pub}  {round((read_json(build.episode_path(p['id']), {}).get('duration_sec') or 0) / 60)}m  {p['title'][:60]}{late}")
        if sl and len(posts) < sl.count:
            lines.append(f"   !! only {len(posts)}/{sl.count}")
    out = "\n".join(lines)
    print(out)
    Path("tools/simulate_schedule.txt").write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
