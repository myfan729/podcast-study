"""Render the app (web build) against the real backend with a signed-in test user; screenshots → tools/app_ui/."""
import asyncio, json, os, subprocess, sys, time
from pathlib import Path
import requests
from playwright.async_api import async_playwright

URL, SVC = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
ANON = json.loads(Path("app/app.json").read_text())["expo"]["extra"]["supabaseAnonKey"]
REF = URL.split("//")[1].split(".")[0]
OUT = Path("tools/app_ui"); OUT.mkdir(exist_ok=True)
pw = "e2e-" + SVC[-10:]
sess = requests.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                     json={"email": "e2e-a@podcast-study.test", "password": pw}, timeout=30).json()
H = {"apikey": ANON, "Authorization": f"Bearer {sess['access_token']}"}
ready = requests.get(f"{URL}/rest/v1/unlocks?select=episode_id,episodes(status,title)", headers=H, timeout=30).json()
ep = next(u["episode_id"] for u in ready if u["episodes"]["status"] == "ready")
show = requests.get(f"{URL}/rest/v1/shows?select=id&title=eq.Odd%20Lots", headers=H, timeout=30).json()[0]["id"]
# follow two shows so the home feed has content
uid = sess["user"]["id"]
for t in ("Odd Lots", "The Indicator from Planet Money"):
    sid = requests.get(f"{URL}/rest/v1/shows?select=id&title=eq.{requests.utils.quote(t)}", headers=H, timeout=30).json()[0]["id"]
    requests.post(f"{URL}/rest/v1/subscriptions", headers={**H, "Prefer": "resolution=ignore-duplicates"}, json={"user_id": uid, "show_id": sid}, timeout=30)
SPA = r"""
import http.server, os
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory="app/dist", **k)
    def send_head(self):
        if not os.path.exists(os.path.join("app/dist", self.path.split("?")[0].lstrip("/"))) or self.path == "/":
            self.path = "/index.html"
        return super().send_head()
http.server.ThreadingHTTPServer(("", 8081), H).serve_forever()
"""
srv = subprocess.Popen([sys.executable, "-c", SPA])
time.sleep(1.5)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        await ctx.add_init_script(f"localStorage.setItem('sb-{REF}-auth-token', {json.dumps(json.dumps(sess))});")
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        for name, path, wait in (("home", "/", 6000), ("discover", "/discover", 5000), ("show", f"/show/{show}", 5000),
                                 ("episode", f"/episode/{ep}", 9000), ("vocab", "/vocab", 4000), ("settings", "/settings", 4000)):
            await pg.goto(f"http://localhost:8081{path}"); await pg.wait_for_timeout(wait)
            await pg.screenshot(path=str(OUT / f"{name}.png"))
            if name == "episode":
                await pg.get_by_text("단어·표현").first.click(); await pg.wait_for_timeout(1500)
                await pg.screenshot(path=str(OUT / "episode_words.png"))
        (OUT / "errors.json").write_text(json.dumps(errs[:40], ensure_ascii=False, indent=1))
        await b.close()
try:
    asyncio.run(main())
except Exception as e:  # noqa: BLE001
    import traceback
    (OUT / 'crash.txt').write_text(traceback.format_exc())
    print(traceback.format_exc())
srv.terminate()
