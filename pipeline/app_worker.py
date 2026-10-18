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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .feeds import Episode, parse_feed, strip_html
from .llm import StudyGenerator
from .main import process_episode, show_filter, web_transcript_ready
from .util import http_get_text, http_session, log, setup_logging, utcnow_iso

KEEP_PER_SHOW = 30            # newest episodes listed per show
RECHECK_DAYS = 10             # NPR: keep looking for a late transcript this long after publication
RECHECK_EVERY = timedelta(hours=3)


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
        if r.status_code >= 400:
            raise RuntimeError(f"upsert {table}: {r.status_code} {r.text[:400]}")

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
    elif row["path"] == "web":                      # publisher web pages (BBC Learning English, ABC, …)
        cfg.update(transcript="web", parser=row.get("parser") or "generic")
        if row.get("page_url"):
            cfg["page_url"] = row["page_url"]
    return cfg


def episode_row(show: dict, ep: Episode, path: str) -> dict:
    return {"show_id": show["id"], "guid": ep.guid, "title": ep.title, "published_at": ep.published_iso,
            "duration_sec": ep.duration_sec, "audio_url": ep.audio_url, "episode_url": ep.link,
            "image_url": ep.image_url, "description": strip_html(ep.description_html, 1500),
            "has_transcript": bool(ep.best_transcript) or path in ("npr", "web")}


def mark_npr_transcripts(db: Supa, session, sh: dict, cfg: dict, kept: list, rows: list[dict]) -> None:
    """NPR posts transcripts hours to a day after the audio — and for some episodes never. Show an episode in
    the app only once its transcript page really has one. Checks are cached in transcript_checked_at:
    re-checked every few hours while the episode is new, given up after RECHECK_DAYS."""
    known = {r["guid"]: r for r in db.select("episodes", f"select=guid,status,has_transcript,transcript_checked_at&show_id=eq.{sh['id']}")}
    now = datetime.now(timezone.utc)
    for e, row in zip(kept, rows):
        k = known.get(e.guid) or {}
        if k.get("status") == "ready":
            row["has_transcript"] = True; row["transcript_checked_at"] = k.get("transcript_checked_at"); continue
        checked = k.get("transcript_checked_at")
        checked = datetime.fromisoformat(checked.replace("Z", "+00:00")) if checked else None
        age = now - e.published_at if e.published_at else timedelta(days=0)
        stale = checked is None or (age < timedelta(days=RECHECK_DAYS) and now - checked > RECHECK_EVERY)
        if not stale:
            row["has_transcript"] = bool(k.get("has_transcript")); row["transcript_checked_at"] = k.get("transcript_checked_at"); continue
        row["has_transcript"] = web_transcript_ready(session, cfg, e)
        row["transcript_checked_at"] = utcnow_iso()
        if not row["has_transcript"] and k.get("status") == "prefetch":
            db.update("episodes", f"show_id=eq.{sh['id']}&guid=eq.{requests.utils.quote(e.guid, safe='')}", {"status": "none"})


def refresh(db: Supa, only: str | None = None) -> int:
    session = http_session()
    shows = db.select("shows", "select=*" + (f"&id=eq.{only}" if only else ""))
    n = 0
    for sh in shows:
        try:
            meta, eps = parse_feed(http_get_text(session, sh["feed_url"]))
        except Exception as e:  # noqa: BLE001
            log.error("feed failed for %s: %s", sh["title"], e)
            continue
        if not sh.get("description") and meta.get("description"):
            # the show's own description (used for its Korean one-liner); a one-liner written without it is redone
            db.update("shows", f"id=eq.{sh['id']}", {"description": strip_html(meta["description"], 1500), "intro_ko": None})
        cfg = show_config(sh)
        ok = show_filter(cfg)
        kept = [e for e in eps if ok(e)][:KEEP_PER_SHOW]
        rows = [episode_row(sh, e, sh["path"]) for e in kept]
        if sh["path"] in ("npr", "web"):
            mark_npr_transcripts(db, session, sh, cfg, kept, rows)
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


def write_intros(db: Supa, max_eps: int = 300) -> int:
    """Short Korean one-liners (small type in the app) for catalog shows and recent episodes that lack one."""
    gen = StudyGenerator()
    n = 0
    shows = db.select("shows", "select=id,title,author,description&catalog=eq.true&intro_ko=is.null&limit=200")
    for k in range(0, len(shows), 12):
        part = shows[k:k + 12]
        try:
            got = gen.short_intros([(s["id"], f"{s['title']} ({s.get('author') or ''})\n{strip_html(s.get('description') or '', 600)}") for s in part], "show")
        except Exception as e:  # noqa: BLE001
            log.error("show intros failed: %s", e); continue
        for sid, ko in got.items():
            db.update("shows", f"id=eq.{sid}", {"intro_ko": ko[:80]}); n += 1
    since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    eps = db.select("episodes", f"select=id,title,description&intro_ko=is.null&has_transcript=eq.true&published_at=gte.{since}"
                                f"&order=published_at.desc&limit={max_eps}")
    for k in range(0, len(eps), 15):
        part = eps[k:k + 15]
        try:
            got = gen.short_intros([(e["id"], f"{e['title']}\n{(e.get('description') or '')[:500]}") for e in part], "episode")
        except Exception as e:  # noqa: BLE001
            log.error("episode intros failed: %s", e); continue
        for eid, ko in got.items():
            db.update("episodes", f"id=eq.{eid}", {"intro_ko": ko[:90]}); n += 1
    log.info("intros: wrote %d", n)
    return n


def seed(db: Supa, path: Path) -> int:
    rows = json.loads(path.read_text())["shows"]
    keep = ("feed_url", "title", "author", "image_url", "description", "language", "path", "parser", "speaker_labels",
            "max_minutes", "title_include", "title_exclude", "category", "level", "page_url")
    db.upsert("shows", [dict({k: r.get(k) for k in keep}, catalog=True) for r in rows], "feed_url")
    # shows dropped from the catalog (they can't be served well): out of the catalog, and nobody follows them
    listed = {r["feed_url"] for r in rows}
    gone = [sh for sh in db.select("shows", "select=id,title,feed_url&catalog=eq.true") if sh["feed_url"] not in listed]
    for sh in gone:
        db.update("shows", f"id=eq.{sh['id']}", {"catalog": False})
        db.s.delete(f"{db.url}/rest/v1/subscriptions?show_id=eq.{sh['id']}", headers=db.h, timeout=60).raise_for_status()
        log.info("dropped from the catalog: %s", sh["title"])
    log.info("seeded %d catalog shows (%d dropped)", len(rows), len(gone))
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["refresh", "process", "prefetch", "sync", "resync", "intros", "seed"])
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
    elif a.cmd == "resync":                       # rebuild sync data (e.g. after the sync builder improved)
        db.update("episodes", "status=eq.ready&sync_path=not.is.null", {"sync_path": None})
        sync_pending(db, a.max)
    elif a.cmd == "intros":
        write_intros(db)
    else:
        seed(db, Path(a.arg or "tools/catalog/catalog.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
