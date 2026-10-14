"""Probe for the morning/evening schedule (run on GitHub Actions; the dev box can't reach the feeds).

- publish times (UTC), durations, transcript tags of the latest items of the candidate shows
- Stuff You Should Know: how often "Short Stuff" comes out, how long it is, whether it has transcripts
- Think Fast, Talk Smart: does the back catalog carry transcripts (and are they downloadable)?
Output: tools/probe_slots.json
"""
import json, re, statistics
import xml.etree.ElementTree as ET
from collections import Counter
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (podcast-study probe; +https://myfan729.github.io/podcast-study/)"}
NS = {"podcast": "https://podcastindex.org/namespace/1.0", "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
OMNY = "https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/"
FEEDS = {
    "daybreak-us": OMNY + "d15648c4-cee0-4e99-a5ca-af80014d921d/65ce2954-d8a8-4c66-9f42-af80014d923e/podcast.rss",
    "big-take": OMNY + "825d4e29-b616-46f4-afd7-ae2b0013005c/8b1dd624-a026-43e9-8b57-ae2b00130066/podcast.rss",
    "sysk": OMNY + "a91018a4-ea4f-4130-bf55-ae270180c327/44710ecc-10bb-48d1-93c7-ae270180c33e/podcast.rss",
    "tfts": "https://feeds.transistor.fm/think-fast-talk-smart-communication-techniques",
    "everybodys-business": OMNY + "f541f9b4-77cb-45aa-bf94-b1d300e5d357/1d448cb7-e0fc-45b8-b51f-b1d300e623a7/podcast.rss",
    "zero": OMNY + "37c6caa7-d377-4c08-b479-af9d012ed5ad/a7faefb0-28ec-4b1d-85f3-af9d012ed5c9/podcast.rss",
    "trumponomics": OMNY + "84f3c095-964f-4994-9d24-ae2b00130029/c9553948-bc39-4871-8989-ae2b00130032/podcast.rss",
}


def duration(raw):
    if not raw:
        return None
    raw = raw.strip()
    if re.fullmatch(r"\d+", raw):
        return int(raw)
    s = 0
    for p in [int(p) for p in raw.split(":") if p.isdigit()]:
        s = s * 60 + p
    return s or None


def items(session, url):
    r = session.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.find("channel").findall("item"):
        try:
            d = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:  # noqa: BLE001
            d = None
        ts = it.findall("podcast:transcript", NS)
        out.append({"title": (it.findtext("title") or "").strip(), "pub": d.isoformat() if d else None,
                    "wd": d.strftime("%a") if d else None,
                    "min": round((duration(it.findtext("itunes:duration", namespaces=NS)) or 0) / 60, 1),
                    "tr": sorted({t.get("type") for t in ts}), "tr_url": ts[0].get("url") if ts else None,
                    "type": it.findtext("itunes:episodeType", namespaces=NS)})
    return out


def main():
    s = requests.Session()
    out = {}
    for name, url in FEEDS.items():
        try:
            its = items(s, url)
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": str(e)[:200]}
            continue
        rec = {"total": len(its), "latest": [{k: i[k] for k in ("pub", "wd", "min", "tr", "title", "type")} for i in its[:14]]}
        by_year = Counter((i["pub"] or "????")[:4] for i in its)
        tr_year = Counter((i["pub"] or "????")[:4] for i in its if i["tr"])
        rec["transcripts_by_year"] = {y: f"{tr_year.get(y, 0)}/{n}" for y, n in sorted(by_year.items())}
        if name == "sysk":
            ss = [i for i in its if re.search(r"short stuff", i["title"], re.I)]
            rec["short_stuff"] = {"count": len(ss), "with_transcript": sum(1 for i in ss if i["tr"]),
                                  "median_min": statistics.median([i["min"] for i in ss[:30] if i["min"]]) if ss else None,
                                  "latest": [{k: i[k] for k in ("pub", "wd", "min", "tr", "title")} for i in ss[:16]]}
            short = [i for i in its[:60] if i["min"] and i["min"] <= 40]
            rec["under_40_latest60"] = [{k: i[k] for k in ("pub", "wd", "min", "tr", "title")} for i in short]
            rec["title_kinds"] = Counter(re.sub(r":.*$", "", i["title"])[:24] if ":" in i["title"][:30] else "(plain)" for i in its[:120]).most_common(12)
        if name == "tfts":
            mins = [i["min"] for i in its if i["min"]]
            rec["median_min_all"] = statistics.median(mins) if mins else None
            with_tr = [i for i in its if i["tr"]]
            rec["oldest_with_transcript"] = {k: with_tr[-1][k] for k in ("pub", "title", "min")} if with_tr else None
            # are old transcripts actually downloadable?
            checks = []
            for i in with_tr[len(with_tr) // 2::max(1, len(with_tr) // 6)][:4] + with_tr[-2:]:
                try:
                    r = s.get(i["tr_url"], headers=UA, timeout=30)
                    checks.append({"title": i["title"][:60], "pub": i["pub"][:10], "status": r.status_code, "bytes": len(r.content),
                                   "head": r.text[:120]})
                except Exception as e:  # noqa: BLE001
                    checks.append({"title": i["title"][:60], "error": str(e)[:120]})
            rec["old_transcript_checks"] = checks
            rec["sample_titles_by_year"] = {y: [i["title"][:70] for i in its if (i["pub"] or "")[:4] == y][:5] for y in sorted(by_year)}
            rec["minutes_by_year"] = {y: statistics.median([i["min"] for i in its if (i["pub"] or "")[:4] == y and i["min"]] or [0]) for y in sorted(by_year)}
        out[name] = rec
        print(name, json.dumps({k: v for k, v in rec.items() if k != "latest"}, ensure_ascii=False)[:1500], flush=True)
    Path("tools/probe_slots.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
