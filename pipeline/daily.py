"""Chat posts: turn the episodes made for each posting occasion (config `schedule`) into ready-to-send messages.

Runs after every pipeline run (.github/workflows/update.yml) and around the posting times (daily.yml). Output:
  docs/data/daily/queue.json        → the KakaoTalk bot (tools/kakao_bot.js) posts every message at its time
  docs/data/daily/<occasion>.json   → archive, e.g. 2026-10-15-morning.json
  docs/data/daily/latest.json       → the latest morning card in the old one-card format (older bot, post.html)
  state/posted.json                 → episodes already queued (never queued twice)
Optional delivery (repository secrets): TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID → each message is also sent to you
on Telegram.

Usage: python -m pipeline.daily [--dry-run] [--force <id-substring>]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import build
from . import schedule as S
from . import main as M
from .util import log, read_json, setup_logging, utcnow_iso, write_json

DAILY_DIR = build.DATA / "daily"
QUEUE_KEEP = timedelta(days=3)
KST = S.KST
DEFAULT_LABELS = {"morning": "🌅 아침 팟캐스트", "evening": "🌙 하루 마무리 팟캐스트"}
_now_override: dict = {"now": None}


def fmt_dur(sec: int | None) -> str:
    sec = int(sec or 0)
    return f"{sec // 60}분" if sec < 3600 else f"{sec // 3600}시간 {sec % 3600 // 60}분"


def compose_text(doc: dict, site_url: str, header: str) -> tuple[str, str]:
    study = doc.get("study") or {}
    link = f"{site_url.rstrip('/')}/episode.html?id={doc['id']}"
    lines = [header, doc["title"], f"⏱ {fmt_dur(doc.get('duration_sec'))}", "", study.get("one_liner_ko", ""),
             "", f"▶ 스크립트·단어·표현 보기: {link}"]
    return "\n".join(lines), link


def compose_post(doc: dict, slot: S.Slot, o: datetime, site_url: str, pick: str = "new") -> dict:
    pub = datetime.fromisoformat(doc["published_at"].replace("Z", "+00:00")).astimezone(KST)
    label = slot.label or DEFAULT_LABELS.get(slot.name, "🎧 오늘의 팟캐스트")
    when = f"지난 회차 · {pub.strftime('%Y/%-m/%-d')}" if pick == "catalog" else pub.strftime("%-m/%-d")
    text, link = compose_text(doc, site_url, f"{label} · {doc['show']['name']} ({when})")
    u = S.until(slot, o)
    return {"id": doc["id"], "occasion": S.occasion_key(slot, o), "slot": slot.name, "order": slot.order_of(doc["show"]["slug"]),
            "post_at": o.isoformat(), "post_at_ms": int(o.timestamp() * 1000),
            "until": u.isoformat(), "until_ms": int(u.timestamp() * 1000),
            "title": doc["title"], "show": doc["show"], "link": link, "pick": pick,
            "one_liner_ko": (doc.get("study") or {}).get("one_liner_ko", ""),
            "duration_sec": doc.get("duration_sec"), "image": doc.get("image_url"), "text": text, "queued_at": utcnow_iso()}


def send_telegram(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    import requests
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text, "disable_web_page_preview": False}, timeout=30)
    r.raise_for_status()
    return True


def _docs() -> list[dict]:
    docs = [read_json(p, None) for p in build.EPISODES_DIR.glob("*.json")]
    return [d for d in docs if d and not d.get("demo") and not (d.get("study") or {}).get("mock")]


def write_outputs(queue: dict, new_posts: list[dict], slots: list[S.Slot], now: datetime) -> None:
    now_ms = int(now.timestamp() * 1000)
    keep = [p for p in queue.get("posts", []) if p.get("until_ms", 0) > now_ms - QUEUE_KEEP.total_seconds() * 1000
            and p["id"] not in {n["id"] for n in new_posts}]
    queue["posts"] = sorted(keep + new_posts, key=lambda p: (p.get("post_at_ms", 0), p.get("order", 9)))
    queue["generated_at"] = utcnow_iso()
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DAILY_DIR / "queue.json", queue)
    for okey in sorted({p["occasion"] for p in new_posts if p.get("occasion")}):
        posts = [p for p in queue["posts"] if p.get("occasion") == okey]
        write_json(DAILY_DIR / f"{okey}.json", {"occasion": okey, "posts": posts})
    # the old one-card format: the latest morning occasion (older bot versions post it once between 07:00 and 12:00)
    morning = [p for p in queue["posts"] if p.get("slot") == "morning"]
    if morning:
        okey = morning[-1]["occasion"]
        posts = [p for p in morning if p["occasion"] == okey]
        first = posts[0]
        write_json(DAILY_DIR / "latest.json", dict(first, id=okey, date_kst=okey[:10],
                                                  text="\n\n━━━━━━━━━━\n\n".join(p["text"] for p in posts),
                                                  generated_at=utcnow_iso()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", help="post this episode (id/title substring) right now, even if it was posted before")
    ap.add_argument("--config", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    cfg = M.load_config(Path(args.config or M.CONFIG_PATH))
    site_url = os.environ.get("SITE_URL") or cfg.get("site_url") or "https://example.github.io/podcast-study/"
    slots = S.load_slots(cfg)
    if not slots and not args.force:
        log.info("daily: no `schedule` in config/shows.yaml — nothing to post")
        return 0
    now = _now_override["now"] or datetime.now(timezone.utc)
    posted = read_json(M.POSTED_PATH, {})
    seen = read_json(M.STATE_PATH, {"episodes": {}}).get("episodes", {})
    queue = read_json(DAILY_DIR / "queue.json", {"posts": []})
    new_posts: list[dict] = []

    if args.force:
        cands = sorted((d for d in _docs() if args.force in d["id"] or args.force.lower() in d["title"].lower()),
                       key=lambda d: d["published_at"], reverse=True)
        if not cands:
            log.info("daily: no episode matches %r", args.force)
            return 1
        now_k = now.astimezone(KST)
        extra = S.Slot(name="extra", at=now_k.strftime("%H:%M"), until=(now_k + timedelta(hours=3)).strftime("%H:%M"),
                       label="🎧 오늘의 팟캐스트")
        post = compose_post(cands[0], extra, now_k.replace(second=0, microsecond=0), site_url)
        post["id"] = f"{post['id']}~{now_k.strftime('%m%d%H%M')}"         # a new id: the bot posts it even if posted before
        new_posts.append(post)
    else:
        for sl in slots:
            o = S.occasion(sl, now)
            okey = S.occasion_key(sl, o)
            if now >= S.until(sl, o):
                continue
            recs = [(k.split(":")[0], r) for k, r in seen.items() if r.get("occasion") == okey and r.get("status") == "done"
                    and r.get("id") and r["id"] not in posted]
            recs.sort(key=lambda sr: (sl.order_of(sr[0]), sr[1].get("published_at", "")))
            for _slug, r in recs:
                doc = read_json(build.episode_path(r["id"]), None)
                if not doc:
                    continue
                new_posts.append(compose_post(doc, sl, o, site_url, r.get("pick", "new")))
    if not new_posts:
        log.info("daily: nothing new to queue")
        return 0
    for p in new_posts:
        print(f"--- {p['occasion']} @ {p['post_at']}\n{p['text']}\n")
    if args.dry_run:
        return 0
    for p in new_posts:
        if not args.force:
            posted[p["id"]] = {"queued_at": utcnow_iso(), "occasion": p["occasion"], "date_kst": p["occasion"][:10], "post_at": p["post_at"]}
    write_outputs(queue, new_posts, slots, now)
    write_json(M.POSTED_PATH, posted)
    for p in new_posts:
        try:
            if send_telegram(p["text"]):
                log.info("daily: sent to Telegram")
        except Exception as e:  # noqa: BLE001
            log.error("daily: telegram failed: %s", e)
    log.info("daily: queued %d post(s): %s", len(new_posts), ", ".join(f"{p['occasion']}:{p['show']['slug']}" for p in new_posts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
