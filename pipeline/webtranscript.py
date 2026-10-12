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
    s = re.sub(r"\s+([,.;:?!])", r"\1", s)
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

    After a <p><strong>TRANSCRIPT</strong></p> marker, turns are laid out as
    <strong>Name</strong><br>line<br>line<br><strong>Name</strong><br>… — several turns per <p>.
    Vocabulary words are also bold but are followed by text, not by a line break.
    """
    soup = BeautifulSoup(html, "html.parser")
    marker = None
    for p in soup.find_all(["p", "h2", "h3", "h4"]):
        if re.fullmatch(r"transcript[:.]?", _clean(p.get_text(" ")), re.I):
            marker = p
            break
    if marker is None:
        raise ValueError("no TRANSCRIPT marker found")

    paras: list[dict] = []
    speaker = ""
    buf: list[str] = []

    def flush() -> None:
        text = _clean(" ".join(buf))
        buf.clear()
        if text and not re.search(r"not a word-for-word transcript", text, re.I) and not re.match(r"^note:", text, re.I):
            paras.append({"speaker": speaker, "text": text})

    for node in marker.find_all_next(["p", "h2", "h3", "h4"]):
        if node.name != "p":
            if paras:
                break
            continue
        txt = _clean(node.get_text(" "))
        if not txt:
            continue
        if paras and (re.match(r"^what do you think of", txt, re.I) or re.match(r"^(find|try|practise|download)\b", txt, re.I)):
            break
        children = list(node.children)
        for idx, child in enumerate(children):
            if isinstance(child, NavigableString):
                buf.append(str(child))
            elif isinstance(child, Tag) and child.name == "br":
                buf.append(" ")
            elif isinstance(child, Tag) and child.name in ("strong", "b"):
                label = _clean(child.get_text(" "))
                nxt = next((c for c in children[idx + 1:] if not (isinstance(c, NavigableString) and not str(c).strip())), None)
                on_own_line = nxt is None or (isinstance(nxt, Tag) and nxt.name == "br")
                if label and SPEAKER_RE.match(label) and on_own_line and not re.fullmatch(r"transcript", label, re.I):
                    flush()
                    speaker = label
                else:
                    buf.append(" " + label + " ")
            elif isinstance(child, Tag):
                buf.append(child.get_text(" "))
        flush()
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


def fetch_page(session, url: str) -> str:
    r = session.get(url, timeout=40, headers={"Accept": "text/html"})
    r.raise_for_status()
    return r.text


def parse_paragraphs(html: str, parser: str) -> list[dict]:
    fn = PARSERS.get(parser or "generic", parse_generic)
    paras = fn(html)
    words = sum(len(p["text"].split()) for p in paras)
    log.info("  web transcript: %d paragraphs, %d words (%s)", len(paras), words, parser)
    return paras


def fetch_paragraphs(session, url: str, parser: str) -> list[dict]:
    return parse_paragraphs(fetch_page(session, url), parser)


def find_audio_link(html: str, base_url: str = "") -> str | None:
    """An .mp3 the page itself offers (BBC Learning English links an ad-free programme download)."""
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "html.parser")
    links = [urljoin(base_url, a["href"]) for a in soup.find_all("a", href=True) if re.search(r"\.mp3(\?|$)", a["href"], re.I)]
    if not links:
        return None
    links.sort(key=lambda u: (0 if "download" in u.lower() else 1, len(u)))
    return links[0]


def resolve_page_url(session, show: dict, ep) -> str:
    """Where this episode's transcript page lives.

    `page_url` in the show config is a template with {year}, {yymmdd}, {yyyymmdd} filled from the
    episode's publication date (UTC); the day before/after is tried too since feeds and sites
    disagree on timestamps. Falls back to the feed's <link>.
    """
    from datetime import timedelta
    tpl = show.get("page_url")
    if tpl:
        for delta in (0, -1, 1):
            d = ep.published_at + timedelta(days=delta)
            url = tpl.format(year=d.strftime("%Y"), yymmdd=d.strftime("%y%m%d"), yyyymmdd=d.strftime("%Y%m%d"))
            try:
                r = session.head(url, timeout=20, allow_redirects=True)
                if r.status_code == 200:
                    return r.url
            except Exception:  # noqa: BLE001
                continue
        log.warning("  transcript page not found from date template; falling back to feed link")
    if not ep.link:
        raise RuntimeError("no transcript page URL for this episode")
    return ep.link
