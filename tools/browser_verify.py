# verify run 2: includes BBC Learning English episodes (CORS on the BBC CDN?)
"""End-to-end check of automatic sync in a real browser (run on GitHub Actions, where the CDNs are reachable).
Serves docs/ locally, opens episode pages that have sync references, waits for auto-sync, records the result."""
import asyncio, json, subprocess, sys, time
from pathlib import Path

from playwright.async_api import async_playwright

DOCS = Path(__file__).resolve().parent.parent / "docs"


async def main():
    ids = [p.stem for p in sorted((DOCS / "data" / "sync").glob("*.json"))
           if json.loads(p.read_text()).get("refs") and "airlines" not in p.stem][:4]
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
                    await page.wait_for_function("document.getElementById('syncBtn').textContent.includes('✓') || document.getElementById('toast').textContent.includes('실패')", timeout=180000)
                    res = await page.evaluate("""() => ({ anchors: JSON.parse(localStorage.getItem('sync:' + location.search.slice(4)) || '[]'),
                        sync: document.getElementById('syncBtn').textContent, toast: document.getElementById('toast').textContent,
                        duration: document.getElementById('audio').duration })""")
                    res["seconds"] = round(time.time() - t0, 1)
                    res["report"] = next((l for l in logs if l.startswith("sync report")), None)
                    res["errors"] = errs
                except Exception as e:  # noqa: BLE001
                    res = {"error": str(e)[:200], "errors": errs, "logs": logs[-5:]}
                out[ep] = res
                print(ep, json.dumps(res, ensure_ascii=False)[:600], flush=True)
                await page.close()
            await b.close()
    finally:
        server.terminate()
    Path("tools/browser_verify.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


asyncio.run(main())
