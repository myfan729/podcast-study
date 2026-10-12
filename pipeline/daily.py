"""Daily post: pick the newest episode not yet shared and write a chat-ready card (text + link).

Runs at 07:00 KST (.github/workflows/daily.yml). Output:
  docs/data/daily/latest.json, docs/data/daily/<date>.json   → docs/post.html shows the card with 복사/공유 buttons
  state/posted.json                                            → which episodes were already shared
Optional delivery (set as repository secrets): TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID → the card is sent to you on
Telegram so one tap forwards it into the KakaoTalk room.

Usage: python -m pipeline.daily [--dry-run] [--force <id-substring>] [--max-age-days 3]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import build
from .main import CONFIG_PATH, ROOT, load_config
from .util import log, read_json, setup_logging, utcnow_iso, write_json

POSTED_PATH = ROOT / "state" / "posted.json"
DAILY_DIR = build.DATA / "daily"
KST = timezone(timedelta(hours=9))


def fmt_dur(sec: int | None) -> str:
    sec = int(sec or 0)
    return f"{sec // 60}분" if sec < 3600 else f"{sec // 3600}시간 {sec % 3600 // 60}분"


def pick(posted: dict, max_age_days: int, force: str | None) -> dict | None:
    docs = [read_json(p, None) for p in build.EPISODES_DIR.glob("*.json")]
    docs = [d for d in docs if d and not d.get("demo") and not (d.get("study") or {}).get("mock")]
    if force:
        cands = [d for d in docs if force in d["id"] or force.lower() in d["title"].lower()]
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cands = [d for d in docs if d["id"] not in posted
                 and datetime.fromisoformat(d["published_at"].replace("Z", "+00:00")) >= cutoff]
    cands.sort(key=lambda d: d["published_at"], reverse=True)
    return cands[0] if cands else None


def compose(doc: dict, site_url: str) -> dict:
    study = doc.get("study") or {}
    link = f"{site_url.rstrip('/')}/episode.html?id={doc['id']}"
    exprs = [e["expression"] for e in (study.get("expressions") or [])[:3]]
    cefr = (study.get("difficulty") or {}).get("cefr", "")
    d = datetime.fromisoformat(doc["published_at"].replace("Z", "+00:00")).astimezone(KST)
    lines = [
        f"🎧 오늘의 팟캐스트 · {doc['show']['name']} ({d.strftime('%-m/%-d')})",
        f"{doc['title']}",
        f"⏱ {fmt_dur(doc.get('duration_sec'))}" + (f" · {cefr}" if cefr else ""),
        "",
        study.get("one_liner_ko", ""),
    ]
    if exprs:
        lines += ["", "🔑 오늘의 표현: " + " · ".join(exprs)]
    lines += ["", f"▶ 스크립트·요약·표현 보기: {link}"]
    text = "\n".join(l for l in lines if l is not None)
    return {"id": doc["id"], "date_kst": datetime.now(KST).strftime("%Y-%m-%d"), "title": doc["title"], "show": doc["show"],
            "link": link, "one_liner_ko": study.get("one_liner_ko", ""), "expressions": exprs, "cefr": cefr,
            "duration_sec": doc.get("duration_sec"), "image": doc.get("image_url"), "text": text, "generated_at": utcnow_iso()}


def send_telegram(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    import requests
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text, "disable_web_page_preview": False}, timeout=30)
    r.raise_for_status()
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", help="post this episode (id/title substring) even if already posted")
    ap.add_argument("--max-age-days", type=int, default=3, help="only episodes published within this many days")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config(Path(CONFIG_PATH))
    site_url = os.environ.get("SITE_URL") or cfg.get("site_url") or "https://example.github.io/podcast-study/"
    posted = read_json(POSTED_PATH, {})
    doc = pick(posted, args.max_age_days, args.force)
    if not doc:
        log.info("daily: nothing new to post")
        return 0
    card = compose(doc, site_url)
    print(card["text"])
    if args.dry_run:
        return 0
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DAILY_DIR / "latest.json", card)
    write_json(DAILY_DIR / f"{card['date_kst']}.json", card)
    posted[doc["id"]] = {"posted_at": utcnow_iso(), "date_kst": card["date_kst"]}
    write_json(POSTED_PATH, posted)
    try:
        if send_telegram(card["text"]):
            log.info("daily: sent to Telegram")
    except Exception as e:  # noqa: BLE001
        log.error("daily: telegram failed: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
