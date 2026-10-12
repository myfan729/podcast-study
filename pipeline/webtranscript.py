"""Transcripts published on the show's website (no timestamps) → paragraphs [{speaker, text}].

Each parser takes the page HTML and returns ordered paragraphs. Timing is added later by aligning
the text to speech recognition (pipeline/align.py).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from .util import log

SPEAKER_RE = re.compile(r"^[A-Z][A-Za-z.'\-]{1,20}(?: [A-Z][A-Za-z.'\-]{1,20}){0,2}$")
STOP_HEADINGS = re.compile(r"^(vocabulary|try|latest|more|download|credits|related|next|programme|episodes?)\b", re.I)


def _clean(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _para_lines(p: Tag) -> list[str]:
    """Text of a <p>, split on <br>."""
    parts: list[str] = [""]
    for node in p.descendants:
        if isinstance(node, NavigableString):
            parts[-1] += str(node)
        elif isinstance(node, Tag) and node.name == "br":
            parts.append("")
    return [_clean(x) for x in parts if _clean(x)]


def parse_bbc_le(html: str) -> list[dict]:
    """BBC Learning English feature pages (6 Minute English, The English We Speak, …).

    The transcript sits in a rich-text block after a 'TRANSCRIPT' marker; each turn is a <p> whose
    bold lead-in is the speaker's name followed by a <br> and the line.
    """
    soup = BeautifulSoup(html, "html.parser")
    # candidates: every <p>/<h*> in document order; find the TRANSCRIPT marker
    nodes = [n for n in soup.find_all(["p", "h2", "h3", "h4", "div"])]
    start = None
    for i, n in enumerate(nodes):
        txt = _clean(n.get_text(" "))
        if n.name != "div" and re.fullmatch(r"transcript[:.]?", txt, re.I):
            start = i
            break
    if start is None:
        # some pages mark it as a bold line inside a <p>
        for i, n in enumerate(nodes):
            if n.name == "p" and re.match(r"^\s*transcript\b", _clean(n.get_text(" ")), re.I) and len(_clean(n.get_text(" "))) < 40:
                start = i
                break
    if start is None:
        raise ValueError("no TRANSCRIPT marker found")

    paras: list[dict] = []
    speaker = ""
    for n in nodes[start + 1:]:
        if n.name in ("h2", "h3", "h4"):
            if paras:
                break
            continue
        if n.name == "div":
            continue
        lines = _para_lines(n)
        if not lines:
            continue
        txt = " ".join(lines)
        if re.match(r"^note:", txt, re.I) or re.search(r"not a word-for-word transcript", txt, re.I):
            continue
        if STOP_HEADINGS.match(txt) and len(txt) < 40 and paras:
            break
        first = n.find(["strong", "b"])
        lead = _clean(first.get_text(" ")) if first else ""
        if lead and SPEAKER_RE.match(lead) and lines and lines[0].startswith(lead):
            speaker = lead
            rest = lines[1:] if len(lines) > 1 else [lines[0][len(lead):].strip(" :")]
            text = " ".join(x for x in rest if x)
            if text:
                paras.append({"speaker": speaker, "text": text})
            continue
        if len(lines) == 1 and SPEAKER_RE.match(lines[0]) and len(lines[0]) < 25:
            speaker = lines[0]          # a name on its own line labels what follows
            continue
        paras.append({"speaker": speaker, "text": txt})
    if len(paras) < 4:
        raise ValueError(f"transcript too short ({len(paras)} paragraphs)")
    return paras


def parse_voa_le(html: str) -> list[dict]:
    """VOA Learning English article pages: the article body is the transcript."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("#article-content, .wsw, .body-container") or soup.find("article") or soup
    paras: list[dict] = []
    for p in body.find_all("p"):
        txt = _clean(p.get_text(" "))
        if not txt:
            continue
        if re.match(r"^(words in this story|_{3,}|we want to hear from you|quiz)", txt, re.I):
            break
        if re.match(r"^(i'?m|and i'?m) [A-Z]", txt) and len(txt) < 40:
            paras.append({"speaker": "", "text": txt})
            continue
        paras.append({"speaker": "", "text": txt})
    if len(paras) < 3:
        raise ValueError("article body not found")
    return paras


def parse_generic(html: str) -> list[dict]:
    """Largest cluster of <p> text on the page — a last resort."""
    soup = BeautifulSoup(html, "html.parser")
    best, best_len = None, 0
    for div in soup.find_all(["div", "article", "section", "main"]):
        ps = div.find_all("p", recursive=False)
        n = sum(len(_clean(p.get_text(" "))) for p in ps)
        if n > best_len:
            best, best_len = ps, n
    paras = [{"speaker": "", "text": _clean(p.get_text(" "))} for p in (best or []) if _clean(p.get_text(" "))]
    if len(paras) < 3:
        raise ValueError("no transcript-like block")
    return paras


PARSERS = {"bbc_le": parse_bbc_le, "voa_le": parse_voa_le, "generic": parse_generic}


def fetch_paragraphs(session, url: str, parser: str) -> list[dict]:
    r = session.get(url, timeout=40, headers={"Accept": "text/html"})
    r.raise_for_status()
    fn = PARSERS.get(parser or "generic", parse_generic)
    paras = fn(r.text)
    words = sum(len(p["text"].split()) for p in paras)
    log.info("  web transcript: %d paragraphs, %d words (%s)", len(paras), words, parser)
    return paras
