"""App backend worker: keeps the show catalog fresh and builds study packs that app users asked for.

Runs on GitHub Actions (.github/workflows/app-worker.yml), talking to Supabase with the service key:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   (repository secrets)
  ANTHROPIC_API_KEY                    (study pack + translations)

  python -m pipeline.app_worker refresh        # RSS of every show → new rows in `episodes`
  python -m pipeline.app_worker process        # episodes with status=queued → pack → storage → ready (then sync)
  python -m pipeline.app_worker prefetch       # newest episode of every followed show → status=prefetch
  python -m pipeline.app_worker process --status prefetch   # build those (separate, low-priority job)
  python -m pipeline.app_worker seed FILE      # load the verified catalog (tools/catalog/catalog.json) into `shows`
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from .feeds import Episode, parse_feed, strip_html
from .llm import StudyGenerator
from .main import process_episode, show_filter, web_transcript_ready
from .util import http_get_text, http_session, log, setup_logging, utcnow_iso

KEEP_PER_SHOW = 30            # newest episodes listed per show
NPR_CHECK = 4                 # newest NPR episodes whose transcript page is checked on every refresh


class Supa:
    """Minimal PostgREST + Storage client (service role: bypasses RLS)."""

    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.h = {"apikey": key, "Authorization": f"Bearer {key}"}
        self.s = requests.Session()

    def select(self, table: str, query: str) -> list[dict]:
        r = self.s.get(f"{self.url}/rest/v1/{table}?{query}", headers=self.h, timeout=60)
        r.raise_for_status()
        return r.json()

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        if not rows:
            return
        r = self.s.post(f"{self.url}/rest/v1/{table}?on_conflict={on_conflict}", json=rows, timeout=60,
                        headers={**self.h, "Prefer": "resolution=merge-duplicates,return=minimal"})
        r.raise_for_status()

    def update(self, table: str, match: str, values: dict) -> list[dict]:
        r = self.s.patch(f"{self.url}/rest/v1/{table}?{match}", json=values, timeout=60,
                         headers={**self.h, "Prefer": "return=representation"})
        r.raise_for_status()
        return r.json()

    def put_object(self, bucket: str, path: str, data: bytes, content_type: str = "application/json") -> None:
        r = self.s.post(f"{self.url}/storage/v1/object/{bucket}/{path}", data=data, timeout=120,
                        headers={**self.h, "Content-Type": content_type, "x-upsert": "true"})
        r.raise_for_status()


def supa() -> Supa:
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set")
    return Supa(url, key)


def show_config(row: dict) -> dict:
    """A `shows` row → the show dict the pipeline expects."""
    cfg = {"slug": str(row["id"])[:8], "name": row["title"], "publisher": row.get("author") or "",
           "color": "#3b5bdb", "feed": row["feed_url"], "speaker_labels": row.get("speaker_labels") or "auto",
           "max_minutes": row.get("max_minutes") or 60, "min_minutes": 4,
           "title_include": row.get("title_include"), "title_exclude": row.get("title_exclude"),
           "style": (row.get("description") or "")[:300]}
    if row["path"] == "npr":
        cfg.update(transcript="web", parser=row.get("parser") or "npr")
    return cfg


def episode_row(show: dict, ep: Episode, path: str) -> dict:
    return {"show_id": show["id"], "guid": ep.guid, "title": ep.title, "published_at": ep.published_iso,
            "duration_sec": ep.duration_sec, "audio_url": ep.audio_url, "episode_url": ep.link,
            "image_url": ep.image_url, "description": strip_html(ep.description_html, 1500),
            "has_transcript": bool(ep.best_transcript) or path == "npr"}


def refresh(db: Supa, only: str | None = None) -> int:
    session = http_session()
    shows = db.select("shows", "select=*" + (f"&id=eq.{only}" if only else ""))
    n = 0
    for sh in shows:
        try:
            _, eps = parse_feed(http_get_text(session, sh["feed_url"]))
        except Exception as e:  # noqa: BLE001
            log.error("feed failed for %s: %s", sh["title"], e)
            continue
        cfg = show_config(sh)
        ok = show_filter(cfg)
        kept = [e for e in eps if ok(e)][:KEEP_PER_SHOW]
        rows = [episode_row(sh, e, sh["path"]) for e in kept]
        if sh["path"] == "npr":
            # NPR posts the transcript hours (sometimes a day) after the audio: keep the newest episodes
            # hidden in the app (has_transcript=false) until their transcript page actually exists
            for e, row in zip(kept[:NPR_CHECK], rows[:NPR_CHECK]):
                row["has_transcript"] = web_transcript_ready(session, cfg, e)
        # don't overwrite worker-owned columns (status, pack paths) on existing rows: upsert only listing fields
        db.upsert("episodes", rows, "show_id,guid")
        db.update("shows", f"id=eq.{sh['id']}", {"refreshed_at": utcnow_iso()})
        n += len(rows)
        log.info("refresh %s: %d episodes", sh["title"], len(rows))
    return n


def prefetch(db: Supa, per_show: int = 1) -> int:
    """Mark the newest unbuilt episode(s) of every show someone follows, so it is ready before anyone opens it."""
    followed = {r["show_id"] for r in db.select("subscriptions", "select=show_id")}
    n = 0
    for sid in followed:
        eps = db.select("episodes", f"select=id,status,published_at&show_id=eq.{sid}&has_transcript=eq.true"
                                     f"&order=published_at.desc&limit={per_show}")
        for e in eps:
            if e["status"] == "none":
                if db.update("episodes", f"id=eq.{e['id']}&status=eq.none", {"status": "prefetch", "requested_at": utcnow_iso()}):
                    n += 1
    log.info("prefetch: %d new episode(s) of %d followed shows", n, len(followed))
    return n


def process(db: Supa, max_n: int = 4, mock: bool = False, status: str = "queued") -> int:
    """Build study packs. Audio sync is a separate, later step (`sync`) so the app can open the episode sooner."""
    queued = db.select("episodes", "select=*,shows(*)&status=eq.%s&order=requested_at.asc&limit=%d" % (status, max_n))
    if not queued:
        log.info("nothing queued")
        return 0
    session = http_session()
    gen = StudyGenerator(mock=mock)
    done = 0
    for row in queued:
        claimed = db.update("episodes", f"id=eq.{row['id']}&status=eq.{status}", {"status": "processing"})
        if not claimed:
            continue                                   # another worker took it
        sh = row["shows"]
        cfg = show_config(sh)
        log.info("▶ %s — %s", sh["title"], row["title"])
        try:
            _, eps = parse_feed(http_get_text(session, sh["feed_url"]))
            ep = next((e for e in eps if e.guid == row["guid"]), None)
            if ep is None:
                raise RuntimeError("episode no longer in the feed")
            if not ep.best_transcript and cfg.get("transcript") != "web":
                db.update("episodes", f"id=eq.{row['id']}", {"status": "no_transcript", "has_transcript": False})
                continue
            doc = process_episode(session, gen, cfg, ep, translate=True)
            doc["id"] = row["id"]
            doc["show"].update(slug=str(sh["id"]), name=sh["title"], image=sh.get("image_url"))
            db.put_object("episodes", f"{row['id']}.json", json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode())
            # the pack is all the app needs: mark it ready right away, then add the audio sync (slow) afterwards
            db.update("episodes", f"id=eq.{row['id']}", {
                "status": "ready", "pack_path": f"{row['id']}.json", "error": None,
                "one_liner_ko": (doc.get("study") or {}).get("one_liner_ko"), "ready_at": utcnow_iso(),
                "duration_sec": doc.get("duration_sec")})
            log.info("  ✓ ready (pack)")
            done += 1
        except Exception as e:  # noqa: BLE001
            from .webtranscript import TranscriptNotReady
            # transcript not published yet (NPR posts some a day later): back to the low-priority hourly job.
            # Never straight back to 'queued' — that fires the database's dispatch trigger again at once (a loop).
            new = "prefetch" if isinstance(e, TranscriptNotReady) else "failed"
            db.update("episodes", f"id=eq.{row['id']}", {"status": new, "error": str(e)[:300],
                                                       "attempts": (row.get("attempts") or 0) + (0 if new == "prefetch" else 1)})
            log.error("  ✗ %s", e)
    return done


def sync_pending(db: Supa, max_n: int = 10) -> int:
    """Add the audio↔transcript sync to ready episodes that don't have it yet (needs requirements-sync.txt + ffmpeg)."""
    from . import sync as SY
    rows = db.select("episodes", "select=id,title,pack_path&status=eq.ready&sync_path=is.null&pack_path=not.is.null"
                                 "&order=ready_at.desc&limit=%d" % max_n)
    if not rows:
        return 0
    session, asr, n = http_session(), None, 0
    for row in rows:
        try:
            r = db.s.get(f"{db.url}/storage/v1/object/episodes/{row['pack_path']}", headers=db.h, timeout=120)
            r.raise_for_status()
            doc = r.json()
            if asr is None and not (doc.get("audio_meta") or {}).get("fixed"):
                asr = SY.Asr()
            sync = SY.build(doc, asr, session)
            db.put_object("episodes", f"{row['id']}.sync.json", json.dumps(sync, separators=(",", ":")).encode())
            db.update("episodes", f"id=eq.{row['id']}", {"sync_path": f"{row['id']}.sync.json"})
            n += 1
            log.info("synced %s", row["title"])
        except Exception as e:  # noqa: BLE001
            log.error("sync failed for %s: %s", row["title"], e)
    return n


def seed(db: Supa, path: Path) -> int:
    rows = json.loads(path.read_text())["shows"]
    keep = ("feed_url", "title", "author", "image_url", "description", "language", "path", "parser", "speaker_labels",
            "max_minutes", "title_include", "title_exclude", "category", "level")
    db.upsert("shows", [dict({k: r.get(k) for k in keep}, catalog=True) for r in rows], "feed_url")
    log.info("seeded %d catalog shows", len(rows))
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["refresh", "process", "prefetch", "sync", "seed"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--max", type=int, default=4)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--status", default="queued", choices=["queued", "prefetch"])
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    db = supa()
    if a.cmd == "refresh":
        refresh(db, a.arg)
    elif a.cmd == "process":
        process(db, a.max, a.mock, a.status)
    elif a.cmd == "prefetch":
        prefetch(db)
    elif a.cmd == "sync":
        sync_pending(db, a.max)
    else:
        seed(db, Path(a.arg or "tools/catalog/catalog.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
