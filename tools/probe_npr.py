"""Probe NPR podcasts (The Indicator, Up First): feed timing + whether npr.org transcripts exist (run on Actions)."""
import json, re, time
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests

UA = {"User-Agent": "Mozilla/5.0 (podcast-study probe; +https://myfan729.github.io/podcast-study/)"}
KST = timezone(timedelta(hours=9))
out = {}
s = requests.Session()
Path("tools/npr_samples").mkdir(exist_ok=True)
for name in ["The Indicator from Planet Money", "Up First NPR"]:
    hit = s.get("https://itunes.apple.com/search", params={"term": name, "entity": "podcast", "limit": 3}, headers=UA, timeout=20).json()["results"][0]
    feed = hit["feedUrl"]
    r = s.get(feed, headers=UA, timeout=60); root = ET.fromstring(r.content)
    items = []
    for i, it in enumerate(root.find("channel").findall("item")[:10]):
        d = parsedate_to_datetime(it.findtext("pubDate"))
        link = it.findtext("link") or ""
        enc = it.find("enclosure")
        rec = {"title": it.findtext("title"), "pub_kst": d.astimezone(KST).strftime("%a %m-%d %H:%M"),
               "dur": it.findtext("{http://www.itunes.com/dtds/podcast-1.0.dtd}duration"), "link": link,
               "guid": it.findtext("guid"), "enclosure": enc.get("url")[:160] if enc is not None else None,
               "tags": sorted({c.tag.split('}')[-1] for c in it})}
        m = re.search(r"/(\d{4}/\d{2}/\d{2}/)?(\d{9,})", link) or re.search(r"(\d{9,})", it.findtext("guid") or "")
        sid = m.group(m.lastindex) if m else None
        rec["story_id"] = sid
        if sid:
            tu = f"https://www.npr.org/transcripts/{sid}"
            try:
                tr = s.get(tu, headers=UA, timeout=30)
                rec["transcript_status"] = tr.status_code; rec["transcript_url"] = tr.url
                txt = tr.text
                paras = re.findall(r"<p>(.*?)</p>", txt, flags=re.S)
                rec["transcript_p_count"] = len(paras)
                rec["transcript_first"] = [re.sub(r"<[^>]+>", "", p)[:160] for p in paras[:6]]
                rec["has_transcript_div"] = 'class="transcript' in txt
                if i < 2:
                    Path(f"tools/npr_samples/{name.split()[0+1 if name.startswith('The') else 0].lower()}_{i}.html").write_text(txt)
            except Exception as e:
                rec["transcript_error"] = str(e)[:200]
        items.append(rec); time.sleep(1)
    out[name] = {"feed": feed, "items": items}
    print(json.dumps(out[name], ensure_ascii=False, indent=1)[:4000])
Path("tools/probe_npr.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
