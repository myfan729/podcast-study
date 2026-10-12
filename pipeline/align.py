"""Forced alignment of a text transcript to speech-recognition output → timed cues.

Given paragraphs [{speaker, text}] and ASR words [(token, start, end)] from the episode audio,
match the two token streams (difflib), give every transcript token a time (matched: the ASR time;
unmatched: placed on the unmatched ASR words in the same gap, or interpolated), then cut sentences
into cues.

Two kinds of audio:
- ad-inserted podcasts: stretches of audio with no transcript words (inserted ads, a pre-roll) are
  detected and removed so cue times are on an ad-free "content" timeline, like publisher VTT files;
- `ad_free` files (e.g. BBC's programme downloads): the file is identical for every listener, so cues
  simply use the file's own clock. Intro/outro material that is not in the transcript stays where it
  is (nothing is highlighted while it plays).
"""
from __future__ import annotations

import difflib
import re

from .sync import tokens
from .transcript import Cue

ALIGN_VERSION = 2         # bump when the algorithm changes; web-show episodes below this are re-timed
TOKEN_SEC = 0.33          # typical spoken-word duration, used for interpolation
MIN_TOKEN_SEC = 0.15      # faster than anyone speaks: a run squeezed below this marks a misplaced match
AD_GAP_MIN = 8.0          # an unmatched stretch this much longer than expected is an inserted ad (jingles are shorter)
SOLID_BLOCK = 6           # matching blocks at least this long are never dropped by the squeeze repair
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


JUMP_SEC = 1.0            # a silence this long between two words matched as consecutive is suspicious
PEEL_MAX = 4              # how many edge tokens of a block the repair may unmatch


def _repair_squeezes(asr_idx: list[int], bid: list[int], bsize: list[int], words: list[tuple[str, float, float]]) -> int:
    """Fix matches that leave the words between them no time to be spoken.

    difflib matches text only. A word that occurs twice ("January" in a quiz question and in its
    answer) can be matched to the wrong occurrence — typically when the ASR dropped the first one — and
    the words between are squeezed into a fraction of a second. Two repairs, in order: unmatch edge
    tokens of the neighbouring blocks that sit across a time jump (the stray "January"), else drop
    the smaller neighbouring block if it is short. Returns the number of repairs made.
    """
    def unmatch(k: int) -> None:
        bsize[bid[k]] -= 1
        asr_idx[k] = -1
        bid[k] = -1

    repairs = 0
    for _ in range(60):
        known = [i for i, k in enumerate(asr_idx) if k >= 0]
        fixed_one = False
        for i, j in zip(known, known[1:]):
            n = j - i - 1
            if n < 3:
                continue
            avail = words[asr_idx[j]][1] - words[asr_idx[i]][2]
            if avail >= n * MIN_TOKEN_SEC:
                continue
            # 1. peel: a jump inside the tail of the left block / head of the right block
            peeled = False
            for k in range(0, PEEL_MAX):
                a, b = i - k - 1, i - k
                if a < 0 or bid[a] != bid[b] or bid[b] < 0:
                    break
                if words[asr_idx[b]][1] - words[asr_idx[a]][2] > JUMP_SEC:
                    for x in range(b, i + 1):
                        unmatch(x)
                    peeled = True
                    break
            for k in range(0, PEEL_MAX):
                a, b = j + k, j + k + 1
                if b >= len(asr_idx) or bid[a] != bid[b] or bid[a] < 0:
                    break
                if words[asr_idx[b]][1] - words[asr_idx[a]][2] > JUMP_SEC:
                    for x in range(j, a + 1):
                        unmatch(x)
                    peeled = True
                    break
            if peeled:
                fixed_one = True
                break
            # 2. drop the smaller block, unless both are solid (then the script has words that were not spoken)
            bi, bj = bid[i], bid[j]
            small = bi if bsize[bi] <= bsize[bj] else bj
            if bsize[small] >= SOLID_BLOCK:
                continue
            for k, b in enumerate(bid):
                if b == small:
                    asr_idx[k] = -1
                    bid[k] = -1
            bsize[small] = 0
            fixed_one = True
            break
        if not fixed_one:
            break
        repairs += 1
    return repairs


def _spread_on_words(n: int, wlist: list[tuple[str, float, float]]) -> list[tuple[float, float]]:
    """Place n transcript tokens on m ASR words (any m ≥ 1) by proportional position, so pauses between
    the words are respected (linear interpolation would put words into silences)."""
    m = len(wlist)

    def at(f: float) -> float:
        w = min(m - 1, int(f))
        frac = f - w
        return wlist[w][1] + frac * (wlist[w][2] - wlist[w][1]) if f < m else wlist[-1][2]

    out = []
    for k in range(n):
        s, e = at(k * m / n), at((k + 1) * m / n)
        out.append((s, max(e, s + 0.05)))
    return out


def align_paragraphs(paragraphs: list[dict], words: list[tuple[str, float, float]], audio_dur: float,
                     ad_free: bool = False) -> tuple[list[Cue], dict]:
    sents: list[dict] = []
    for p in paragraphs:
        for s in split_sentences(p["text"]):
            sents.append({"spk": p.get("speaker") or None, "text": s, "tokens": tokens(s)})
    T: list[tuple[str, int]] = [(tok, si) for si, s in enumerate(sents) for tok in s["tokens"]]
    if not T or not words:
        raise ValueError("nothing to align")
    sm = difflib.SequenceMatcher(None, [t for t, _ in T], [w[0] for w in words], autojunk=False)
    blocks = [(a, b, size) for a, b, size in sm.get_matching_blocks() if size]
    asr_idx = [-1] * len(T)           # matched ASR word per transcript token
    bid = [-1] * len(T)               # matching block per transcript token
    bsize = [size for _, _, size in blocks]
    for k, (a, b, size) in enumerate(blocks):
        for j in range(size):
            asr_idx[a + j] = b + j
            bid[a + j] = k
    coverage = sum(1 for k in asr_idx if k >= 0) / len(T)
    if coverage < 0.35:
        raise ValueError(f"alignment too weak ({coverage:.0%} of transcript tokens matched)")
    repaired = _repair_squeezes(asr_idx, bid, bsize, words)

    times: list[tuple[float, float] | None] = [(words[k][1], words[k][2]) if k >= 0 else None for k in asr_idx]
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
        between = words[asr_idx[i] + 1:asr_idx[j]]          # ASR words the transcript did not match here
        if not ad_free and gap > expected + AD_GAP_MIN:
            # inserted ad: content words sit at the end of the gap, the ad fills the rest
            start = t1 - expected
            for k in range(n):
                times[i + 1 + k] = (start + k * TOKEN_SEC, start + (k + 1) * TOKEN_SEC)
        elif between and n / 2 <= len(between) <= 3 * n + 5:
            # misrecognised words: same speech, different spelling — take their timing
            # (far fewer ASR words than transcript words means the ASR dropped speech: interpolate instead)
            for k, te in enumerate(_spread_on_words(n, between)):
                times[i + 1 + k] = te
        else:
            step = gap / (n + 1)
            for k in range(n):
                times[i + 1 + k] = (t0 + step * (k + 0.5) - min(step / 2, TOKEN_SEC / 2), t0 + step * (k + 1))
        i = j

    # Inserted ads show up as jumps between consecutive transcript tokens.
    ad_gaps: list[tuple[float, float]] = []      # (runner start, runner end)
    if not ad_free:
        for i in range(len(T) - 1):
            gap = times[i + 1][0] - times[i][1]
            if gap > AD_GAP_MIN:
                ad_gaps.append((times[i][1] + 0.3, times[i + 1][0] - 0.3))
        ad_gaps = [(a, b) for a, b in ad_gaps if b - a > 1.0]
    # Pre-roll: whatever plays before the first transcript word is not content (ad-inserted files only).
    preroll = 0.0 if ad_free else max(0.0, times[0][0] - 0.3)

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
        "version": ALIGN_VERSION,
        "ad_free": ad_free,
        "coverage": round(coverage, 3),
        "repaired_blocks": repaired,
        "preroll_runner": round(preroll, 3),
        "first_word_runner": round(times[0][0], 3),
        "last_word_runner": round(times[-1][1], 3),
        "ad_gaps_runner": [(round(a, 2), round(b, 2)) for a, b in ad_gaps],
        "content_duration": round(audio_dur, 3) if ad_free else (round(cues[-1].e, 3) if cues else 0.0),
        "runner_duration": round(audio_dur, 3),
        "markers": markers,
    }
    return cues, info
