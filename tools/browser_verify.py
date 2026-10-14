# verify run 6: NPR Up First (web transcript + detected ad gaps) and SYSK Short Stuff
"""End-to-end check of automatic sync in a real browser (run on GitHub Actions, where the CDNs are reachable).
Serves docs/ locally, opens episode pages that have sync references, waits for the sync report the page
persists (localStorage syncrep:<id>), records phase / anchors / per-reference match quality."""
import asyncio, json, subprocess, sys, time
from pathlib import Path

from playwright.async_api import async_playwright

DOCS = Path(__file__).resolve().parent.parent / "docs"


async def main():
    ids = [p.stem for p in sorted((DOCS / "data" / "sync").glob("*.json"))
           if json.loads(p.read_text()).get("refs") and "airlines" not in p.stem]
    # all BBC (fixed) episodes + up to three ad-inserted ones
    ids = [i for i in ids if i.startswith(("up-first", "the-indicator", "stuff-you"))][:3]
    server = subprocess.Popen([sys.executable, "-m", "RangeHTTPServer", "8766"], cwd=DOCS)
    time.sleep(1.5)
    out = {}
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch()
            for ep in ids:
                page = await b.new_page(viewport={"width": 390, "height": 844})
                logs, errs = [], []
                page.on("console", lambda m: logs.append(m.text))
                page.on("pageerror", lambda e: errs.append(str(e)))
                t0 = time.time()
                await page.goto(f"http://localhost:8766/episode.html?id={ep}")
                try:
                    await page.wait_for_function("!!localStorage.getItem('syncrep:' + location.search.slice(4))", timeout=180000)
                    rep = json.loads(await page.evaluate("localStorage.getItem('syncrep:' + location.search.slice(4))"))
                    doc = json.loads((DOCS / "data" / "episodes" / f"{ep}.json").read_text())
                    first = doc["transcript"]["cues"][0]
                    # jump to just after the first line starts and see what is highlighted
                    a_first = first["s"] + (rep["anchors"][0]["a"] - rep["anchors"][0]["c"] if rep["anchors"] else 0)
                    await page.evaluate("t => { const a = document.getElementById('audio'); a.currentTime = t; a.dispatchEvent(new Event('timeupdate')); }", a_first + 0.5)
                    active = await page.evaluate("document.querySelector('.cue.active') && document.querySelector('.cue.active').textContent")
                    res = {"phase": rep["phase"], "error": rep.get("error"), "anchors": rep["anchors"],
                           "refs": [{k: r.get(k) for k in ("c", "ok", "a", "offset", "ber", "second", "error")} for r in (rep["report"] or {}).get("refs", [])],
                           "decode": (rep["report"] or {}).get("decode"), "adTotal": (rep["report"] or {}).get("adTotal"), "ms": (rep["report"] or {}).get("ms"),
                           "sync_btn": await page.evaluate("document.getElementById('syncBtn').textContent"),
                           "adbar_hidden": await page.evaluate("document.getElementById('adbar').hidden"),
                           "first_line_ok": active == first["t"], "seconds": round(time.time() - t0, 1), "errors": errs}
                except Exception as e:  # noqa: BLE001
                    res = {"error": str(e)[:200], "errors": errs, "logs": logs[-5:]}
                out[ep] = res
                print(ep, json.dumps(res, ensure_ascii=False)[:700], flush=True)
                await page.close()
            await b.close()
    finally:
        server.terminate()
    Path("tools/browser_verify.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


asyncio.run(main())
