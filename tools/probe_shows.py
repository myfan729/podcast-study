"""Probe: which candidate podcasts can this pipeline take on today?

For each show name: find the RSS feed (Apple Podcasts lookup), read the latest items and report
- <podcast:transcript> tags (type, how many of the latest items have one) → fully automatic
- typical episode length, publishing frequency, audio host (dynamic ad insertion likely?)
Output: tools/probe_shows.json
"""
import json, re, statistics, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

SHOWS = [
    # business / economics / news
    "Odd Lots", "Money Stuff: The Podcast", "Bloomberg Daybreak: US Edition", "Everybody's Business Bloomberg",
    "Big Take DC", "Zero Akshat Rathi", "Elon, Inc.", "Trumponomics Bloomberg", "Big Take", "Big Take Asia",
    "The Indicator from Planet Money", "Planet Money", "Up First", "Short Wave", "Marketplace Morning Report",
    "Marketplace Tech", "The Journal. WSJ", "WSJ What's News", "FT News Briefing", "The Economics Show Soumaya Keynes",
    "Axios Today", "Morning Brew Daily", "Squawk Pod", "The Intelligence Economist", "Global News Podcast BBC",
    "Today, Explained", "CNN 5 Things", "The Daily New York Times", "Reuters World News",
    # work / communication / ideas
    "HBR IdeaCast", "Women at Work HBR", "Coaching Real Leaders", "The McKinsey Podcast", "WorkLife with Adam Grant",
    "ReThinking with Adam Grant", "TED Talks Daily", "TED Business", "No Stupid Questions", "Freakonomics Radio",
    "Hidden Brain", "Speaking of Psychology", "The Science of Happiness", "Unexplainable", "Stuff You Should Know",
    "Think Fast, Talk Smart", "Ten Percent Happier", "Short History Of", "Making Sense of Cents",
]
UA = {"User-Agent": "Mozilla/5.0 (podcast-study probe; +https://myfan729.github.io/podcast-study/)"}
NS = {"podcast": "https://podcastindex.org/namespace/1.0", "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}


def duration(raw):
    if not raw:
        return None
    raw = raw.strip()
    if re.fullmatch(r"\d+", raw):
        return int(raw)
    parts = [int(p) for p in raw.split(":") if p.isdigit()]
    s = 0
    for p in parts:
        s = s * 60 + p
    return s or None


def lookup(session, term):
    r = session.get("https://itunes.apple.com/search", params={"term": term, "entity": "podcast", "limit": 3}, headers=UA, timeout=20)
    r.raise_for_status()
    res = r.json().get("results") or []
    return res[0] if res else None


def probe_feed(session, url):
    r = session.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ch = root.find("channel")
    items = ch.findall("item")[:10]
    trans, types, durs, dates, hosts, sample = 0, {}, [], [], {}, None
    for it in items:
        ts = it.findall("podcast:transcript", NS)
        if ts:
            trans += 1
            for t in ts:
                types[t.get("type")] = types.get(t.get("type"), 0) + 1
                sample = sample or t.get("url")
        d = duration(it.findtext("itunes:duration", namespaces=NS))
        if d:
            durs.append(d)
        try:
            dates.append(parsedate_to_datetime(it.findtext("pubDate")))
        except Exception:  # noqa: BLE001
            pass
        enc = it.find("enclosure")
        if enc is not None:
            host = re.sub(r"^https?://([^/]+)/.*$", r"\1", enc.get("url") or "")
            hosts[host] = hosts.get(host, 0) + 1
    per_week = None
    if len(dates) >= 3:
        span = (max(dates) - min(dates)).total_seconds() / 86400
        per_week = round((len(dates) - 1) / span * 7, 1) if span > 0 else None
    return {"items": len(items), "with_transcript": trans, "types": types, "sample": sample,
            "median_min": round(statistics.median(durs) / 60, 1) if durs else None,
            "per_week": per_week, "hosts": hosts,
            "latest": max(dates).astimezone(timezone.utc).isoformat()[:10] if dates else None}


def main():
    s = requests.Session()
    out = {}
    for name in SHOWS:
        rec = {"query": name}
        try:
            hit = lookup(s, name)
            if not hit:
                rec["error"] = "not found"
            else:
                rec.update({"title": hit.get("collectionName"), "artist": hit.get("artistName"), "feed": hit.get("feedUrl")})
                if rec["feed"]:
                    rec.update(probe_feed(s, rec["feed"]))
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        out[name] = rec
        print(json.dumps(rec, ensure_ascii=False)[:300], flush=True)
        time.sleep(3.2)                       # Apple's search API allows ~20 calls a minute
    Path("tools/probe_shows.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
