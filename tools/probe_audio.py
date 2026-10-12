"""Probe 7: does the browser's clock for the BBC file match the pipeline's (ffmpeg) clock?
- MP3 structure: ID3 size, Xing/Info header, CBR/VBR, frame-count duration vs ffmpeg duration
- Chromium: <audio> duration for the blob, and the whole-file Web Audio decode cross-correlated against
  ffmpeg's decode (an offset here would shift every highlight by that amount)."""
import asyncio, json, struct, subprocess, sys, time
from pathlib import Path

import numpy as np
import requests

EP = "docs/data/episodes/bbc-6-minute-english-2026-10-08-are-people-drinking-less-alcohol.json"
BITRATES = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320], 2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
SR = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def mp3_info(b: bytes) -> dict:
    pos = 0; id3 = 0
    if b[:3] == b"ID3":
        id3 = 10 + ((b[6] & 0x7f) << 21 | (b[7] & 0x7f) << 14 | (b[8] & 0x7f) << 7 | (b[9] & 0x7f)) + (10 if b[5] & 0x10 else 0)
        pos = id3
    frames = 0; t = 0.0; brs = {}; xing = None; first = None
    while pos + 4 <= len(b):
        if b[pos] != 0xff or (b[pos + 1] & 0xe0) != 0xe0:
            pos += 1; continue
        b1, b2 = b[pos + 1], b[pos + 2]
        ver, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
        if ver == 1 or layer != 1:
            pos += 1; continue
        br = BITRATES[1 if ver == 3 else 2][b2 >> 4]; sr = SR.get(ver, [0, 0, 0])[(b2 >> 2) & 3]; pad = (b2 >> 1) & 1
        if not br or not sr:
            pos += 1; continue
        ln = (144000 * br // sr if ver == 3 else 72000 * br // sr) + pad
        if frames == 0:
            first = {"ver": ver, "br": br, "sr": sr, "mode": (b[pos + 3] >> 6) & 3}
            body = b[pos + 4: pos + ln]
            for tag in (b"Xing", b"Info", b"VBRI"):
                i = body.find(tag)
                if i >= 0:
                    xing = {"tag": tag.decode(), "at": i}
                    lame = body.find(b"LAME"); lavc = body.find(b"Lavc")
                    if lame >= 0 or lavc >= 0:
                        enc = lame if lame >= 0 else lavc
                        try:
                            dp = body[enc + 21: enc + 24]
                            xing["enc_delay"], xing["enc_padding"] = (dp[0] << 4) | (dp[1] >> 4), ((dp[1] & 0xf) << 8) | dp[2]
                            xing["encoder"] = body[enc: enc + 9].decode("latin1")
                        except Exception:  # noqa: BLE001
                            pass
        brs[br] = brs.get(br, 0) + 1
        frames += 1; t += (1152 if ver == 3 else 576) / sr; pos += ln
    return {"id3_bytes": id3, "first_frame": first, "xing": xing, "frames": frames, "frame_duration": round(t, 3),
            "bitrates": brs, "vbr": len(brs) > 1, "naive_duration": round((len(b) - id3) * 8 / (first["br"] * 1000), 3) if first else None, "size": len(b)}


def ffmpeg_pcm(path, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def envelope(pcm, sr, hop=0.01):
    n = int(sr * hop); m = len(pcm) // n
    return np.sqrt((pcm[: m * n].reshape(m, n) ** 2).mean(axis=1))


async def browser(path: Path) -> dict:
    from playwright.async_api import async_playwright
    import http.server, threading, functools
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(path.parent))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8799), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        await page.goto("http://127.0.0.1:8799/")
        res = await page.evaluate("""async (name) => {
            const r = await fetch(name); const buf = await r.arrayBuffer();
            const blob = new Blob([buf], {type: 'audio/mpeg'}); const url = URL.createObjectURL(blob);
            const a = new Audio(); a.src = url;
            const dur = await new Promise(res => { a.addEventListener('loadedmetadata', () => res(a.duration)); a.addEventListener('error', () => res(-1)); });
            // seek accuracy: ask for 100 s, read back
            a.currentTime = 100; await new Promise(r => a.addEventListener('seeked', r, {once: true})); const seeked = a.currentTime;
            const ctx = new OfflineAudioContext(1, 1, 16000); const ab = await ctx.decodeAudioData(buf.slice(0));
            const pcm = ab.getChannelData(0); const hop = 160; const m = Math.floor(pcm.length / hop); const env = new Array(m);
            for (let i = 0; i < m; i++) { let s = 0; for (let j = 0; j < hop; j++) { const v = pcm[i * hop + j]; s += v * v; } env[i] = Math.sqrt(s / hop); }
            return { audio_duration: dur, seeked, decoded_samples: pcm.length, decoded_sr: ab.sampleRate, env };
        }""", path.name)
        await b.close()
    srv.shutdown()
    return res


def main():
    doc = json.loads(Path(EP).read_text())
    s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 podcast-study probe"
    r = s.get(doc["audio_url"], timeout=120)
    hdr = {k: r.headers.get(k) for k in ("content-type", "content-length", "accept-ranges", "access-control-allow-origin", "cache-control", "etag", "last-modified", "server")}
    b = r.content
    out = {"probe": 7, "headers": hdr, "mp3": mp3_info(b)}
    path = Path("probe_dir"); path.mkdir(exist_ok=True); f = path / "a.mp3"; f.write_bytes(b)
    pcm = ffmpeg_pcm(f); out["ffmpeg_duration"] = round(len(pcm) / 16000, 3)
    env_ff = envelope(pcm, 16000)
    out["ffmpeg_first_sound_s"] = round(float(np.argmax(env_ff > 0.01)) * 0.01, 2)
    try:
        br = asyncio.run(browser(f))
        env_b = np.array(br.pop("env"), dtype=np.float64)
        out["browser"] = br
        out["browser_first_sound_s"] = round(float(np.argmax(env_b > 0.01)) * 0.01, 2)
        # cross-correlate the first 60 s of envelopes (10 ms hops) over ±5 s
        n = min(6000, len(env_ff), len(env_b)); a = env_ff[:n] - env_ff[:n].mean(); c = env_b[:n] - env_b[:n].mean()
        best = None
        for lag in range(-500, 501):
            if lag >= 0: x, y = a[lag:], c[: n - lag]
            else: x, y = a[: n + lag], c[-lag:]
            v = float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))
            if best is None or v > best[1]: best = (lag, v)
        out["browser_vs_ffmpeg_offset_s"] = round(best[0] * 0.01, 2); out["corr"] = round(best[1], 3)
    except Exception as e:  # noqa: BLE001
        out["browser_error"] = str(e)[:300]
    Path("tools/probe_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
