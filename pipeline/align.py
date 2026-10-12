"""Forced alignment of a text transcript to speech-recognition output → timed cues.

Given paragraphs [{speaker, text}] and ASR words [(token, start, end)] from the episode audio,
match the two token streams (difflib), give every transcript token a time (matched: the ASR time;
unmatched: interpolated), then cut sentences into cues. Stretches of audio with no transcript
words (inserted ads, a pre-roll) are detected and removed so cue times are on an ad-free
"content" timeline, like the publisher-provided VTT files.
"""
from __future__ import annotations

import difflib
import re

from .sync import tokens
from .transcript import Cue

TOKEN_SEC = 0.33          # typical spoken-word duration, used for interpolation
AD_GAP_MIN = 4.0          # an unmatched stretch this much longer than expected is an inserted ad
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'“(A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENT_RE.split(text) if p.strip()]
    # merge very short fragments ("Yes." "I'm Neil.") into their neighbour for readable cues
    out: list[str] = []
    for p in parts:
        if out and len(p.split()) <= 2:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def align_paragraphs(paragraphs: list[dict], words: list[tuple[str, float, float]], audio_dur: float) -> tuple[list[Cue], dict]:
    sents: list[dict] = []
    for p in paragraphs:
        for s in split_sentences(p["text"]):
            sents.append({"spk": p.get("speaker") or None, "text": s, "tokens": tokens(s)})
    T: list[tuple[str, int]] = [(tok, si) for si, s in enumerate(sents) for tok in s["tokens"]]
    if not T or not words:
        raise ValueError("nothing to align")
    sm = difflib.SequenceMatcher(None, [t for t, _ in T], [w[0] for w in words], autojunk=False)
    times: list[tuple[float, float] | None] = [None] * len(T)
    matched = 0
    for a, b, size in sm.get_matching_blocks():
        for j in range(size):
            times[a + j] = (words[b + j][1], words[b + j][2])
            matched += 1
    coverage = matched / len(T)
    if coverage < 0.35:
        raise ValueError(f"alignment too weak ({coverage:.0%} of transcript tokens matched)")

    # Fill gaps and detect inserted ads (long silences in the transcript's terms).
    ad_gaps: list[tuple[float, float]] = []      # (runner start, runner end)
    known = [i for i, t in enumerate(times) if t is not None]
    first, last = known[0], known[-1]
    # leading unmatched tokens: pack them right before the first match
    t_first = times[first][0]
    for k, i in enumerate(range(first - 1, -1, -1)):
        end = t_first - k * TOKEN_SEC
        times[i] = (max(0.0, end - TOKEN_SEC), max(0.0, end))
    # trailing
    t_last = times[last][1]
    for k, i in enumerate(range(last + 1, len(T))):
        times[i] = (t_last + k * TOKEN_SEC, t_last + (k + 1) * TOKEN_SEC)
    # middle runs
    i = first
    while i < last:
        if times[i + 1] is not None:
            i += 1
            continue
        j = i + 1
        while times[j] is None:
            j += 1
        n = j - i - 1
        t0, t1 = times[i][1], times[j][0]
        expected = n * TOKEN_SEC
        gap = t1 - t0
        if gap > expected + AD_GAP_MIN:
            # inserted ad: content words sit at the end of the gap, the ad fills the rest
            start = t1 - expected
            for k in range(n):
                times[i + 1 + k] = (start + k * TOKEN_SEC, start + (k + 1) * TOKEN_SEC)
        else:
            step = gap / (n + 1)
            for k in range(n):
                times[i + 1 + k] = (t0 + step * (k + 0.5) - min(step / 2, TOKEN_SEC / 2), t0 + step * (k + 1))
        i = j

    # Inserted ads show up as jumps between consecutive transcript tokens.
    for i in range(len(T) - 1):
        gap = times[i + 1][0] - times[i][1]
        if gap > AD_GAP_MIN:
            ad_gaps.append((times[i][1] + 0.3, times[i + 1][0] - 0.3))
    # Pre-roll: whatever plays before the first transcript word is not content.
    preroll = max(0.0, times[0][0] - 0.3)
    ad_gaps = [(a, b) for a, b in ad_gaps if b - a > 1.0]

    def to_content(t: float) -> float:
        c = t - preroll
        for a, b in ad_gaps:
            if t >= b:
                c -= (b - a)
            elif t > a:
                c -= (t - a)
        return max(0.0, c)

    # cues per sentence (content time), monotonic
    cues: list[Cue] = []
    tok_idx = 0
    prev_end = 0.0
    for si, s in enumerate(sents):
        n = len(s["tokens"])
        if n == 0:
            continue
        seg = times[tok_idx:tok_idx + n]
        tok_idx += n
        start = to_content(min(x[0] for x in seg))
        end = to_content(max(x[1] for x in seg)) + 0.15
        start = max(start, prev_end)
        end = max(end, start + 0.4)
        cues.append(Cue(i=len(cues), s=round(start, 3), e=round(end, 3), t=s["text"], spk=s["spk"]))
        prev_end = end
    markers = [{"type": "mid", "sec": round(to_content(b), 3)} for a, b in ad_gaps]
    info = {
        "coverage": round(coverage, 3),
        "preroll_runner": round(preroll, 3),
        "ad_gaps_runner": [(round(a, 2), round(b, 2)) for a, b in ad_gaps],
        "content_duration": round(cues[-1].e, 3) if cues else 0.0,
        "runner_duration": round(audio_dur, 3),
        "markers": markers,
    }
    return cues, info
