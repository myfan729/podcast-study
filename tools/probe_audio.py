"""Probe 4: BBC Learning English page download links — CORS? ad-free? duration?"""
import io, json, re, sys
from pathlib import Path
import requests

UA = {"User-Agent": "Mozilla/5.0 (podcast-study probe)", "Origin": "https://myfan729.github.io"}
PAGE = "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2026/ep-261008"
FEED_ENCLOSURE = "http://open.live.bbc.co.uk/mediaselector/6/redir/version/2.0/mediaset/audio-nondrm-download-rss-low/proto/http/vpid/p0pfllv6.mp3"


def dur(data):
    try:
        from mutagen.mp3 import MP3
        return float(MP3(io.BytesIO(data)).info.length)
    except Exception:  # noqa: BLE001
        return None


def main():
    s = requests.Session()
    res = {}
    html = s.get(PAGE, headers=UA, timeout=30).text
    links = sorted(set(re.findall(r'href="([^"]+\.(?:mp3|pdf))"', html)))
    res["page_media_links"] = links
    for i, url in enumerate([u for u in links if u.endswith(".mp3")][:3] + [FEED_ENCLOSURE, FEED_ENCLOSURE.replace("http://", "https://")]):
        try:
            r = s.get(url, headers=UA, timeout=90, allow_redirects=True)
            res[f"audio_{i}"] = {"url": url[:120], "status": r.status_code, "final": r.url[:120], "bytes": len(r.content),
                                 "duration": dur(r.content), "cors": {k: v for k, v in r.headers.items() if k.lower().startswith("access-control")},
                                 "hops": [(h.status_code, h.url[:80], {k: v for k, v in h.headers.items() if k.lower().startswith("access-control")}) for h in r.history]}
        except Exception as e:  # noqa: BLE001
            res[f"audio_{i}"] = {"url": url[:120], "error": str(e)[:200]}
    Path("tools/probe_result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1)[:3000])


if __name__ == "__main__":
    sys.exit(main())
