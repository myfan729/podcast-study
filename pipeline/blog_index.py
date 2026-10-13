"""Links from episode words/expressions to the owner's existing blog posts.

Reads every post title of the configured Naver blogs (public listing endpoints — no login), pulls the
English phrases out of each title ("[영어표현] perk up 뜻과 예문" → "perk up"), and matches them against
each episode's vocab/expressions. Output: docs/data/blog_links.json
    {"updated_at": ..., "posts": N, "episodes": {episode_id: {item text: {"url", "title"}}}}
The episode page shows a "블로그 글" link next to matched items.

Usage: python -m pipeline.blog_index [-v]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote_plus

from . import build
from .main import CONFIG_PATH, load_config
from .util import http_session, log, read_json, setup_logging, utcnow_iso, write_json

LINKS_PATH = build.DATA / "blog_links.json"
POSTS_CACHE = build.ROOT / "state" / "blog_posts.json"
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; SM-A175F) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/129.0 Mobile Safari/537.36")


# ---------------------------------------------------------------------------
# Fetching post lists (three public endpoints, best first)
# ---------------------------------------------------------------------------

def _post(blog_id: str, log_no, title: str, category=None, date=None) -> dict:
    return {"blog": blog_id, "logNo": str(log_no), "title": html.unescape(title).strip(), "category": category,
            "date": date, "url": f"https://blog.naver.com/{blog_id}/{log_no}"}


def fetch_mobile_api(session, blog_id: str, max_pages: int = 60) -> list[dict]:
    out: list[dict] = []
    headers = {"User-Agent": MOBILE_UA, "Referer": f"https://m.blog.naver.com/{blog_id}?tab=1",
               "Accept": "application/json"}
    for page in range(1, max_pages + 1):
        r = session.get(f"https://m.blog.naver.com/api/blogs/{blog_id}/post-list",
                        params={"categoryNo": 0, "itemCount": 30, "page": page}, headers=headers, timeout=20)
        r.raise_for_status()
        res = (r.json() or {}).get("result") or {}
        items = res.get("items") or []
        for it in items:
            title = it.get("titleWithInspectMessage") or it.get("title") or ""
            out.append(_post(blog_id, it.get("logNo"), title, it.get("categoryName") or it.get("categoryNo"), it.get("addDate")))
        total = int(res.get("totalCount") or 0)
        if not items or len(items) < 30 or (total and len(out) >= total):
            break
        time.sleep(0.3)
    return out


def fetch_title_list(session, blog_id: str, max_pages: int = 60) -> list[dict]:
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        r = session.get("https://blog.naver.com/PostTitleListAsync.naver",
                        params={"blogId": blog_id, "viewdate": "", "currentPage": page, "categoryNo": 0,
                                "parentCategoryNo": "", "countPerPage": 30},
                        headers={"Referer": f"https://blog.naver.com/{blog_id}"}, timeout=20)
        r.raise_for_status()
        text = r.text.replace("\\'", "'")
        data = json.loads(text)
        items = data.get("postList") or []
        for it in items:
            out.append(_post(blog_id, it.get("logNo"), unquote_plus(it.get("title") or ""), it.get("categoryNo"), it.get("addDate")))
        total = int(data.get("totalCount") or 0)
        if not items or len(items) < 30 or (total and len(out) >= total):
            break
        time.sleep(0.3)
    return out


def fetch_rss(session, blog_id: str) -> list[dict]:
    r = session.get(f"https://rss.blog.naver.com/{blog_id}.xml", timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").split("?")[0]
        m = re.search(r"/(\d{6,})$", link)
        if not m:
            continue
        out.append(_post(blog_id, m.group(1), item.findtext("title") or "", item.findtext("category"), item.findtext("pubDate")))
    return out


def fetch_posts(session, blog_id: str) -> tuple[list[dict], str]:
    """Full post list: the title-list endpoint pages through every post; the others are fallbacks."""
    errors = []
    best: tuple[list[dict], str] = ([], "")
    for name, fn in (("title-list", fetch_title_list), ("mobile-api", fetch_mobile_api), ("rss", fetch_rss)):
        try:
            posts = fn(session, blog_id)
            if len(posts) > len(best[0]):
                best = (posts, name)
            if len(posts) >= 100:
                break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    if not best[0]:
        raise RuntimeError(f"could not list posts of {blog_id}: " + "; ".join(errors))
    return best


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

_POSS = r"(?:one's|ones|someone's|somebody's|your|my|his|her|their|our|its)"
_OBJ = r"(?:someone|somebody|something|sb|sth|sb's|sth's|one)"
_EN_RUN = re.compile(r"[A-Za-z][A-Za-z'’\-]*(?:[ \t]+(?:[A-Za-z][A-Za-z'’\-]*|~|\.\.\.))*")


def norm_phrase(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"\(.*?\)", " ", s)                       # "(one's) own" → drop optional parts
    s = re.sub(r"[^a-z0-9' ~-]+", " ", s)
    s = s.replace("-", " ")
    s = re.sub(rf"\b{_POSS}\b", "POSS", s)
    s = re.sub(rf"\b{_OBJ}\b", "OBJ", s)
    s = s.strip()
    if s.startswith("to "):                              # "to perk up" → "perk up"
        s = s[3:]
    s = re.sub(r"^(?:a|an|the) ", "", s.strip())         # "a tall order" → "tall order"
    s = re.sub(r"\s+", " ", s).strip(" ~'")
    return s


def _stem_first(s: str) -> str:
    """Base form of the first word, so 'perks up' / 'perked up' / 'perking up' all match 'perk up'."""
    parts = s.split(" ")
    w = parts[0]
    for suf, rep in (("ying", "y"), ("ies", "y"), ("ied", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: len(w) - len(suf)] + rep
            break
    return " ".join([w] + parts[1:])


def _drop_obj(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\bOBJ\b", " ", s)).strip()


def _variants(s: str) -> list[str]:
    out = []
    for v in (s, _stem_first(s), _drop_obj(s), _stem_first(_drop_obj(s))):
        if v and v not in out:
            out.append(v)
    return out


STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "from", "by", "out", "up", "down", "off",
        "over", "into", "onto", "about", "as", "and", "or", "but", "is", "be", "it", "that", "this", "than",
        "other", "others", "another", "so", "not", "no", "do", "get", "have", "make", "go", "i", "you", "we"}


def _words(p: str) -> list[str]:
    return [w for w in p.split(" ") if w and w not in ("POSS", "OBJ")]


def _is_content(p: str) -> bool:
    w = _words(p)
    return bool(w) and p not in GENERIC and len(p) >= 2 and any(x not in STOP for x in w)


def title_phrases(title: str) -> list[str]:
    """English phrases in a post title, normalised; generic words that appear in many titles are skipped."""
    title = title.replace("(", " ").replace(")", " ").replace("[", " [ ").replace("]", " ] ")
    out = []
    for m in _EN_RUN.finditer(title):
        p = norm_phrase(m.group(0))
        if _is_content(p):
            out.append(p)
    return out


GENERIC = {"speak", "ai", "english", "app", "tip", "tips", "q", "a", "i", "lesson", "day", "vs", "ok", "tv", "sns",
           "premium", "plus", "podcast", "big take", "bbc", "ted", "netflix", "youtube"}


def build_post_index(posts: list[dict]) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for p in posts:
        for ph in title_phrases(p["title"]):
            for key in _variants(ph):
                if _is_content(key):
                    idx.setdefault(key, p)        # newest post first in the listing → keep the first
    return idx


def _contains(hay: str, needle: str) -> bool:
    return re.search(rf"(?<![A-Za-z']){re.escape(needle)}(?![A-Za-z'])", hay) is not None


def _match_part(e: str, idx: dict[str, dict], titles_norm: list[tuple[list[str], dict]]) -> dict | None:
    if not _is_content(e):
        return None
    vs = _variants(e)
    for key in vs:
        if key in idx:
            return idx[key]
    multi = [v for v in vs if len(_words(v)) >= 2]
    for phrases, p in titles_norm:
        for ph in phrases:
            # the expression inside a longer title phrase ("perk up" in "perk up and smile")
            if any(_contains(ph, v) for v in multi):
                return p
            # a multi-word title phrase that is most of the expression ("ripple out" in "ripple out through",
            # "live up to" in "live up to its promise"); "out of", "the other" etc. never count
            nw = len(_words(ph))
            if nw >= 2 and _is_content(ph) and any(_contains(v, ph) and nw * 2 >= len(_words(v)) for v in vs):
                return p
    return None


def match_item(text: str, idx: dict[str, dict], titles_norm: list[tuple[list[str], dict]]) -> dict | None:
    """Alternatives ("a tall order / an uphill climb", "find a bridge out of / into") are tried one by one."""
    parts = [text] + [x for x in re.split(r"\s*(?:/|,|;|\bor\b)\s*", text) if x.strip() and x.strip() != text]
    for part in parts:
        p = _match_part(norm_phrase(part), idx, titles_norm)
        if p:
            return p
    return None


def link_episodes(posts: list[dict]) -> dict[str, dict]:
    idx = build_post_index(posts)
    titles_norm = [(title_phrases(p["title"]), p) for p in posts]
    out: dict[str, dict] = {}
    for path in sorted(build.EPISODES_DIR.glob("*.json")):
        doc = read_json(path, None)
        if not doc:
            continue
        study = doc.get("study") or {}
        items = [v.get("word", "") for v in study.get("vocab") or []] + [x.get("expression", "") for x in study.get("expressions") or []]
        links = {}
        for it in items:
            p = match_item(it, idx, titles_norm)
            if p:
                links[it] = {"url": p["url"], "title": p["title"]}
        if links:
            out[doc["id"]] = links
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config(Path(CONFIG_PATH))
    blogs = cfg.get("blogs") or []
    if not blogs:
        log.info("blog links: no blogs configured")
        return 0
    session = http_session()
    posts: list[dict] = []
    for b in blogs:
        try:
            got, via = fetch_posts(session, b["id"])
            if b.get("categories"):
                wanted = {str(c) for c in b["categories"]}
                got = [p for p in got if str(p.get("category")) in wanted]
            log.info("blog %s: %d posts (%s)", b["id"], len(got), via)
            posts += got
        except Exception as e:  # noqa: BLE001
            log.error("blog %s: %s", b["id"], e)
    if not posts:
        prev = read_json(POSTS_CACHE, None)
        if not prev:
            return 1
        posts = prev.get("posts", [])
        log.warning("using cached post list (%d posts)", len(posts))
    else:
        write_json(POSTS_CACHE, {"updated_at": utcnow_iso(), "posts": posts}, compact=True)
    links = link_episodes(posts)
    write_json(LINKS_PATH, {"updated_at": utcnow_iso(), "posts": len(posts), "episodes": links}, compact=True)
    log.info("blog links: %d episodes with links (%d items)", len(links), sum(len(v) for v in links.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
