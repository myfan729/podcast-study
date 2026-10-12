"""Probe candidate audio URLs for an episode: final URL, size and real duration.

Used once to find out which delivery URL (if any) serves the episode WITHOUT dynamically
inserted ads, so transcript timestamps line up. Writes tools/probe_result.json.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import requests

ORG = "e73c998e-6e60-432f-8610-ae210140c5b1"
PROG = "825d4e29-b616-46f4-afd7-ae2b0013005c"
CLIP = "947bb858-7725-41b9-a0bc-b4de014c6b52"  # Big Take: Inside Jane Street (content 987.5 s)

CANDIDATES = {
    "A_feed_enclosure": "https://podtrac.com/pts/redirect.mp3/tracking.swap.fm/track/UVBrz8bN8aM2Xe47PEPu/traffic.omny.fm/d/clips/%s/%s/%s/audio.mp3?utm_source=Podcast&in_playlist=8b1dd624-a026-43e9-8b57-ae2b00130066" % (ORG, PROG, CLIP),
    "F_tfts_transistor": "https://feeds.transistor.fm/think-fast-talk-smart-communication-techniques",  # resolved below to the latest enclosure
}


def mp3_duration(data: bytes) -> float | None:
    try:
        from mutagen.mp3 import MP3
        return float(MP3(io.BytesIO(data)).info.length)
    except Exception as e:  # noqa: BLE001
        return None


def fetch(session: requests.Session, url: str, max_bytes: int = 60_000_000) -> dict:
    t0 = time.time()
    out: dict = {"url": url}
    try:
        r = session.get(url, timeout=60, allow_redirects=True, stream=True,
                        headers={"User-Agent": "podcast-study-probe/1.0"})
        out.update(status=r.status_code, final_url=r.url, content_type=r.headers.get("Content-Type"),
                   content_length=r.headers.get("Content-Length"), hops=[h.url for h in r.history],
                   cors={k: v for k, v in r.headers.items() if k.lower().startswith("access-control")},
                   accept_ranges=r.headers.get("Accept-Ranges"))
        # a browser sends an Origin header on cross-origin fetches; some CDNs only answer CORS then
        try:
            pre = session.get(r.url, timeout=30, stream=True, headers={"User-Agent": "podcast-study-probe/1.0", "Origin": "https://myfan729.github.io", "Range": "bytes=0-1023"})
            out["cors_with_origin"] = {k: v for k, v in pre.headers.items() if k.lower().startswith("access-control")}
            out["range_status"] = pre.status_code
            pre.close()
        except Exception as e:  # noqa: BLE001
            out["cors_with_origin"] = {"error": str(e)[:120]}
        buf = io.BytesIO()
        for chunk in r.iter_content(1 << 16):
            buf.write(chunk)
            if buf.tell() > max_bytes:
                break
        data = buf.getvalue()
        out["bytes_downloaded"] = len(data)
        out["duration_sec"] = mp3_duration(data)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:300]
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main() -> None:
    s = requests.Session()
    results = {}
    # Resolve TFTS latest enclosure + its transcript end time for comparison
    try:
        import xml.etree.ElementTree as ET
        xml = s.get(CANDIDATES.pop("F_tfts_transistor"), timeout=30).text
        root = ET.fromstring(xml)
        item = root.find("channel/item")
        enc = item.find("enclosure").get("url")
        dur = next((c.text for c in item if c.tag.endswith("duration")), None)
        tr = next((c.get("url") for c in item if c.tag.endswith("transcript")), None)
        CANDIDATES["F_tfts_enclosure"] = enc
        results["F_tfts_meta"] = {"itunes_duration": dur, "transcript": tr, "title": item.find("title").text}
    except Exception as e:  # noqa: BLE001
        results["F_tfts_meta"] = {"error": str(e)[:200]}
    for name, url in CANDIDATES.items():
        results[name] = fetch(s, url)
        print(name, json.dumps(results[name])[:300], flush=True)
    Path("tools/probe_result.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    sys.exit(main())
