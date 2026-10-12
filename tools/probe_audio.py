"""Probe 3: BBC Learning English feed → item link → page structure outline (for the parser)."""
import json, re, sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup

FEED = "https://podcasts.files.bbci.co.uk/p02pc9tn.rss"
UA = {"User-Agent": "Mozilla/5.0 (podcast-study probe)"}


def outline(html, limit=400):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "div", "section", "a", "strong", "b", "li"]):
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))[:70]
        cls = " ".join(el.get("class", []))[:50]
        if el.name in ("div", "section") and not cls:
            continue
        if not txt and el.name != "a":
            continue
        href = el.get("href", "")[:80] if el.name == "a" else ""
        if el.name == "a" and not re.search(r"transcript|\.pdf|\.mp3|download", href, re.I):
            continue
        out.append(f"{el.name}.{cls}| {txt} {('→ ' + href) if href else ''}")
        if len(out) >= limit:
            break
    return out


def main():
    s = requests.Session(); s.headers.update(UA)
    res = {}
    feed = s.get(FEED, timeout=30).text
    items = re.findall(r"<item>(.*?)</item>", feed, re.S)[:2]
    res["feed_items"] = []
    for it in items:
        title = re.search(r"<title>(.*?)</title>", it, re.S); link = re.search(r"<link>(.*?)</link>", it, re.S)
        enc = re.search(r'<enclosure[^>]*url="([^"]+)"', it); guid = re.search(r"<guid[^>]*>(.*?)</guid>", it)
        res["feed_items"].append({"title": title.group(1).strip() if title else None, "link": link.group(1).strip() if link else None,
                                  "enclosure": enc.group(1) if enc else None, "guid": guid.group(1) if guid else None,
                                  "raw_head": it[:600]})
    link = res["feed_items"][0]["link"] if res["feed_items"] else None
    if link:
        r = s.get(link, timeout=30, allow_redirects=True)
        res["page"] = {"status": r.status_code, "final_url": r.url, "bytes": len(r.text), "outline": outline(r.text)}
    # the episode listing page, in case the feed link is not the episode page
    r2 = s.get("https://www.bbc.co.uk/learningenglish/english/features/6-minute-english", timeout=30)
    res["listing"] = {"status": r2.status_code, "links": sorted(set(re.findall(r'href="(/learningenglish/english/features/6-minute-english[^"]*)"', r2.text)))[:12]}
    Path("tools/probe_result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    sys.exit(main())
