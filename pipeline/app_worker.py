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
        if cfg["parser"] == "bbc_le":
            # the feed's audio goes through a tracking redirect that answers 403 to phones outside
            # the UK/US; the page links BBC's own ad-free download, which plays everywhere
            cfg["audio_from_page"] = True
    return cfg


def episode_row(show: dict, ep: Episode, path: str) -> dict:
    # where the publisher's transcript lives: the phone fetches it from there (we never store the text).
    # Web-page transcripts: the page's address is filled in by transcript_pages() (it may take a lookup).
    web = path in ("npr", "web")
    tr = None if web else ep.best_transcript
    return {"show_id": show["id"], "guid": ep.guid, "title": ep.title, "published_at": ep.published_iso,
            "duration_sec": ep.duration_sec, "audio_url": ep.audio_url, "episode_url": ep.link,
            "image_url": ep.image_url, "description": strip_html(ep.description_html, 1500),
            "has_transcript": bool(tr) or web,
            "transcript_url": (None if web else (tr.url if tr else None)),
            "transcript_kind": ("web" if web else (tr.kind if tr else None))}


def transcript_pages(db: "Supa", session, sh: dict, cfg: dict, kept: list, rows: list[dict]) -> None:
    """The real transcript page of each web-transcript episode (NPR: /transcripts/<id>; BBC: the dated feature
    page), looked up once and then kept."""
    from . import webtranscript as W
    known = {r["guid"]: r.get("transcript_url") for r in db.select("episodes", f"select=guid,transcript_url&show_id=eq.{sh['id']}")}
    for e, row in zip(kept, rows):
        url = known.get(e.guid)
        if not url or url == e.link and cfg.get("parser") in ("npr", "bbc_le"):
            try:
                url = W.resolve_page_url(session, cfg, e)
            except Exception as x:  # noqa: BLE001
                log.info("no transcript page for %s: %s", e.title, x); url = None
        row["transcript_url"] = url or e.link


def public_pack(doc: dict) -> dict:
    """What we keep on our server: the study notes and timing references — never the publisher's text.
    The app downloads the transcript from the publisher and rebuilds the same sentences/paragraphs
    (app/lib/transcript.ts, kept identical to pipeline/transcript.py by the parity check)."""
    tr = doc.get("transcript") or {}
    stats = tr.get("stats") or {}
    study = {k: v for k, v in (doc.get("study") or {}).items() if k not in ("translations_sent", "translations", "shadowing", "summary_en")}   # no verbatim passages
    keep = ("id", "show", "title", "published_at", "duration_sec", "episode_number", "audio_url", "audio_url_original",
            "audio_type", "audio_meta", "episode_url", "image_url", "built_at")
    src = tr.get("source") or ""
    kind = tr.get("kind") or _kind_of(src, tr.get("url") or "")
    extra = {}
    if kind == "web" and tr.get("cues"):
        # web pages carry no timestamps: keep each sentence's time + fingerprint; the phone reads the text from the page
        extra = {"parser": tr.get("parser"), "timing": [[c["s"], c["e"], fp(c["t"])] for c in tr["cues"]]}
    return {**{k: doc.get(k) for k in keep},
            "transcript": {"source": src, "version": tr.get("version"), "url": tr.get("url"), **extra,
                           "kind": kind,
                           "n_cues": stats.get("cues") or len(tr.get("cues") or []), "n_segments": stats.get("segments"),
                           # paragraph id → speaker name the study pass worked out ("Tracy Alloway (host)")
                           "speakers": {g["id"]: g.get("display_speaker") or "" for g in tr.get("segments") or [] if g.get("id")}},
            "study": study, "text_free": True}


def fp(text: str) -> str:
    """Short fingerprint of a sentence (FNV-1a over its lowercase letters/digits) — same as app/lib/webTranscript.ts."""
    import re as _re
    h = 0x811C9DC5
    for ch in _re.sub(r"[^a-z0-9]", "", text.lower()):
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def page_sentences(html: str, parser: str) -> list[dict]:
    from .webtranscript import parse_paragraphs
    from .align import split_sentences
    return [{"t": s, "spk": p.get("speaker") or None} for p in parse_paragraphs(html, parser) for s in split_sentences(p["text"])]


def _kind_of(source: str, url: str) -> str:
    """Older packs only recorded "rss:<mime type>": work the parser kind out the way feeds.TranscriptRef does."""
    from .feeds import TranscriptRef
    if not source.startswith("rss:"):
        return "web"
    return TranscriptRef(url=url, type=source.split(":", 1)[1]).kind


def transcript_cues(session, doc: dict) -> list[dict]:
    """Re-read the publisher's transcript (for the audio sync of a text-free pack)."""
    from .transcript import parse_transcript, sentence_cues, cues_to_dicts
    tr = doc.get("transcript") or {}
    if tr.get("cues"):
        return tr["cues"]
    if tr.get("kind") == "web" and tr.get("timing") and tr.get("url"):
        from .webtranscript import fetch_page
        sents = page_sentences(fetch_page(session, tr["url"]), tr.get("parser") or "generic")
        timing = tr["timing"]
        if len(sents) != len(timing) or any(fp(x["t"]) != t[2] for x, t in zip(sents, timing)):
            raise RuntimeError("the transcript page changed since the pack was made")
        return [{"i": i, "s": t[0], "e": t[1], "t": x["t"], **({"spk": x["spk"]} if x["spk"] else {})} for i, (x, t) in enumerate(zip(sents, timing))]
    if not tr.get("url") or tr.get("kind") == "web":
        raise RuntimeError("no publisher transcript file for this episode")
    return cues_to_dicts(sentence_cues(parse_transcript(http_get_text(session, tr["url"]), tr.get("kind") or "unknown")))


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


def page_audio(db: Supa, session, sh: dict, cfg: dict, kept: list, rows: list[dict]) -> None:
    """Shows whose feed audio doesn't play on phones abroad (BBC's tracking redirect): store the episode
    page's own download instead, so plain listening works too. Found once per episode, then kept."""
    from . import webtranscript as W
    known = {r["guid"]: r.get("audio_url") for r in db.select("episodes", f"select=guid,audio_url&show_id=eq.{sh['id']}")}
    for e, row in zip(kept, rows):
        had = known.get(e.guid)
        if had and had != e.audio_url:
            row["audio_url"] = had; continue
        try:
            page = W.resolve_page_url(session, cfg, e)
            link = W.find_audio_link(W.fetch_page(session, page), page)
            if link:
                row["audio_url"] = link
        except Exception as x:  # noqa: BLE001
            log.info("no page audio yet for %s: %s", e.title, x)


def backfill_ipa(db: Supa, max_n: int = 200) -> int:
    """Packs made before vocab carried IPA: add it (one cheap call per pack)."""
    gen, n = StudyGenerator(), 0
    for row in db.select("episodes", f"select=id,title,pack_path&status=eq.ready&pack_path=not.is.null&order=ready_at.desc&limit={max_n}"):
        try:
            r = db.s.get(f"{db.url}/storage/v1/object/episodes/{row['pack_path']}", headers=db.h, timeout=120)
            r.raise_for_status()
            pack = r.json()
            vocab = (pack.get("study") or {}).get("vocab") or []
            need = [v["word"] for v in vocab if v.get("word") and not v.get("ipa")]
            if not need:
                continue
            got = gen.ipa(need)
            for v in vocab:
                if not v.get("ipa") and got.get(v.get("word")):
                    v["ipa"] = got[v["word"]]
            db.put_object("episodes", row["pack_path"], json.dumps(pack, ensure_ascii=False).encode())
            n += 1
        except Exception as e:  # noqa: BLE001
            log.error("ipa failed for %s: %s", row["title"], e)
    log.info("ipa: updated %d packs", n)
    return n


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
            transcript_pages(db, session, sh, cfg, kept, rows)
        if cfg.get("audio_from_page"):
            page_audio(db, session, sh, cfg, kept, rows)
        # don't overwrite worker-owned columns (status, pack paths) on existing rows: upsert only listing fields
        db.upsert("episodes", rows, "show_id,guid")
        db.update("shows", f"id=eq.{sh['id']}", {"refreshed_at": utcnow_iso()})
        n += len(rows)
        log.info("refresh %s: %d episodes", sh["title"], len(rows))
    return n


SYNC_WAIT_SEC = 150    # after the pack is done, wait this long for its sync before opening it unsynced
MAX_STUDY_SEC = 3600   # study packs only for episodes up to 60 min (same limit in request_episode)


def prefetch(db: Supa, per_show: int = 1) -> int:
    """Mark the newest unbuilt episode(s) of every show someone follows, so it is ready before anyone opens it."""
    followed = {r["show_id"] for r in db.select("subscriptions", "select=show_id")}
    n = 0
    for sid in followed:
        eps = db.select("episodes", f"select=id,status,published_at&show_id=eq.{sid}&has_transcript=eq.true"
                                     f"&or=(duration_sec.is.null,duration_sec.lte.{MAX_STUDY_SEC})"   # longer ones: listen only
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
    # the audio sync runs beside the study pack (one at a time), so the episode opens already synced
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
    sync_pool, sync_asr = ThreadPoolExecutor(max_workers=1), {}

    def do_sync(eid: str, partial: dict) -> str:
        from . import sync as SY
        if "asr" not in sync_asr and not (partial.get("audio_meta") or {}).get("fixed"):
            sync_asr["asr"] = SY.Asr()
        built = SY.build(partial, sync_asr.get("asr"), http_session())
        db.put_object("episodes", f"{eid}.sync.json", json.dumps(built, separators=(",", ":")).encode())
        return f"{eid}.sync.json"

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
            fut: dict = {}
            doc = process_episode(session, gen, cfg, ep, translate=False,
                                  on_sync_ready=lambda partial, eid=row["id"]: fut.setdefault("f", sync_pool.submit(do_sync, eid, partial)))
            doc["id"] = row["id"]
            doc["show"].update(slug=str(sh["id"]), name=sh["title"], image=sh.get("image_url"))
            db.put_object("episodes", f"{row['id']}.json", json.dumps(public_pack(doc), ensure_ascii=False, separators=(",", ":")).encode())
            # open it synced from the start: wait (a little) for the sync that ran beside the pack;
            # if it's slower, mark ready anyway and add sync_path when it lands (the app switches over then)
            sync_path = None
            if "f" in fut:
                try:
                    sync_path = fut["f"].result(timeout=SYNC_WAIT_SEC)
                except FutTimeout:
                    log.info("  sync still running — ready without it for now")
                    fut["f"].add_done_callback(lambda f, eid=row["id"]: f.exception() is None and
                                               db.update("episodes", f"id=eq.{eid}", {"sync_path": f.result()}))
                except Exception as x:  # noqa: BLE001
                    log.error("  sync failed (the later sync step retries): %s", x)
            db.update("episodes", f"id=eq.{row['id']}", {
                "status": "ready", "pack_path": f"{row['id']}.json", "error": None,
                "one_liner_ko": (doc.get("study") or {}).get("one_liner_ko"), "ready_at": utcnow_iso(),
                "duration_sec": doc.get("duration_sec"), **({"sync_path": sync_path} if sync_path else {})})
            log.info("  ✓ ready (pack)")
            from . import push
            push.study_ready(db, row["id"], row["title"])
            done += 1
        except Exception as e:  # noqa: BLE001
            from .webtranscript import TranscriptNotReady
            # transcript not published yet (NPR posts some a day later): back to the low-priority hourly job.
            # Never straight back to 'queued' — that fires the database's dispatch trigger again at once (a loop).
            new = "prefetch" if isinstance(e, TranscriptNotReady) else "failed"
            db.update("episodes", f"id=eq.{row['id']}", {"status": new, "error": str(e)[:300],
                                                       "attempts": (row.get("attempts") or 0) + (0 if new == "prefetch" else 1)})
            log.error("  ✗ %s", e)
    sync_pool.shutdown(wait=True)
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
            doc = {**doc, "transcript": {**(doc.get("transcript") or {}), "cues": transcript_cues(session, doc)}}   # in memory only
            sync = SY.build(doc, asr, session)
            db.put_object("episodes", f"{row['id']}.sync.json", json.dumps(sync, separators=(",", ":")).encode())
            db.update("episodes", f"id=eq.{row['id']}", {"sync_path": f"{row['id']}.sync.json"})
            n += 1
            log.info("synced %s", row["title"])
        except Exception as e:  # noqa: BLE001
            log.error("sync failed for %s: %s", row["title"], e)
    return n


def strip_packs(db: Supa) -> int:
    """One-off: rewrite every stored pack without the publisher's text (and without full translations)."""
    n = 0
    for row in db.select("episodes", "select=id,title,pack_path&pack_path=not.is.null&limit=5000"):
        try:
            r = db.s.get(f"{db.url}/storage/v1/object/episodes/{row['pack_path']}", headers=db.h, timeout=120)
            r.raise_for_status()
            doc = r.json()
            if doc.get("text_free"):
                continue
            db.put_object("episodes", row["pack_path"], json.dumps(public_pack(doc), ensure_ascii=False, separators=(",", ":")).encode())
            n += 1
        except Exception as e:  # noqa: BLE001
            log.error("strip failed for %s: %s", row["title"], e)
    log.info("strip: rewrote %d packs", n)
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
    ap.add_argument("cmd", choices=["refresh", "process", "prefetch", "sync", "resync", "intros", "ipa", "notify", "seed", "strip"])
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
    elif a.cmd == "ipa":
        backfill_ipa(db)
    elif a.cmd == "strip":
        strip_packs(db)
    elif a.cmd == "notify":                       # push: new episodes of followed shows
        from . import push
        push.new_episodes(db)
    else:
        seed(db, Path(a.arg or "tools/catalog/catalog.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
