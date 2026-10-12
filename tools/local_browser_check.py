"""Local browser check of the player's sync logic using the synthetic demo audio (no network needed).

Builds a throwaway copy of docs/ with a "fixed" (ad-free) episode whose cues are on the file's clock, plus
its reference fingerprint, then drives the page in headless Chromium:
  1. fixed file → no alignment needed, status ✓, intro line before the first cue, no ad prompt;
  2. a deliberately late manual tap is snapped back by the fingerprint (±0.1 s);
  3. browsers without 8/16 kHz audio contexts fall back to 48 kHz decode + resampling.
Usage: python tools/local_browser_check.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import fingerprint as F  # noqa: E402
from pipeline.sync import build_fixed  # noqa: E402

PORT = 8771


class _LocalSession:
    """Stands in for requests: 'downloads' the local demo mp3."""
    def __init__(self, src: Path):
        self.src = src

    def get(self, url, **kw):
        src = self.src

        class _R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def raise_for_status(self): pass
            def iter_content(self, n):
                with src.open("rb") as f:
                    while chunk := f.read(n):
                        yield chunk
        return _R()


def make_fixture(dst: Path) -> tuple[str, dict]:
    shutil.copytree(ROOT / "docs", dst, ignore=shutil.ignore_patterns("data"))
    (dst / "data" / "episodes").mkdir(parents=True)
    (dst / "data" / "sync").mkdir(parents=True)
    demo = next((ROOT / "docs" / "data" / "episodes").glob("*airlines*.json"))
    doc = json.loads(demo.read_text())
    mp3 = ROOT / "docs" / "demo" / "airlines-demo.mp3"
    dur = len(F.decode_pcm(mp3, F.SR)) / F.SR
    # the demo file: 12 s pre-roll, content, 9 s mid-roll at content 60 s → express cues on the file's clock
    def to_file(c: float) -> float:
        return c + 12.0 + (9.0 if c >= 60.0 else 0.0)
    for c in doc["transcript"]["cues"]:
        c["s"], c["e"] = round(to_file(c["s"]), 3), round(to_file(c["e"]), 3)
    for s in doc["transcript"]["segments"]:
        s["start"], s["end"] = doc["transcript"]["cues"][s["cue_from"]]["s"], doc["transcript"]["cues"][s["cue_to"]]["e"]
    doc["id"] = "fixed-check"
    doc["demo"] = False
    doc["audio_url"] = doc["audio_url_original"] = "demo/airlines-demo.mp3"
    doc["duration_sec"] = int(round(dur))
    doc["audio_meta"] = {"dai": "none", "fixed": True, "content_duration": round(dur, 3), "ad_markers": [], "source": "asr-align",
                         "alignment": {"version": 2, "ad_free": True, "first_word_runner": 12.0, "runner_duration": round(dur, 3)}}
    (dst / "data" / "episodes" / "fixed-check.json").write_text(json.dumps(doc))
    sync = build_fixed(doc, _LocalSession(mp3))
    (dst / "data" / "sync" / "fixed-check.json").write_text(json.dumps(sync))
    (dst / "data" / "index.json").write_text(json.dumps({"episodes": [], "shows": []}))
    return "fixed-check", doc


async def run(dst: Path, ep_id: str, doc: dict) -> dict:
    from playwright.async_api import async_playwright
    out: dict = {}
    first = doc["transcript"]["cues"][0]["s"]
    target = next(c for c in doc["transcript"]["cues"] if c["s"] > 40)        # a sentence well after the first ref
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for variant in ("normal", "no8k", "pcm"):
            page = await b.new_page(viewport={"width": 390, "height": 844})
            logs, errs = [], []
            page.on("console", lambda m: logs.append(m.text))
            page.on("pageerror", lambda e: errs.append(str(e)))
            if variant == "no8k":   # emulate a browser whose contexts only run at 44.1/48 kHz
                await page.add_init_script("""(() => { const Orig = window.OfflineAudioContext;
                    window.OfflineAudioContext = function (ch, len, sr) { if (sr < 44100) throw new DOMException('rate', 'NotSupportedError'); return new Orig(ch, len, sr); }; })();""")
            await page.goto(f"http://localhost:{PORT}/episode.html?id={ep_id}" + ("&pcm=1" if variant == "pcm" else ""))
            r: dict = {"errors": errs}
            try:
                await page.wait_for_function("document.getElementById('syncBtn').textContent.includes('✓') && !document.getElementById('play').disabled", timeout=60000)
                await page.wait_for_function("!!localStorage.getItem('syncrep:fixed-check')", timeout=60000)
                rep = json.loads(await page.evaluate("localStorage.getItem('syncrep:fixed-check')"))
                r["phase"], r["refs"], r["decode"], r["anchors"] = rep["phase"], rep["report"]["refs"], rep["report"].get("decode"), rep["anchors"]
                r["pcm"] = rep.get("pcm"); r["audio_src"] = await page.evaluate("document.getElementById('audio').src.slice(0, 5)")
                await page.wait_for_function("isFinite(document.getElementById('audio').duration)", timeout=20000)
                r["audio_duration"] = await page.evaluate("document.getElementById('audio').duration")
                # intro line before the first cue, nothing highlighted, no ad prompt
                await page.evaluate("t => { const a = document.getElementById('audio'); a.currentTime = t; a.dispatchEvent(new Event('timeupdate')); }", first - 3)
                r["intro_line"] = await page.evaluate("document.getElementById('nowLine').textContent")
                r["adbar_hidden"] = await page.evaluate("document.getElementById('adbar').hidden")
                # highlight follows the file clock
                await page.evaluate("t => { const a = document.getElementById('audio'); a.currentTime = t; a.dispatchEvent(new Event('timeupdate')); }", target["s"] + 0.3)
                r["active_cue"] = await page.evaluate("document.querySelector('.cue.active') && document.querySelector('.cue.active').textContent")
                r["active_expected"] = target["t"]
                # a late manual tap (2 s after the sentence started) must be snapped back
                await page.keyboard.press("s")
                await page.evaluate("t => { const a = document.getElementById('audio'); a.currentTime = t; }", target["s"] + 2.0)
                await page.click(f".cue[data-i='{target['i']}']")
                await page.wait_for_function("document.getElementById('toast').textContent.includes('보정')", timeout=20000)
                anchors = json.loads(await page.evaluate("localStorage.getItem('sync:fixed-check') || '[]'"))
                r["snap_anchor"] = anchors
                r["snap_offset"] = round(anchors[-1]["a"] - anchors[-1]["c"], 3) if anchors else None
                # diagnostics sheet
                await page.keyboard.press("f")
                await page.click("#adbar button[data-act='info']")
                r["diag"] = (await page.evaluate("document.querySelector('.diag').textContent")).split("\n")[:3]
            except Exception as e:  # noqa: BLE001
                r["error"] = str(e)[:300]
                r["logs"] = logs[-8:]
            out[variant] = r
            await page.close()
        await b.close()
    return out


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "docs"
        ep_id, doc = make_fixture(dst)
        server = subprocess.Popen([sys.executable, "-m", "RangeHTTPServer", str(PORT)], cwd=dst, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.2)
        try:
            out = asyncio.run(run(dst, ep_id, doc))
        finally:
            server.terminate()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    ok = True
    for v, r in out.items():
        if v == "pcm" and not (r.get("pcm", "") or "").startswith("wav"):
            print("pcm conversion missing:", r.get("pcm")); ok = False
        good = (not r.get("error") and r.get("phase") == "fixed" and r.get("anchors") == [] and r.get("adbar_hidden") is True
                and r.get("intro_line", "").startswith("인트로") and r.get("active_cue") == r.get("active_expected")
                and r.get("snap_offset") is not None and abs(r["snap_offset"]) < 0.15 and all(x.get("ok") for x in r.get("refs", [])))
        print(f"{v}: {'OK' if good else 'FAIL'}")
        ok = ok and good
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
