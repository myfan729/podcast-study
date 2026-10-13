"""Orchestrator: feeds → new episodes → transcript → study pack → docs/data JSON.

Usage:
  python -m pipeline                 # normal run (needs ANTHROPIC_API_KEY)
  python -m pipeline --mock          # no API calls; placeholder study content
  python -m pipeline --backfill 5    # process the newest 5 eligible episodes per show
  python -m pipeline --show big-take --force "<guid or title fragment>"
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import build
from .feeds import Episode, iter_eligible, parse_feed, strip_html
from .llm import StudyGenerator
from .transcript import (TRANSCRIPT_VERSION, cues_to_dicts, group_sentences, parse_transcript, segment_cues,
                         segments_to_dicts, sentence_cues, transcript_stats)
from .util import http_get_text, http_session, log, read_json, resolve_final_url, setup_logging, slugify, utcnow_iso, write_json

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state" / "seen.json"
CONFIG_PATH = ROOT / "config" / "shows.yaml"

# Testing hooks: when set, used instead of downloading the transcript / calling the API.
_overrides: dict = {"transcript_text": None, "study": None, "audio_url": None, "resolve": True, "audio_meta": None}


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    defaults = cfg.get("defaults", {})
    for show in cfg["shows"]:
        for k, v in defaults.items():
            show.setdefault(k, v)
    return cfg


def episode_key(show_slug: str, ep: Episode) -> str:
    return f"{show_slug}:{hashlib.sha1(ep.guid.encode('utf-8')).hexdigest()[:12]}"


UPGRADE_DAYS = 3        # recent episodes made with an older transcript format are rebuilt (study pack included)
UPGRADE_MAX = 3         # …at most this many per run


def needs_upgrade(rec: dict, now: datetime) -> bool:
    """A finished RSS-transcript episode from the last few days whose cues are still caption lines."""
    if not rec.get("id"):
        return False
    doc = read_json(build.episode_path(rec["id"]), None)
    if not doc or doc.get("demo"):
        return False
    tr = doc.get("transcript") or {}
    src = str(tr.get("source") or "")
    if int(tr.get("version") or 1) >= TRANSCRIPT_VERSION or not src.startswith("rss:") or src == "rss:web":
        return False
    published = datetime.fromisoformat(doc["published_at"].replace("Z", "+00:00"))
    return now - published <= timedelta(days=UPGRADE_DAYS)


def episode_id(show_slug: str, ep: Episode) -> str:
    base = f"{show_slug}-{ep.published_at.strftime('%Y-%m-%d')}-{slugify(ep.title, 60)}"
    tok = build.id_token(episode_key(show_slug, ep))
    return f"{base}-{tok}" if tok else base


def migrate_ids(seen: dict) -> int:
    """Once a site password exists, episode ids gain an unguessable token; rename files already built."""
    n = 0
    for key, rec in seen.items():
        old = rec.get("id")
        if rec.get("status") != "done" or not old:
            continue
        tok = build.id_token(key)
        if not tok or old.endswith("-" + tok):
            continue
        new = f"{old}-{tok}"
        src = build.episode_path(old)
        if not src.exists():
            continue
        doc = read_json(src, None) or {}
        doc["id"] = new
        write_json(build.episode_path(new), doc, compact=True)
        src.unlink()
        sync_old = build.DATA / "sync" / f"{old}.json"
        if sync_old.exists():
            sync_old.rename(build.DATA / "sync" / f"{new}.json")
        rec["id"] = new
        n += 1
        log.info("  id → %s", new)
    return n


OMNY_CLIP_RE = re.compile(r"https://api\.omny\.fm/orgs/([0-9a-f-]+)/clips/([0-9a-f-]+)/transcript", re.I)
HMS_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})(?:\.(\d+))?$")


def _hms(raw: str) -> float | None:
    m = HMS_RE.match((raw or "").strip())
    if not m:
        return None
    h, mi, sec, frac = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(sec) + (float("0." + frac) if frac else 0.0)


def fetch_audio_meta(session, transcript_url: str) -> dict:
    """Where the audio comes from, whether ads are inserted dynamically, and where the ad breaks sit
    (in content time). Omny exposes this through its clip API; other hosts are 'unknown'."""
    meta: dict = {"dai": "unknown", "content_duration": None, "ad_markers": []}
    if _overrides.get("audio_meta"):
        return dict(_overrides["audio_meta"])
    m = OMNY_CLIP_RE.match(transcript_url or "")
    if not m:
        if "transistor.fm" in (transcript_url or ""):
            meta["dai"] = "likely"      # Transistor serves audio through dai.transistor.fm
        return meta
    org, clip = m.groups()
    try:
        r = session.get(f"https://api.omny.fm/orgs/{org}/clips/{clip}", timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("  omny clip meta failed: %s", e)
        meta.update(dai="yes", error=str(e)[:200])   # Omny always inserts ads; markers unknown this time
        return meta
    meta["dai"] = "yes"
    meta["content_duration"] = data.get("DurationSeconds")
    markers = []
    for mk in data.get("AdMarkers") or []:
        sec = _hms(str(mk.get("Offset", "")))
        kind = str(mk.get("AdMarkerType", "")).lower()
        kind = "pre" if "pre" in kind else "post" if "post" in kind else "mid"
        if sec is not None:
            markers.append({"type": kind, "sec": round(sec, 3)})
    meta["ad_markers"] = markers
    meta["source"] = "omny"
    return meta


_asr = None


def get_asr():
    """Speech recognition (faster-whisper), loaded once per run and only when a show needs it."""
    global _asr
    if _asr is None:
        from .sync import Asr
        _asr = Asr()
    return _asr


def web_transcript_cues(session, show: dict, ep: Episode) -> tuple[list, dict, str]:
    """Shows whose transcript is a web page without timestamps: fetch the text, download the
    audio once, recognise it, and align the two → timed cues on an ad-free content timeline."""
    import tempfile
    from . import align as A, fingerprint as F, webtranscript as W
    from .sync import download

    audio_url = ep.audio_url
    if _overrides.get("web_paragraphs"):
        page_url, paras = ep.link, _overrides["web_paragraphs"]
    else:
        page_url = W.resolve_page_url(session, show, ep)
        html = W.fetch_page(session, page_url)
        paras = W.parse_paragraphs(html, show.get("parser", "generic"))
        if show.get("audio_from_page"):
            link = W.find_audio_link(html, page_url)
            if link:
                audio_url = link          # e.g. BBC's ad-free programme file (https, CORS-enabled)
                log.info("  audio from page: %s", link)
    if _overrides.get("web_words"):
        words, dur = _overrides["web_words"], _overrides.get("web_duration", 0.0)
    else:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "audio.mp3"
            download(session, audio_url, p)
            pcm16 = F.decode_pcm(p, 16000)
        dur = len(pcm16) / 16000
        words = get_asr().words(pcm16, 0.0, dur)
    ad_free = bool(show.get("ad_free"))
    cues, info = A.align_paragraphs(paras, words, dur, ad_free=ad_free)
    log.info("  aligned %d cues (coverage %.0f%%, repaired %d, first word %.1fs, pre-roll %.1fs, gaps %s)", len(cues),
             info["coverage"] * 100, info["repaired_blocks"], info["first_word_runner"], info["preroll_runner"], info["ad_gaps_runner"])
    meta = {"dai": "none" if ad_free else ("detected" if (info["preroll_runner"] > 3 or info["ad_gaps_runner"]) else "none"),
            "content_duration": info["content_duration"], "ad_markers": info["markers"], "source": "asr-align",
            # fixed: the file is identical for every listener and cue times are on its clock → no sync needed
            "fixed": ad_free,
            "alignment": {k: info[k] for k in ("version", "ad_free", "coverage", "repaired_blocks", "preroll_runner",
                                                "first_word_runner", "last_word_runner", "ad_gaps_runner", "runner_duration")},
            "audio_url": audio_url}
    return cues, meta, page_url


def retime_episode(session, show: dict, path: Path, doc: dict) -> bool:
    """Re-run the ASR alignment of a web-transcript episode and update cue/segment times in place,
    keeping the study pack and paragraphing. Returns True if the file was updated."""
    from .feeds import Episode
    tr = doc.get("transcript") or {}
    old_cues = tr.get("cues") or []
    ep = Episode(guid=doc["id"], title=doc["title"], link=tr.get("url") or doc.get("episode_url") or "",
                 published_at=datetime.fromisoformat(doc["published_at"].replace("Z", "+00:00")),
                 duration_sec=doc.get("duration_sec"), audio_url=doc.get("audio_url"), audio_type=doc.get("audio_type"),
                 description_html=doc.get("description_html", ""), image_url=doc.get("image_url"), episode_number=doc.get("episode_number"),
                 transcripts=[])
    cues, web_meta, _page = web_transcript_cues(session, show, ep)
    if len(cues) != len(old_cues) or any(c.t != o["t"] for c, o in zip(cues, old_cues)):
        log.warning("  retime: transcript text changed (%d → %d cues); leaving %s for a full re-run", len(old_cues), len(cues), doc["id"])
        return False
    for c, o in zip(cues, old_cues):
        o["s"], o["e"] = round(c.s, 3), round(c.e, 3)
    for sg in tr.get("segments") or []:
        sg["start"] = old_cues[sg["cue_from"]]["s"]
        sg["end"] = old_cues[sg["cue_to"]]["e"]
    tr["stats"] = dict(tr.get("stats") or {}, end_sec=round(old_cues[-1]["e"], 3))
    doc["audio_meta"] = web_meta
    if web_meta.get("content_duration"):
        doc["duration_sec"] = int(round(web_meta["content_duration"]))
    if web_meta.get("audio_url"):
        doc["audio_url"] = doc["audio_url_original"] = web_meta["audio_url"]
    doc["retimed_at"] = utcnow_iso()
    write_json(path, doc, compact=True)
    sync_path = build.DATA / "sync" / path.name
    if sync_path.exists():
        sync_path.unlink()                 # rebuilt by pipeline.sync on this run
    return True


def backfill_cue_translations(gen: StudyGenerator, max_n: int = 3, max_age_days: int = 7) -> int:
    """Older episodes only have paragraph translations; add sentence-level ones for recent ones only."""
    if gen.mock:
        return 0
    n = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    for p in sorted(build.EPISODES_DIR.glob("*.json"), reverse=True):
        if n >= max_n:
            break
        doc = read_json(p, None)
        if not doc or doc.get("demo"):
            continue
        if datetime.fromisoformat(doc["published_at"].replace("Z", "+00:00")) < cutoff:
            continue
        study = doc.get("study") or {}
        if study.get("mock") or study.get("translations_sent") is not None:
            continue
        tr = doc.get("transcript") or {}
        cues = tr.get("cues") or []
        if not cues:
            continue
        sentences = tr.get("sentences") or group_sentences(cues, tr.get("segments"))
        tr["sentences"] = sentences
        log.info("▶ sentence translations for %s (%d sentences)", doc["id"], len(sentences))
        study["translations_sent"] = gen.translate_sentences(cues, sentences)
        study.pop("translations_cues", None)
        doc["study"] = study
        write_json(p, doc, compact=True)
        n += 1
    return n


def retime_stale(session, shows: list[dict], max_n: int = 4, only: str | None = None) -> int:
    """Web-transcript episodes aligned by an older algorithm version are re-timed (study pack kept)."""
    from .align import ALIGN_VERSION
    by_slug = {s["slug"]: s for s in shows}
    n = 0
    for p in sorted(build.EPISODES_DIR.glob("*.json"), reverse=True):
        if n >= max_n:
            break
        doc = read_json(p, None)
        if not doc or doc.get("demo"):
            continue
        show = by_slug.get((doc.get("show") or {}).get("slug"))
        if not show or show.get("transcript") != "web":
            continue
        am = doc.get("audio_meta") or {}
        ver = int((am.get("alignment") or {}).get("version") or 1)
        stale = ver < ALIGN_VERSION or bool(show.get("ad_free")) != bool(am.get("fixed"))
        if only:
            stale = only in doc["id"] or only.lower() in doc["title"].lower()
        if not stale:
            continue
        log.info("▶ retime %s (alignment v%d → v%d)", doc["id"], ver, ALIGN_VERSION)
        try:
            if retime_episode(session, show, p, doc):
                n += 1
                log.info("  ✓ re-timed %s", doc["id"])
        except Exception as e:  # noqa: BLE001
            log.error("  ✗ retime failed: %s", e)
    return n


def process_episode(session, gen: StudyGenerator, show: dict, ep: Episode, translate: bool) -> dict:
    tref = ep.best_transcript
    web_meta = None
    if tref is None and show.get("transcript") == "web":
        cues, web_meta, page_url = web_transcript_cues(session, show, ep)
        class _Ref:  # stands in for a feed transcript reference
            url, type, kind = page_url, "web", "web"
        tref = _Ref()
    else:
        assert tref is not None
        log.info("  transcript: %s (%s)", tref.kind, tref.url)
        raw = _overrides["transcript_text"] or http_get_text(session, tref.url)
        cues = sentence_cues(parse_transcript(raw, tref.kind))      # caption lines → whole sentences
    if len(cues) < 10:
        raise RuntimeError(f"transcript parsed into only {len(cues)} cues — format not understood?")
    segments = segment_cues(cues)
    sentences = group_sentences(cues, segments)
    stats = transcript_stats(cues, segments)
    log.info("  %d cues → %d segments, %d words, speakers=%s", stats["cues"], stats["segments"], stats["words"], stats["speakers"])

    speaker_mode = show.get("speaker_labels", "auto")
    if speaker_mode == "auto":
        speaker_mode = "none" if not stats["has_speakers"] else (
            "generic" if all(s.lower().startswith("speaker") for s in stats["speakers"]) else "named")

    audio_meta = web_meta or fetch_audio_meta(session, tref.url)
    if audio_meta.get("ad_markers"):
        log.info("  ad markers: %s", ", ".join(f"{a['type']}@{a['sec']:.0f}s" for a in audio_meta["ad_markers"]))

    if web_meta and web_meta.get("audio_url") and web_meta["audio_url"] != ep.audio_url:
        ep.audio_url = web_meta["audio_url"]      # the page's own (ad-free, CORS-enabled) file
    if _overrides["audio_url"]:
        audio_final = _overrides["audio_url"]
    elif ep.audio_url and _overrides["resolve"]:
        audio_final = resolve_final_url(session, ep.audio_url)
    else:
        audio_final = ep.audio_url
    meta = {
        "title": ep.title,
        "published_at": ep.published_iso,
        "duration_sec": ep.duration_sec or int(stats["end_sec"]),
        "description_text": strip_html(ep.description_html, 2000),
    }
    if audio_meta.get("content_duration"):
        meta["duration_sec"] = int(round(audio_meta["content_duration"]))
    if _overrides["study"]:
        from .llm import postprocess_study_pack
        study = postprocess_study_pack(dict(_overrides["study"]), segments)
        study.setdefault("mock", False)
        study.setdefault("model", "fixture")
    else:
        study = gen.generate_study_pack(meta, show, segments, speaker_mode)
        study["mock"] = gen.mock
        study["model"] = gen.model
        if translate:
            study["translations_sent"] = gen.translate_sentences(cues, sentences)      # sentence by sentence
    study["generated_at"] = utcnow_iso()

    # Apply speaker names to segments for display.
    name_by_label = {s["label"]: s["name"] for s in study.get("speakers", []) if s.get("label")}
    role_by_label = {s["label"]: s.get("role", "") for s in study.get("speakers", [])}
    assign = {a["segment_id"]: a["speaker"] for a in study.get("speaker_assignments", [])}
    seg_dicts = segments_to_dicts(segments)
    for d in seg_dicts:
        if d["id"] in assign:
            d["display_speaker"] = assign[d["id"]]
        elif d["speaker"] in name_by_label:
            role = role_by_label.get(d["speaker"], "")
            nm = name_by_label[d["speaker"]]
            d["display_speaker"] = f"{nm} ({role})" if role and role not in nm.lower() and role not in ("other",) else nm
        else:
            d["display_speaker"] = d["speaker"] or ""

    return {
        "id": episode_id(show["slug"], ep),
        "show": {"slug": show["slug"], "name": show["name"], "publisher": show.get("publisher", ""),
                 "color": show.get("color", "#555"), "homepage": show.get("homepage", "")},
        "title": ep.title,
        "published_at": ep.published_iso,
        "duration_sec": meta["duration_sec"],
        "episode_number": ep.episode_number,
        "audio_url": audio_final or ep.audio_url,
        "audio_url_original": ep.audio_url,
        "demo": bool(_overrides["study"]),
        "audio_type": ep.audio_type or "audio/mpeg",
        "audio_meta": audio_meta,
        "episode_url": ep.link,
        "image_url": ep.image_url,
        "description_html": ep.description_html,
        "transcript": {
            "source": f"rss:{tref.type or tref.kind}",
            "version": TRANSCRIPT_VERSION,
            "url": tref.url,
            "stats": stats,
            "cues": cues_to_dicts(cues),
            "sentences": sentences,
            "segments": seg_dicts,
        },
        "study": study,
        "built_at": utcnow_iso(),
    }


def refresh_missing_audio_meta(session) -> None:
    """Older episode files predate audio_meta; fill it in so the player knows about ad breaks."""
    for p in sorted(build.EPISODES_DIR.glob("*.json")):
        doc = read_json(p, None)
        if not doc or doc.get("audio_meta") or doc.get("demo"):
            continue
        turl = (doc.get("transcript") or {}).get("url", "")
        am = fetch_audio_meta(session, turl)
        if am.get("error"):
            continue  # try again next run
        doc["audio_meta"] = am
        if am.get("content_duration"):
            doc["duration_sec"] = int(round(am["content_duration"]))
        write_json(p, doc, compact=True)
        log.info("  audio_meta added: %s (%s, %d markers)", doc["id"], am.get("dai"), len(am.get("ad_markers", [])))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--max-new", type=int, default=6, help="max episodes to process in one run (all shows)")
    ap.add_argument("--backfill", type=int, default=None, help="override per-show backfill count for shows with no history")
    ap.add_argument("--show", action="append", help="only these show slugs (repeatable)")
    ap.add_argument("--force", help="re-process the episode whose guid or title contains this text")
    ap.add_argument("--mock", action="store_true", help="skip the Claude API; write placeholder study content")
    ap.add_argument("--no-translate", action="store_true", help="skip Korean segment translations")
    ap.add_argument("--feed-file", action="append", default=[],
                    help="slug=path : read this show's feed from a local file (testing)")
    ap.add_argument("--transcript-file", help="path : read the transcript from a local file instead of the URL (testing)")
    ap.add_argument("--study-file", help="path : use this study-pack JSON instead of calling the API (testing/demo)")
    ap.add_argument("--audio-url", help="override the episode audio URL (testing/demo)")
    ap.add_argument("--ad-markers", help="comma-separated mid-roll positions in content seconds (testing/demo)")
    ap.add_argument("--no-resolve", action="store_true", help="don't follow enclosure redirects (offline testing)")
    ap.add_argument("--retime", help="re-align the web-transcript episode whose id or title contains this text (study pack kept)")
    ap.add_argument("--no-retime", action="store_true", help="skip the automatic re-timing of episodes aligned by an older version")
    ap.add_argument("--no-upgrade", action="store_true", help="skip rebuilding recent episodes made with an older transcript format")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)

    cfg = load_config(Path(args.config))
    shows = [s for s in cfg["shows"] if (s["slug"] in args.show if args.show else s.get("enabled", True))]
    daily_limit = int(cfg.get("daily_limit") or 0)
    kst = timezone(timedelta(hours=9))
    today_kst = datetime.now(kst).strftime("%Y-%m-%d")
    state = read_json(STATE_PATH, {"episodes": {}})
    seen: dict = state.setdefault("episodes", {})
    session = http_session()
    feed_files = dict(kv.split("=", 1) for kv in args.feed_file)

    if args.transcript_file:
        _overrides["transcript_text"] = Path(args.transcript_file).read_text(encoding="utf-8")
    if args.study_file:
        _overrides["study"] = read_json(Path(args.study_file), None)
    if args.audio_url:
        _overrides["audio_url"] = args.audio_url
    if args.ad_markers:
        _overrides["audio_meta"] = {"dai": "yes", "content_duration": None, "source": "fixture",
                                    "ad_markers": [{"type": "mid", "sec": float(x)} for x in args.ad_markers.split(",") if x]}
    if args.no_resolve:
        _overrides["resolve"] = False

    gen = StudyGenerator(mock=args.mock)
    upgrades: set[str] = set()
    now = datetime.now(timezone.utc)
    processed = 0
    failures = 0
    stop_all = False

    for show in shows:
        slug = show["slug"]
        log.info("== %s", show["name"])
        try:
            xml_text = Path(feed_files[slug]).read_text(encoding="utf-8") if slug in feed_files else http_get_text(session, show["feed"])
            _, episodes = parse_feed(xml_text)
        except Exception as e:  # noqa: BLE001
            log.error("feed failed for %s: %s", slug, e)
            failures += 1
            continue

        has_history = any(k.startswith(slug + ":") and v.get("status") == "done" for k, v in seen.items())
        backfill = args.backfill if args.backfill is not None else int(show.get("backfill", 3))
        max_minutes = show.get("max_minutes")
        retry_days = int(show.get("transcript_retry_days", 4))
        max_age = timedelta(days=int(show.get("max_age_days", 14)))

        candidates: list[Episode] = []
        for ep in episodes:
            key = episode_key(slug, ep)
            rec = seen.get(key)
            forced = bool(args.force) and (args.force in ep.guid or args.force.lower() in ep.title.lower())
            if forced:
                candidates.append(ep)
                continue
            if (rec and rec.get("status") == "done" and len(upgrades) < UPGRADE_MAX and not args.no_upgrade
                    and needs_upgrade(rec, now)):
                upgrades.add(key)
                candidates.append(ep)
                log.info("  upgrade to sentence transcript: %s", ep.title)
                continue
            if rec and rec.get("status") in ("done", "skipped_long", "skipped_daily", "no_transcript", "gave_up"):
                continue
            if rec and rec.get("status") == "failed" and rec.get("attempts", 0) >= 3:
                rec["status"] = "gave_up"
                log.warning("  giving up after %d attempts: %s", rec["attempts"], ep.title)
                continue
            if now - ep.published_at > max_age:
                continue  # archive item; only new episodes (and explicit --force/--backfill) are processed
            if max_minutes and ep.duration_sec and ep.duration_sec > max_minutes * 60:
                seen[key] = {"status": "skipped_long", "title": ep.title, "published_at": ep.published_iso,
                             "duration_sec": ep.duration_sec, "seen_at": utcnow_iso()}
                log.info("  skip (%.0f min > %d): %s", ep.duration_sec / 60, max_minutes, ep.title)
                continue
            candidates.append(ep)

        if not has_history and not args.force:
            candidates = candidates[:backfill]
            log.info("  first run: backfilling up to %d episodes", backfill)

        candidates.sort(key=lambda e: e.published_at, reverse=True)
        for ep in candidates:
            if daily_limit and not args.force and episode_key(slug, ep) not in upgrades:
                done_today = sum(1 for v in seen.values() if v.get("status") == "done"
                                 and datetime.fromisoformat(v.get("done_at", "1970-01-01T00:00:00Z").replace("Z", "+00:00")).astimezone(kst).strftime("%Y-%m-%d") == today_kst)
                if done_today >= daily_limit:
                    key = episode_key(slug, ep)
                    if key not in seen or seen[key].get("status") not in ("done",):
                        seen[key] = {"status": "skipped_daily", "title": ep.title, "published_at": ep.published_iso, "seen_at": utcnow_iso()}
                        log.info("  skip (daily limit %d reached): %s", daily_limit, ep.title)
                    continue
            if processed >= args.max_new:
                log.info("  reached --max-new=%d; remaining episodes wait for the next run", args.max_new)
                break
            key = episode_key(slug, ep)
            rec = seen.get(key, {"first_seen": utcnow_iso(), "attempts": 0})
            if not ep.best_transcript and show.get("transcript") != "web":
                age = now - ep.published_at
                status = "pending_transcript" if age < timedelta(days=retry_days) else "no_transcript"
                rec.update({"status": status, "title": ep.title, "published_at": ep.published_iso, "seen_at": utcnow_iso()})
                seen[key] = rec
                log.info("  %s: %s", status, ep.title)
                continue
            log.info("▶ %s (%s, %s)", ep.title, ep.published_iso[:10], f"{(ep.duration_sec or 0) // 60} min")
            try:
                doc = process_episode(session, gen, show, ep, translate=not args.no_translate)
                build.write_episode(doc)
                if key in upgrades:      # a rebuild: keep done_at so it does not count toward today's limit
                    rec.update({"status": "done", "id": doc["id"], "upgraded_at": utcnow_iso()})
                else:
                    rec.update({"status": "done", "id": doc["id"], "title": ep.title, "published_at": ep.published_iso,
                                "done_at": utcnow_iso(), "attempts": rec.get("attempts", 0) + 1})
                processed += 1
                log.info("  ✓ wrote docs/data/episodes/%s.json", doc["id"])
            except Exception as e:  # noqa: BLE001
                failures += 1
                msg = str(e)
                auth_problem = ("API error 401" in msg or "ANTHROPIC_API_KEY is not set" in msg
                                or "credit balance" in msg.lower())
                rec.update({"status": "failed", "title": ep.title, "published_at": ep.published_iso,
                            "error": msg[:300], "seen_at": utcnow_iso(),
                            # an invalid/missing API key is not the episode's fault: don't burn its retry budget
                            "attempts": rec.get("attempts", 0) + (0 if auth_problem else 1)})
                log.error("  ✗ failed: %s", e)
                if args.verbose:
                    traceback.print_exc()
                if auth_problem:
                    seen[key] = rec
                    write_json(STATE_PATH, state)
                    log.error("API key/billing problem — stopping this run. Fix the ANTHROPIC_API_KEY secret "
                              "or top up credits in the Claude Console, then re-run; nothing was lost.")
                    stop_all = True
                    break
            seen[key] = rec
            write_json(STATE_PATH, state)  # checkpoint after every episode
        if stop_all:
            break

    refresh_missing_audio_meta(session)
    if not stop_all and not args.no_translate:
        try:
            backfill_cue_translations(gen)
        except Exception as e:  # noqa: BLE001
            log.error("sentence-translation backfill failed: %s", e)
    if migrate_ids(seen):
        write_json(STATE_PATH, state)
    retimed = 0
    if args.retime or not (args.no_retime or stop_all):
        retimed = retime_stale(session, cfg["shows"], max_n=4 if not args.retime else 50, only=args.retime)
    write_json(STATE_PATH, state)
    index = build.rebuild_index(cfg["shows"])
    log.info("index: %d episodes, processed %d new, re-timed %d, %d failures", len(index["episodes"]), processed, retimed, failures)
    return 0 if failures == 0 or processed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
