"""Probe BBC Learning English + Australian (ABC/SBS) podcasts: feeds, episode pages, where transcripts live.
Saves raw HTML samples to tools/probe_samples/ and a summary to tools/probe_newshows.json (run on Actions)."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, ".")
from pipeline.feeds import parse_feed
from pipeline.util import http_get_text, http_session

s = http_session()
OUT = Path("tools/probe_samples"); OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (podcast-study probe)"}

def itunes(term):
    r = s.get("https://itunes.apple.com/search", params={"term": term, "entity": "podcast", "limit": 5}, headers=UA, timeout=30).json()
    return [{"name": x.get("collectionName"), "artist": x.get("artistName"), "feed": x.get("feedUrl")} for x in r.get("results", [])]

BBC = {"6 Minute English": "p02pc9tn", "Learning English from the News": "p05hw4bq", "Learning English Conversations": "p02pc9zn",
       "Learning English Vocabulary": "p02pc9xz", "Learning English Grammar": "p02pc9wq", "Learning English Stories": "p02pc9s1"}
LE_INDEX = ["6-minute-english", "learning-english-from-the-news", "news-review", "the-english-we-speak", "6-minute-vocabulary",
            "6-minute-grammar", "learning-english-conversations", "english-in-a-minute", "real-easy-english", "learning-english-stories"]
AU_TERMS = ["ABC News Daily", "ABC Business Daily", "AM ABC Radio National", "The Science Show ABC", "All in the Mind ABC",
            "Rear Vision ABC", "Health Report ABC", "Science Friction ABC", "SBS Learn English", "Words We Use SBS Learn English",
            "Conversations ABC", "Late Night Live ABC", "The Signal ABC", "Background Briefing ABC"]
out = {"bbc": {}, "le_index": {}, "au": {}}

def page_info(url, tag):
    try:
        html = http_get_text(s, url)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": str(e)[:200]}
    (OUT / f"{tag}.html").write_text(html[:600000])
    low = html.lower()
    return {"url": url, "len": len(html), "transcript_word": low.count("transcript"),
            "classes": sorted(set(re.findall(r'(?:class|id)="([^"]*transcript[^"]*)"', html, re.I)))[:8],
            "jsonld": "@type" in html and "transcript" in low}

for name, pid in BBC.items():
    feed = f"https://podcasts.files.bbci.co.uk/{pid}.rss"
    try:
        _, eps = parse_feed(http_get_text(s, feed))
        out["bbc"][name] = {"feed": feed, "n": len(eps), "eps": [{"title": e.title, "pub": e.published_iso, "link": e.link,
                            "dur": e.duration_sec, "tr": bool(e.best_transcript)} for e in eps[:4]]}
    except Exception as e:  # noqa: BLE001
        out["bbc"][name] = {"feed": feed, "error": str(e)[:200]}
for slug in LE_INDEX:
    url = f"https://www.bbc.co.uk/learningenglish/english/features/{slug}"
    try:
        html = http_get_text(s, url)
        links = sorted(set(re.findall(r'/learningenglish/english/features/[a-z0-9-]+(?:_\d{4})?/[a-z0-9-]+', html)))
        out["le_index"][slug] = {"ok": True, "links": links[:12], "n": len(links)}
        if links:
            ep = "https://www.bbc.co.uk" + links[-1]
            out["le_index"][slug]["sample"] = page_info(ep, f"bbc-{slug}")
    except Exception as e:  # noqa: BLE001
        out["le_index"][slug] = {"ok": False, "error": str(e)[:150]}
for term in AU_TERMS:
    try:
        hits = itunes(term)
    except Exception as e:  # noqa: BLE001
        out["au"][term] = {"error": str(e)[:150]}; continue
    rec = {"hits": hits[:3]}
    feed = next((h["feed"] for h in hits if h["feed"]), None)
    if feed:
        try:
            _, eps = parse_feed(http_get_text(s, feed))
            rec["feed"] = feed
            rec["eps"] = [{"title": e.title, "pub": e.published_iso, "link": e.link, "dur": e.duration_sec, "tr": bool(e.best_transcript)} for e in eps[:3]]
            if eps and eps[0].link:
                slug = re.sub(r"[^a-z0-9]+", "-", term.lower())[:30]
                rec["page"] = page_info(eps[0].link, f"au-{slug}")
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
    out["au"][term] = rec
Path("tools/probe_newshows.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("done")
