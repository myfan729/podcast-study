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
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import build
from .feeds import Episode, iter_eligible, parse_feed, strip_html
from .llm import StudyGenerator
from .transcript import cues_to_dicts, parse_transcript, segment_cues, segments_to_dicts, transcript_stats
from .util import http_get_text, http_session, log, read_json, resolve_final_url, setup_logging, slugify, utcnow_iso, write_json

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state" / "seen.json"
CONFIG_PATH = ROOT / "config" / "shows.yaml"

# Testing hooks: when set, used instead of downloading the transcript / calling the API.
_overrides: dict = {"transcript_text": None, "study": None, "audio_url": None, "resolve": True}


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


def episode_id(show_slug: str, ep: Episode) -> str:
    return f"{show_slug}-{ep.published_at.strftime('%Y-%m-%d')}-{slugify(ep.title, 60)}"


def process_episode(session, gen: StudyGenerator, show: dict, ep: Episode, translate: bool) -> dict:
    tref = ep.best_transcript
    assert tref is not None
    log.info("  transcript: %s (%s)", tref.kind, tref.url)
    raw = _overrides["transcript_text"] or http_get_text(session, tref.url)
    cues = parse_transcript(raw, tref.kind)
    if len(cues) < 10:
        raise RuntimeError(f"transcript parsed into only {len(cues)} cues — format not understood?")
    segments = segment_cues(cues)
    stats = transcript_stats(cues, segments)
    log.info("  %d cues → %d segments, %d words, speakers=%s", stats["cues"], stats["segments"], stats["words"], stats["speakers"])

    speaker_mode = show.get("speaker_labels", "auto")
    if speaker_mode == "auto":
        speaker_mode = "none" if not stats["has_speakers"] else (
            "generic" if all(s.lower().startswith("speaker") for s in stats["speakers"]) else "named")

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
            study["translations"] = gen.translate_segments(segments)
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
        "episode_url": ep.link,
        "image_url": ep.image_url,
        "description_html": ep.description_html,
        "transcript": {
            "source": f"rss:{tref.type or tref.kind}",
            "url": tref.url,
            "stats": stats,
            "cues": cues_to_dicts(cues),
            "segments": seg_dicts,
        },
        "study": study,
        "built_at": utcnow_iso(),
    }


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
    ap.add_argument("--no-resolve", action="store_true", help="don't follow enclosure redirects (offline testing)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)

    cfg = load_config(Path(args.config))
    shows = [s for s in cfg["shows"] if not args.show or s["slug"] in args.show]
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
    if args.no_resolve:
        _overrides["resolve"] = False

    gen = StudyGenerator(mock=args.mock)
    now = datetime.now(timezone.utc)
    processed = 0
    failures = 0

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
            if rec and rec.get("status") in ("done", "skipped_long", "no_transcript", "gave_up"):
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

        for ep in candidates:
            if processed >= args.max_new:
                log.info("  reached --max-new=%d; remaining episodes wait for the next run", args.max_new)
                break
            key = episode_key(slug, ep)
            rec = seen.get(key, {"first_seen": utcnow_iso(), "attempts": 0})
            if not ep.best_transcript:
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
                rec.update({"status": "done", "id": doc["id"], "title": ep.title, "published_at": ep.published_iso,
                            "done_at": utcnow_iso(), "attempts": rec.get("attempts", 0) + 1})
                processed += 1
                log.info("  ✓ wrote docs/data/episodes/%s.json", doc["id"])
            except Exception as e:  # noqa: BLE001
                failures += 1
                rec.update({"status": "failed", "title": ep.title, "published_at": ep.published_iso,
                            "error": str(e)[:300], "attempts": rec.get("attempts", 0) + 1, "seen_at": utcnow_iso()})
                log.error("  ✗ failed: %s", e)
                if args.verbose:
                    traceback.print_exc()
            seen[key] = rec
            write_json(STATE_PATH, state)  # checkpoint after every episode

    write_json(STATE_PATH, state)
    index = build.rebuild_index(cfg["shows"])
    log.info("index: %d episodes, processed %d new, %d failures", len(index["episodes"]), processed, failures)
    return 0 if failures == 0 or processed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
