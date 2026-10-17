"""Find podcasts whose episodes the pipeline can turn into study packs automatically (run on GitHub Actions).

For each candidate name: Apple Podcasts lookup → RSS feed → latest 10 items:
- RSS path: <podcast:transcript> with VTT/SRT/JSON on recent items
- NPR path: feeds.npr.org feeds → npr.org/transcripts/<story id> has the text (checked on an item ≥2 days old)
Also: median length, episodes/week, last publish date, language.
Output: tools/catalog/probe_catalog.json
"""
import json, re, statistics, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

NS = {"podcast": "https://podcastindex.org/namespace/1.0", "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
UA = {"User-Agent": "Mozilla/5.0 (podcast-study catalog probe; +https://myfan729.github.io/podcast-study/)"}
CANDIDATES = [l.strip() for l in Path(__file__).with_name("candidates.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
OUT = Path(__file__).with_name("probe_catalog.json")


def dur(raw):
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    s = 0
    for p in raw.split(":"):
        if p.isdigit():
            s = s * 60 + int(p)
    return s or None


def npr_check(s, link):
    m = re.search(r"npr\.org/\d{4}/\d{2}/\d{2}/([A-Za-z0-9-]+?)/", link or "")
    if not m:
        return None
    r = s.get(f"https://www.npr.org/transcripts/{m.group(1)}", headers=UA, timeout=30)
    if r.status_code != 200 or 'class="transcript' not in r.text:
        return False
    words = len(re.sub(r"<[^>]+>", " ", r.text.split('class="transcript', 1)[1][:200000]).split())
    return words > 600


def main():
    s = requests.Session()
    out = json.loads(OUT.read_text()) if OUT.exists() and "--fresh" not in sys.argv else {}
    now = datetime.now(timezone.utc)
    for name in CANDIDATES:
        if name in out and "error" not in out[name]:
            continue
        rec = {"query": name}
        try:
            res = s.get("https://itunes.apple.com/search", params={"term": name, "entity": "podcast", "limit": 3}, headers=UA, timeout=20).json().get("results") or []
            if not res:
                rec["error"] = "not found"; out[name] = rec; continue
            hit = res[0]
            rec.update(title=hit.get("collectionName"), artist=hit.get("artistName"), feed=hit.get("feedUrl"),
                       genre=hit.get("primaryGenreName"), image=hit.get("artworkUrl600"))
            r = s.get(rec["feed"], headers=UA, timeout=40)
            r.raise_for_status()
            ch = ET.fromstring(r.content).find("channel")
            rec["language"] = (ch.findtext("language") or "").lower()
            items = ch.findall("item")[:10]
            durs, dates, tr, types, links = [], [], 0, {}, []
            for it in items:
                ts = it.findall("podcast:transcript", NS)
                good = [t for t in ts if re.search(r"vtt|srt|subrip|json", (t.get("type") or "") + (t.get("url") or ""), re.I)]
                if good:
                    tr += 1
                    for t in good:
                        types[t.get("type")] = types.get(t.get("type"), 0) + 1
                d = dur(it.findtext("itunes:duration", namespaces=NS))
                if d:
                    durs.append(d)
                try:
                    dt = parsedate_to_datetime(it.findtext("pubDate"))
                    dates.append(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
                except Exception:  # noqa: BLE001
                    pass
                links.append(it.findtext("link") or "")
            rec.update(items=len(items), with_transcript=tr, types=types,
                       median_min=round(statistics.median(durs) / 60, 1) if durs else None,
                       latest=max(dates).date().isoformat() if dates else None,
                       days_since=(now - max(dates)).days if dates else None)
            if len(dates) >= 3:
                span = (max(dates) - min(dates)).total_seconds() / 86400
                rec["per_week"] = round((len(dates) - 1) / span * 7, 1) if span > 0 else None
            if "feeds.npr.org" in (rec["feed"] or ""):
                # an item at least 2 days old (transcripts come later)
                old = [(d, l) for d, l in zip(dates, links) if (now - d).days >= 2]
                rec["npr_transcript"] = npr_check(s, old[0][1]) if old else None
            path = "rss" if tr >= 7 else ("npr" if rec.get("npr_transcript") else None)
            rec["path"] = path
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        out[name] = rec
        print(json.dumps({k: rec.get(k) for k in ("query", "title", "path", "with_transcript", "median_min", "per_week", "days_since", "error")}, ensure_ascii=False), flush=True)
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        time.sleep(3.1)        # Apple search allows ~20 calls a minute


if __name__ == "__main__":
    main()
