"""Build docs/data/sync/<episode>.json — reference fingerprints for automatic ad-aware sync.

The publisher inserts ads into the audio at download time, so transcript timestamps (content time)
drift from the file's clock. This module downloads one copy of the episode, uses speech recognition
to find where the transcript's content starts (after the pre-roll) and resumes (after each mid-roll),
then fingerprints 45 s of content after each break. The page downloads its own copy, fingerprints the
same spots and matches them against these references (docs/assets/sync.js). Audio is never kept.

Usage:  python -m pipeline.sync [--max 4] [--only <episode-id>] [--force] [--selftest]
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
import tempfile
import time
from pathlib import Path
from statistics import median

import numpy as np

from . import fingerprint as F
from .build import EPISODES_DIR, DATA
from .util import http_session, log, read_json, setup_logging, utcnow_iso, write_json

SYNC_DIR = DATA / "sync"
REF_LEN = 45.0            # seconds of content fingerprinted after each break
BACKUP_AT = 60.0          # …and again this far into the same stretch, in case the first spot fails in a browser
GRID_EVERY = 120.0        # …and every this many seconds of content (catches ad slots that were empty in our copy)
RETRY_AT = (0.0, 25.0, 60.0, 120.0)   # content seconds after a break where its text is looked for
TARGET_TOKENS = 24        # transcript words used to locate a break in the ASR output
MIN_SCORE = 0.55
ASR_MODEL = "base.en"

_token_re = re.compile(r"[^a-z0-9']+")
# spellings that differ between scripts and ASR output but are the same spoken word
_NORMALISE = {"okay": "ok", "mmm": "hmm", "mm": "hmm", "umm": "um", "uhm": "um", "erm": "um", "er": "uh", "err": "uh",
              "alright": "allright", "mr": "mister", "mrs": "missus", "dr": "doctor", "vs": "versus"}
_ISE_RE = re.compile(r"(?<=[a-z]{3})i[sz](e[sd]?|ing|ation|ations|ational)$")


def _norm(tok: str) -> str:
    tok = _NORMALISE.get(tok, tok)
    # British -ise / American -ize (optimisation vs optimization)
    return _ISE_RE.sub(lambda m: "iz" + m.group(1), tok)


def tokens(text: str) -> list[str]:
    return [_norm(t) for t in _token_re.split(text.lower().replace("’", "'")) if t]


# ---------------------------------------------------------------------------
# ASR
# ---------------------------------------------------------------------------

class Asr:
    def __init__(self, model_name: str = ASR_MODEL):
        from faster_whisper import WhisperModel  # heavy import, only when needed
        t0 = time.time()
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8")
        self.name = model_name
        log.info("  whisper %s loaded in %.0fs", model_name, time.time() - t0)

    def words(self, pcm16: np.ndarray, t_lo: float, t_hi: float) -> list[tuple[str, float, float]]:
        """[(token, start, end)] with absolute times, for audio between t_lo and t_hi seconds."""
        lo, hi = int(max(0, t_lo) * 16000), int(min(len(pcm16) / 16000, t_hi) * 16000)
        if hi - lo < 16000:
            return []
        t0 = time.time()
        segments, _ = self.model.transcribe(pcm16[lo:hi], language="en", beam_size=1, word_timestamps=True,
                                            condition_on_previous_text=False, vad_filter=False)
        out: list[tuple[str, float, float]] = []
        for seg in segments:
            for w in seg.words or []:
                for tok in tokens(w.word):
                    out.append((tok, t_lo + w.start, t_lo + w.end))
        log.info("  asr %.0f–%.0fs: %d words in %.0fs", t_lo, t_hi, len(out), time.time() - t0)
        return out


# ---------------------------------------------------------------------------
# Locating transcript text inside ASR output
# ---------------------------------------------------------------------------

def fix_at(cue_fix: list, c: float) -> float:
    """Correction (seconds) for a cue at content time c — linear between calibration points, flat outside."""
    if not cue_fix:
        return 0.0
    if len(cue_fix) == 1 or c <= cue_fix[0][0]:
        return float(cue_fix[0][1])
    for (c0, d0), (c1, d1) in zip(cue_fix, cue_fix[1:]):
        if c <= c1:
            return float(d0 + (d1 - d0) * (c - c0) / max(1e-6, c1 - c0))
    return float(cue_fix[-1][1])


def cue_tokens(cues: list[dict], start_sec: float, n: int = TARGET_TOKENS) -> list[tuple[str, float]]:
    """First `n` transcript tokens at/after content time `start_sec`, each with an estimated content time."""
    out: list[tuple[str, float]] = []
    for c in cues:
        if c["e"] < start_sec - 0.2:
            continue
        toks = tokens(c["t"])
        if not toks:
            continue
        span = max(0.2, c["e"] - c["s"])
        for i, tok in enumerate(toks):
            out.append((tok, c["s"] + span * i / len(toks)))
            if len(out) >= n:
                return out
    return out


def locate(target: list[tuple[str, float]], words: list[tuple[str, float, float]],
           t_lo: float, t_hi: float) -> dict | None:
    """Find `target` tokens in `words` restricted to [t_lo, t_hi]. Returns {offset, score, time}."""
    cand = [(i, w) for i, w in enumerate(words) if t_lo <= w[1] <= t_hi]
    if len(cand) < max(6, len(target) // 2):
        return None
    tgt = [t for t, _ in target]
    best = None
    n = len(tgt)
    for k in range(0, len(cand)):
        window = [w[0] for _, w in cand[k:k + n]]
        if len(window) < n // 2:
            break
        sm = difflib.SequenceMatcher(None, tgt, window, autojunk=False)
        score = sm.ratio()
        if best is None or score > best[0]:
            best = (score, k, sm.get_matching_blocks())
    if not best or best[0] < MIN_SCORE:
        return None
    score, k, blocks = best
    offsets = []
    for a, b, size in blocks:
        for j in range(size):
            asr_time = cand[k + b + j][1][1]
            content_time = target[a + j][1]
            offsets.append(asr_time - content_time)
    if not offsets:
        return None
    return {"offset": float(median(offsets)), "score": round(score, 3), "n": len(offsets)}


# ---------------------------------------------------------------------------
# Building the sync document
# ---------------------------------------------------------------------------

def download(session, url: str, dest: Path) -> int:
    with session.get(url, stream=True, timeout=120, allow_redirects=True) as r:
        r.raise_for_status()
        n = 0
        with dest.open("wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                n += len(chunk)
    return n


def content_map(asr: Asr, cues: list[dict], pcm16: np.ndarray, dur: float, content_dur: float,
                markers: list[float] | None) -> tuple[list[dict], float]:
    """Return ([{c, a, score}], ad_total). Each entry: content time c resumes at audio time a."""
    ad_total = max(0.0, dur - content_dur)
    budget = ad_total
    offset = 0.0
    out: list[dict] = []
    if markers is not None:
        points = [0.0] + sorted(markers)
        for idx, c_k in enumerate(points):
            seg_end = points[idx + 1] if idx + 1 < len(points) else content_dur
            # the first words after a break can be hard to recognise (music bed, jingle, cold open with several
            # voices), so if they are not found, look for text a little later in the same stretch of content
            delays = [d for d in RETRY_AT if c_k + d + 20 <= seg_end] or [0.0]
            exp = c_k + offset
            lo, hi = max(0.0, exp - 4), min(dur, exp + budget + 40 + max(delays))
            words = asr.words(pcm16, lo, hi)
            hit, used = None, 0.0
            for d in delays:
                hit = locate(cue_tokens(cues, c_k + d), words, max(0.0, exp + d - 4), min(dur, exp + d + budget + 40))
                if hit:
                    used = d
                    break
            if not hit:
                out.append({"c": c_k, "a": None, "error": "not found"})
                continue
            new_offset = hit["offset"]
            br = {"c": c_k, "a": round(c_k + new_offset, 3), "score": hit["score"]}
            if used:
                br["found_at"] = round(c_k + used, 1)
            out.append(br)
            budget = max(0.0, budget - max(0.0, new_offset - offset))
            offset = new_offset
        return out, ad_total
    # Unknown ad positions: transcribe everything and walk the transcript in ~15 s groups,
    # recording every place where the offset jumps (= an ad break).
    words = asr.words(pcm16, 0.0, dur)
    starts: list[float] = []
    last = -1e9
    for c in cues:
        if c["s"] - last >= 15.0:
            starts.append(c["s"])
            last = c["s"]
    have_offset = False
    for c_k in starts:
        exp = c_k + offset
        lo, hi = max(0.0, exp - 4), min(dur, exp + budget + 10)
        hit = locate(cue_tokens(cues, c_k), words, lo, hi)
        if not hit:
            continue
        off = hit["offset"]
        if not have_offset or abs(off - offset) > 2.5:
            out.append({"c": c_k, "a": round(c_k + off, 3), "score": hit["score"]})
            if have_offset:
                budget = max(0.0, budget - max(0.0, off - offset))
            have_offset = True
            offset = off
    return out, ad_total


def selftest(session, url: str, refs: list[dict], content_dur: float) -> dict:
    """Download a second copy (new ad session) and run the client's matching logic on it."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "b.mp3"
        download(session, url, p)
        pcm8 = F.decode_pcm(p)
    dur = len(pcm8) / F.SR
    probe = F.fingerprint(pcm8)
    budget = max(0.0, dur - content_dur)
    offset = 0.0
    results = []
    for ref in refs:
        fp = F.decode(ref["fp"])
        exp = ref["c"] + offset
        lo = int(max(0.0, exp - 2.5) / F.HOP_SEC)
        hi = int(min(dur, exp + budget + ref["len"] + 6) / F.HOP_SEC)
        o, b, second = F.best_offset(fp, probe, lo, hi)
        ok = b < 0.33 and second - b > 0.04
        a = o * F.HOP_SEC
        results.append({"c": ref["c"], "a": round(a, 3), "ber": round(b, 3), "second": round(second, 3), "ok": ok})
        if ok:
            new_offset = a - ref["c"]
            budget = max(0.0, budget - max(0.0, new_offset - offset))
            offset = new_offset
    return {"duration": round(dur, 3), "results": results}


def build_fixed(doc: dict, session) -> dict:
    """Ad-free file whose cue times are already on the file's clock (audio_meta.fixed): no alignment is
    needed, but a fingerprint of the first spoken passage lets the page confirm it plays the same file."""
    url = doc.get("audio_url_original") or doc["audio_url"]
    cues = doc["transcript"]["cues"]
    am = doc.get("audio_meta") or {}
    a0 = float((am.get("alignment") or {}).get("first_word_runner") or cues[0]["s"])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.mp3"
        n = download(session, url, p)
        pcm8 = F.decode_pcm(p, F.SR)
    dur = len(pcm8) / F.SR
    i0 = max(0, int(a0 * F.SR))
    seg = pcm8[i0:i0 + int(REF_LEN * F.SR)]
    if len(seg) < F.N_FFT * 4:
        raise RuntimeError("audio too short for a reference fingerprint")
    log.info("  fixed file %.1fs (%.1f MB); reference at %.1fs", dur, n / 1048576, a0)
    return {
        "v": 1, "sr": F.SR, "hop": F.HOP_SEC, "fixed": True,
        "content_duration": float(am.get("content_duration") or dur), "runner_duration": round(dur, 3),
        "ad_total_runner": 0.0, "markers": [], "breaks": [{"c": round(a0, 3), "a": round(a0, 3), "score": 1.0}],
        "refs": [{"c": round(a0, 3), "len": round(len(seg) / F.SR, 3), "fp": F.encode(F.fingerprint(seg))}],
        "method": "fixed", "built_at": utcnow_iso(), "status": "ok",
    }


CAL_POINTS = 12          # transcript spots checked against speech recognition to correct cue times


def _map_c2a(breaks: list[dict]):
    """Content time → audio time in OUR copy, from the breaks found (offset is constant between breaks)."""
    known = sorted((b["c"], b["a"] - b["c"]) for b in breaks if b.get("a") is not None)

    def f(c: float) -> float:
        off = known[0][1] if known else 0.0
        for bc, bo in known:
            if bc <= c + 0.01:
                off = bo
        return c + off
    return f


def calibrate(asr: Asr, cues: list[dict], pcm16: np.ndarray, c2a) -> list[list[float]]:
    """Publisher cue times are often a little off (shifted by a second or several, or drifting over the episode).
    Check CAL_POINTS sentences with speech recognition and return a piecewise correction [[c, delta], …]:
    the words of a cue starting at content time c are really heard at content time c + delta(c)."""
    end = cues[-1]["e"] if cues else 0
    usable = [c for c in cues if 20 <= c["s"] <= end - 15 and len(tokens(c["t"])) >= 6]
    if len(usable) < 4:
        return []
    picks = [usable[int(i * (len(usable) - 1) / (CAL_POINTS - 1))] for i in range(CAL_POINTS)]
    pts: list[tuple[float, float]] = []
    for cue in picks:
        exp = c2a(cue["s"])
        words = asr.words(pcm16, exp - 10, exp + 16)
        hit = locate(cue_tokens(cues, cue["s"], 14), words, exp - 10, exp + 16)
        if hit and hit["score"] >= 0.7:
            pts.append((cue["s"], (cue["s"] + hit["offset"]) - exp))
    if len(pts) < 4:
        return []
    deltas = [d for _, d in pts]
    med = float(median(deltas))
    # one shift for the whole episode when the points agree; otherwise a smoothed piecewise correction
    if all(abs(d - med) <= 0.6 for d in deltas):
        return [[0.0, round(med, 2)]] if abs(med) >= 0.25 else []
    sm = []
    for i in range(len(pts)):
        win = [pts[j][1] for j in range(max(0, i - 1), min(len(pts), i + 2))]
        sm.append([round(pts[i][0], 1), round(float(median(win)), 2)])
    return sm


def build(doc: dict, asr: Asr | None, session, do_selftest: bool = False) -> dict:
    if (doc.get("audio_meta") or {}).get("fixed"):
        return build_fixed(doc, session)
    if asr is None:
        raise RuntimeError("ASR model required")
    url = doc.get("audio_url_original") or doc["audio_url"]
    cues = doc["transcript"]["cues"]
    am = doc.get("audio_meta") or {}
    content_dur = float(am.get("content_duration") or doc.get("duration_sec") or cues[-1]["e"])
    markers = ([m["sec"] for m in am.get("ad_markers", []) if m.get("type") == "mid"]
               if am.get("source") in ("omny", "asr-align") else None)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.mp3"
        n = download(session, url, p)
        pcm16 = F.decode_pcm(p, 16000)
        pcm8 = F.decode_pcm(p, F.SR)
    dur = len(pcm16) / 16000
    log.info("  audio %.1fs (%.1f MB), content %.1fs → %.1fs of ads; markers=%s", dur, n / 1048576, content_dur,
             dur - content_dur, markers)
    breaks, ad_total = content_map(asr, cues, pcm16, dur, content_dur, markers)
    try:
        cue_fix = calibrate(asr, cues, pcm16, _map_c2a(breaks))
    except Exception as e:  # noqa: BLE001
        log.warning("  cue calibration failed: %s", e)
        cue_fix = []
    if cue_fix:
        log.info("  cue time correction: %s", cue_fix[:6])
    refs = []
    for i, br in enumerate(breaks):
        if br.get("a") is None:
            continue
        seg_end = breaks[i + 1]["c"] if i + 1 < len(breaks) else content_dur
        # right after the break, a backup a minute later, then a grid every GRID_EVERY seconds: an ad slot that was
        # empty in our copy (so we saw no break there) can be filled in the listener's copy, and the grid catches it
        ds = [0.0, BACKUP_AT] + [g for g in range(int(GRID_EVERY), int(seg_end - br["c"] - REF_LEN), int(GRID_EVERY))]
        for d in sorted(set(ds)):
            if d and br["c"] + d + REF_LEN > seg_end:
                continue
            if d and d != BACKUP_AT and abs(d - BACKUP_AT) < 40:
                continue
            a0 = max(0, int((br["a"] + d) * F.SR))
            seg = pcm8[a0:a0 + int(REF_LEN * F.SR)]
            if len(seg) < F.N_FFT * 4:
                continue
            refs.append({"c": round(br["c"] + d, 3), "len": round(len(seg) / F.SR, 3), "fp": F.encode(F.fingerprint(seg))})
    out = {
        "v": 1, "sr": F.SR, "hop": F.HOP_SEC, "content_duration": content_dur, "runner_duration": round(dur, 3),
        "ad_total_runner": round(ad_total, 3), "markers": markers, "breaks": breaks, "refs": refs, "cue_fix": cue_fix,
        "method": "asr", "model": asr.name, "built_at": utcnow_iso(),
        "status": "ok" if refs and all(b.get("a") is not None for b in breaks) else ("partial" if refs else "failed"),
    }
    if do_selftest and refs:
        try:
            out["selftest"] = selftest(session, url, refs, content_dur)
        except Exception as e:  # noqa: BLE001
            out["selftest"] = {"error": str(e)[:200]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=4)
    ap.add_argument("--only", help="episode id (file stem)")
    ap.add_argument("--force", action="store_true", help="rebuild even if a sync file exists")
    ap.add_argument("--selftest", action="store_true", help="download a second copy and verify matching")
    ap.add_argument("--model", default=ASR_MODEL)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    SYNC_DIR.mkdir(parents=True, exist_ok=True)

    todo = []
    for p in sorted(EPISODES_DIR.glob("*.json"), reverse=True):
        if args.only and p.stem != args.only:
            continue
        doc = read_json(p, None)
        if not doc or doc.get("demo"):
            continue
        existing = read_json(SYNC_DIR / p.name, None)
        if existing and not args.force:
            if existing.get("status") == "ok" or existing.get("attempts", 0) >= 3:
                continue
        todo.append((p, doc, existing))
    todo = todo[:args.max]
    if not todo:
        log.info("sync: nothing to do")
        return 0
    asr = None
    session = http_session()
    failures = 0
    for p, doc, existing in todo:
        log.info("▶ sync %s", p.stem)
        attempts = (existing or {}).get("attempts", 0) + 1
        try:
            if asr is None and not (doc.get("audio_meta") or {}).get("fixed"):
                asr = Asr(args.model)
            out = build(doc, asr, session, do_selftest=args.selftest)
            out["attempts"] = attempts
            write_json(SYNC_DIR / p.name, out, compact=True)
            log.info("  %s: %d refs, breaks=%s", out["status"], len(out["refs"]),
                     [(b["c"], b.get("a")) for b in out["breaks"]])
            if out.get("selftest"):
                log.info("  selftest: %s", out["selftest"])
        except Exception as e:  # noqa: BLE001
            failures += 1
            log.error("  ✗ %s", e)
            write_json(SYNC_DIR / p.name, {"status": "failed", "error": str(e)[:300], "attempts": attempts,
                                           "built_at": utcnow_iso()})
    return 1 if failures and failures == len(todo) else 0


if __name__ == "__main__":
    sys.exit(main())
