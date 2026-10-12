"""Second probe: (1) do the tracking redirectors (podtrac, swap.fm) answer CORS so a browser can read the
stream through the whole chain? (2) does a Triton DAI session URL replay the same stitched file later?
(3) what does Omny's WaveformUrl contain? Writes tools/probe_result.json."""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import requests

UA = {"User-Agent": "podcast-study-probe/1.0", "Origin": "https://myfan729.github.io"}
ORG = "e73c998e-6e60-432f-8610-ae210140c5b1"
CLIP = "947bb858-7725-41b9-a0bc-b4de014c6b52"
ENCLOSURE = ("https://podtrac.com/pts/redirect.mp3/tracking.swap.fm/track/UVBrz8bN8aM2Xe47PEPu/traffic.omny.fm/d/clips/"
             f"{ORG}/825d4e29-b616-46f4-afd7-ae2b0013005c/{CLIP}/audio.mp3?utm_source=Podcast&in_playlist=8b1dd624-a026-43e9-8b57-ae2b00130066")
OLD_SESSION = ("https://26833.mc.tritondigital.com:443/OMNY_THEBIGTAKE_PODCAST_P/media-session/fd357064-25fc-4a4b-afe5-f0d8119efa12/d/clips/"
               f"{ORG}/825d4e29-b616-46f4-afd7-ae2b0013005c/{CLIP}/audio.mp3?utm_source=Podcast&in_playlist=8b1dd624-a026-43e9-8b57-ae2b00130066")


def mp3_duration(data: bytes):
    try:
        from mutagen.mp3 import MP3
        return float(MP3(io.BytesIO(data)).info.length)
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    s = requests.Session()
    out: dict = {}
    # (1) each hop's status + CORS headers, as a browser (with Origin) would see them
    hops = []
    url = ENCLOSURE
    for _ in range(8):
        r = s.get(url, headers=UA, allow_redirects=False, stream=True, timeout=30)
        hops.append({"url": url[:110], "status": r.status_code, "location": (r.headers.get("Location") or "")[:110],
                     "cors": {k: v for k, v in r.headers.items() if k.lower().startswith("access-control")}})
        nxt = r.headers.get("Location"); r.close()
        if not nxt or r.status_code not in (301, 302, 303, 307, 308):
            break
        url = requests.compat.urljoin(url, nxt)
    out["hops"] = hops
    out["final_url"] = url
    # (2) replay an old session URL and compare to a fresh session
    def dl(u):
        r = s.get(u, headers=UA, timeout=90, allow_redirects=True)
        return {"status": r.status_code, "final": r.url[:120], "bytes": len(r.content), "duration": mp3_duration(r.content),
                "head": r.content[:64].hex()}
    out["old_session_replay"] = dl(OLD_SESSION)
    time.sleep(2)
    out["fresh_session_1"] = dl(url)
    time.sleep(2)
    out["fresh_session_2"] = dl(url)
    # (3) waveform url
    try:
        clip = s.get(f"https://api.omny.fm/orgs/{ORG}/clips/{CLIP}", timeout=30).json()
        wurl = clip.get("WaveformUrl")
        w = s.get(wurl, timeout=30)
        body = w.content
        info = {"url": wurl, "status": w.status_code, "content_type": w.headers.get("Content-Type"), "bytes": len(body)}
        if "json" in (w.headers.get("Content-Type") or "") or body[:1] in (b"{", b"["):
            j = json.loads(body)
            info["json_keys"] = list(j.keys())[:10] if isinstance(j, dict) else f"list[{len(j)}]"
            if isinstance(j, dict):
                for k, v in j.items():
                    if isinstance(v, list):
                        info[f"len_{k}"] = len(v); info[f"sample_{k}"] = v[:12]
        else:
            info["head"] = body[:16].hex()
        out["waveform"] = info
    except Exception as e:  # noqa: BLE001
        out["waveform"] = {"error": str(e)[:200]}
    Path("tools/probe_result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1)[:3000])


if __name__ == "__main__":
    sys.exit(main())
