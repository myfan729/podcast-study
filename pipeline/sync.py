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
TARGET_TOKENS = 24        # transcript words used to locate a break in the ASR output
MIN_SCORE = 0.55
ASR_MODEL = "base.en"

_token_re = re.compile(r"[^a-z0-9']+")


def tokens(text: str) -> list[str]:
    return [t for t in _token_re.split(text.lower().replace("’", "'")) if t]


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
        for c_k in [0.0] + sorted(markers):
            exp = c_k + offset
            lo, hi = max(0.0, exp - 4), min(dur, exp + budget + 40)
            words = asr.words(pcm16, lo, hi)
            hit = locate(cue_tokens(cues, c_k), words, lo, hi)
            if not hit:
                out.append({"c": c_k, "a": None, "error": "not found"})
                continue
            new_offset = hit["offset"]
            out.append({"c": c_k, "a": round(c_k + new_offset, 3), "score": hit["score"]})
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


def build(doc: dict, asr: Asr, session, do_selftest: bool = False) -> dict:
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
    refs = []
    for br in breaks:
        if br.get("a") is None:
            continue
        a0 = max(0, int(br["a"] * F.SR))
        seg = pcm8[a0:a0 + int(REF_LEN * F.SR)]
        if len(seg) < F.N_FFT * 4:
            continue
        refs.append({"c": br["c"], "len": round(len(seg) / F.SR, 3), "fp": F.encode(F.fingerprint(seg))})
    out = {
        "v": 1, "sr": F.SR, "hop": F.HOP_SEC, "content_duration": content_dur, "runner_duration": round(dur, 3),
        "ad_total_runner": round(ad_total, 3), "markers": markers, "breaks": breaks, "refs": refs,
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
    asr = Asr(args.model)
    session = http_session()
    failures = 0
    for p, doc, existing in todo:
        log.info("▶ sync %s", p.stem)
        attempts = (existing or {}).get("attempts", 0) + 1
        try:
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
