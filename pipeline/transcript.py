"""Transcript parsing (WebVTT / SRT / JSON / timestamped text) and segmentation.

A *cue* is one timed line as delivered by the publisher. A *segment* is a
readable paragraph: consecutive cues by the same speaker, split at sentence
boundaries so each block is roughly 40–110 words. The study page highlights
cues for playback sync and renders segments for reading.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

TIMESTAMP_RE = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
CUE_LINE_RE = re.compile(
    r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
VOICE_TAG_RE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]*)>", re.I)
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
SPEAKER_PREFIX_RE = re.compile(r"^\s*([A-Z][A-Za-z0-9 .'\-]{0,40}?):\s+(?=\S)")
SENTENCE_END_RE = re.compile(r"[.!?]['\")\]]?$")


@dataclass
class Cue:
    i: int
    s: float          # start seconds
    e: float          # end seconds
    t: str            # text
    spk: str | None   # speaker label as given by the publisher, if any


@dataclass
class Segment:
    id: str
    start: float
    end: float
    speaker: str | None
    text: str
    cue_from: int
    cue_to: int       # inclusive

    @property
    def words(self) -> int:
        return len(self.text.split())


def parse_timestamp(raw: str) -> float:
    m = TIMESTAMP_RE.fullmatch(raw.strip())
    if not m:
        raise ValueError(f"bad timestamp: {raw!r}")
    h, mi, s, ms = m.groups()
    ms = (ms + "000")[:3]
    return (int(h or 0) * 3600) + int(mi) * 60 + int(s) + int(ms) / 1000.0


def clean_text(text: str) -> str:
    text = TAG_RE.sub("", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text).strip()
    # Light ASR cleanup seen in Omny output: "$ 40 billion" → "$40 billion", "9. 38" → "9.38"
    text = re.sub(r"\$\s+(\d)", r"$\1", text)
    text = re.sub(r"(\d)\.\s+(\d{2}\b)", r"\1.\2", text)
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    return text


def _extract_speaker(text: str, allow_prefix: bool) -> tuple[str | None, str]:
    """Pull a speaker label out of a cue's text ("<v Name>…" or "Name: …")."""
    m = VOICE_TAG_RE.search(text)
    if m:
        spk = m.group(1).strip()
        return (spk or None), text
    if allow_prefix:
        m = SPEAKER_PREFIX_RE.match(text)
        if m and not re.match(r"^\d", m.group(1)):
            return m.group(1).strip(), text[m.end():]
    return None, text


def parse_vtt(text: str, speaker_prefix: bool = True) -> list[Cue]:
    text = text.lstrip("﻿")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[Cue] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = CUE_LINE_RE.match(line)
        if not m:
            i += 1
            continue
        start, end = parse_timestamp(m.group(1)), parse_timestamp(m.group(2))
        i += 1
        body: list[str] = []
        while i < n and lines[i].strip() != "":
            if CUE_LINE_RE.match(lines[i]):
                break  # malformed file without blank lines: next cue starts here
            if lines[i].strip().isdigit() and i + 1 < n and CUE_LINE_RE.match(lines[i + 1]):
                break  # numeric cue identifier of the next cue
            body.append(lines[i])
            i += 1
        raw = " ".join(body)
        spk, raw = _extract_speaker(raw, allow_prefix=speaker_prefix)
        t = clean_text(raw)
        if t:
            cues.append(Cue(i=len(cues), s=start, e=max(end, start), t=t, spk=spk))
    return cues


def parse_srt(text: str, speaker_prefix: bool = True) -> list[Cue]:
    # SRT is structurally the same as VTT without the header; the cue-line regex
    # accepts both comma and dot separators, so the VTT parser handles it.
    return parse_vtt(text, speaker_prefix=speaker_prefix)


def parse_json_transcript(text: str) -> list[Cue]:
    """Podcasting 2.0 JSON transcript: {"segments":[{"startTime","endTime","speaker","body"}]}"""
    data = json.loads(text)
    segs = data.get("segments") if isinstance(data, dict) else data
    cues: list[Cue] = []
    for seg in segs or []:
        body = clean_text(str(seg.get("body") or seg.get("text") or ""))
        if not body:
            continue
        s = float(seg.get("startTime", seg.get("start", 0)) or 0)
        e = float(seg.get("endTime", seg.get("end", s)) or s)
        cues.append(Cue(i=len(cues), s=s, e=max(e, s), t=body, spk=(seg.get("speaker") or None)))
    return cues


LINE_TS_RE = re.compile(
    r"^\s*(?:(?P<spk>[A-Z][A-Za-z0-9 .'\-]{0,40}?)\s*)?[\[(]?(?P<ts>(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)[\])]?\s*[:\-–]?\s*(?P<text>.+)$"
)


def parse_timestamped_text(text: str) -> list[Cue]:
    """Plain text where lines start with a timestamp (and maybe a speaker). End times are inferred."""
    cues: list[Cue] = []
    for line in text.replace("\r", "").split("\n"):
        m = LINE_TS_RE.match(line)
        if not m:
            continue
        ts = m.group("ts")
        ts = ts if re.search(r"[.,]\d", ts) else ts + ".000"
        try:
            s = parse_timestamp(ts)
        except ValueError:
            continue
        spk = (m.group("spk") or "").strip() or None
        t = clean_text(m.group("text"))
        if t:
            cues.append(Cue(i=len(cues), s=s, e=s, t=t, spk=spk))
    for a, b in zip(cues, cues[1:]):
        a.e = max(a.s, b.s)
    if cues:
        cues[-1].e = cues[-1].s + max(2.0, len(cues[-1].t.split()) / 2.5)
    return cues


def parse_transcript(text: str, kind: str) -> list[Cue]:
    kind = (kind or "").lower()
    if kind == "json":
        return parse_json_transcript(text)
    if kind in ("vtt", "srt", "unknown", "html"):
        cues = parse_vtt(text)
        if cues:
            return cues
    if kind in ("text", "unknown"):
        return parse_timestamped_text(text)
    # Last resort: try everything.
    return parse_vtt(text) or parse_timestamped_text(text)


def _normalize_speakers(cues: list[Cue]) -> None:
    """Tidy speaker labels: 'speaker 1' → 'Speaker 1'; drop empty."""
    for c in cues:
        if c.spk:
            spk = re.sub(r"\s+", " ", c.spk).strip(" :")
            m = re.fullmatch(r"(?i)speaker\s*(\d+)", spk)
            c.spk = f"Speaker {m.group(1)}" if m else spk


def segment_cues(
    cues: list[Cue],
    target_words: int = 70,
    max_words: int = 120,
    gap_break: float = 1.6,
) -> list[Segment]:
    """Group cues into paragraphs.

    Break rules (in order): speaker change; a pause longer than `gap_break` at a
    sentence end; sentence end once the block has >= target_words; hard cap at
    max_words at the next sentence end or, failing that, at the next cue.
    """
    _normalize_speakers(cues)
    segments: list[Segment] = []
    buf: list[Cue] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        text = " ".join(c.t for c in buf).strip()
        segments.append(
            Segment(
                id=f"s{len(segments) + 1}",
                start=buf[0].s,
                end=buf[-1].e,
                speaker=buf[0].spk,
                text=text,
                cue_from=buf[0].i,
                cue_to=buf[-1].i,
            )
        )
        buf = []

    for c in cues:
        if buf:
            prev = buf[-1]
            words = sum(len(x.t.split()) for x in buf)
            prev_ends = bool(SENTENCE_END_RE.search(prev.t))
            if (c.spk or None) != (prev.spk or None):
                flush()
            elif prev_ends and (c.s - prev.e) > gap_break:
                flush()
            elif prev_ends and words >= target_words:
                flush()
            elif words >= max_words and (prev_ends or words >= max_words + 40):
                flush()
        buf.append(c)
    flush()
    return segments


def cues_to_dicts(cues: list[Cue]) -> list[dict]:
    out = []
    for c in cues:
        d = {"i": c.i, "s": round(c.s, 3), "e": round(c.e, 3), "t": c.t}
        if c.spk:
            d["spk"] = c.spk
        out.append(d)
    return out


def segments_to_dicts(segments: list[Segment]) -> list[dict]:
    out = []
    for s in segments:
        d = asdict(s)
        d["start"] = round(s.start, 3)
        d["end"] = round(s.end, 3)
        out.append(d)
    return out


def transcript_stats(cues: list[Cue], segments: list[Segment]) -> dict:
    words = sum(len(c.t.split()) for c in cues)
    speakers = sorted({c.spk for c in cues if c.spk})
    return {
        "cues": len(cues),
        "segments": len(segments),
        "words": words,
        "speakers": speakers,
        "has_speakers": bool(speakers),
        "end_sec": round(cues[-1].e, 3) if cues else 0,
    }


SENT_END_RE = re.compile(r"[.!?…][\"'”’)\]]*$")


def group_sentences(cues: list, segments: list | None = None, max_words: int = 45) -> list[list[int]]:
    """Merge caption-sized cues into sentences: [[first_cue, last_cue], ...].

    A sentence ends at a cue whose text ends with . ! ? (closing quotes allowed), at a speaker change,
    at a segment boundary, or after max_words (captions without punctuation)."""
    def g(c, k):
        return getattr(c, k, None) if not isinstance(c, dict) else c.get(k)
    bounds = set()
    if segments:
        for sg in segments:
            bounds.add(g(sg, "cue_from"))
    out: list[list[int]] = []
    start, words = None, 0
    for idx, c in enumerate(cues):
        i = g(c, "i")
        nxt = cues[idx + 1] if idx + 1 < len(cues) else None
        if start is None:
            start, words = i, 0
        words += len(g(c, "t").split())
        ends = bool(SENT_END_RE.search(g(c, "t").strip())) or nxt is None or words >= max_words
        if nxt is not None and not ends:
            if (g(nxt, "spk") or None) != (g(c, "spk") or None) or g(nxt, "i") in bounds:
                ends = True
        if ends:
            out.append([start, i])
            start = None
    return out
