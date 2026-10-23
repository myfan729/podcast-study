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
# stage the test account so the screenshots look like real use (also used for the store listing)
S = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}
requests.patch(f"{URL}/rest/v1/unlocks?user_id=eq.{uid}", headers=S, timeout=30,
               json={"unlocked_at": "2026-01-01T00:00:00Z"})                      # weekly quota → full again
WORDS = [("word", "underlying", "근본적인, 기저의", "The underlying problem isn't the schedule."),
         ("word", "annualized", "연율로 환산한", "At that pace, the annualized growth would be around 8%."),
         ("word", "spiral", "악순환적 상승·하락, 나선", "The club slid into a downward spiral."),
         ("expression", "pass along", "(비용 등을) 다른 사람에게 넘기다, 전가하다", "A lot of that cost gets passed along to shoppers."),
         ("expression", "on the hook", "(비용·책임을) 떠안은", "Taxpayers could be on the hook for the bill."),
         ("word", "buyout", "(기업) 인수, 지분 매입", "The owners accepted a buyout offer.")]
requests.post(f"{URL}/rest/v1/vocab?on_conflict=user_id,kind,text", headers={**S, "Prefer": "resolution=merge-duplicates"}, timeout=30,
              json=[{"user_id": uid, "kind": k, "text": t, "meaning_ko": m, "example": e, "due_at": "2026-01-01T00:00:00Z", "reps": 2 if i % 2 else 0}
                    for i, (k, t, m, e) in enumerate(WORDS)])
# signed up already (nickname + current terms), so the app goes straight in
import re
cfg = Path("app/lib/config.ts").read_text()
TV = re.search(r"TERMS_VERSION = '([^']+)'", cfg).group(1); PV = re.search(r"PRIVACY_VERSION = '([^']+)'", cfg).group(1)
requests.post(f"{URL}/rest/v1/profiles?on_conflict=user_id", headers={**S, "Prefer": "resolution=merge-duplicates"}, timeout=30,
              json={"user_id": uid, "nickname": "경환", "terms_version": TV, "privacy_version": PV, "age14_confirmed": True})
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
        b = await p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        await ctx.add_init_script(f"localStorage.setItem('sb-{REF}-auth-token', {json.dumps(json.dumps(sess))});")
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        shots = (("home", "/", 6000), ("discover", "/discover", 5000), ("show", f"/show/{show}", 5000),
                 ("listen", f"/episode/{ep}", 6000), ("episode", f"/episode/{ep}?study=1", 9000),
                 ("vocab", "/vocab", 4000), ("settings", "/settings", 4000))
        for name, path, wait in shots:
            try:
                await pg.goto(f"http://localhost:8081{path}"); await pg.wait_for_timeout(wait)
                if name == "episode":
                    await pg.mouse.click(195, 520); await pg.wait_for_timeout(2500)    # tap a sentence → jump + play
                await pg.screenshot(path=str(OUT / f"{name}.png"))
                if name == "episode":
                    await pg.get_by_text("단어·표현").first.click(timeout=8000); await pg.wait_for_timeout(1500)
                    await pg.screenshot(path=str(OUT / "episode_words.png"))
            except Exception as e:  # noqa: BLE001  (one screen failing shouldn't lose the rest)
                errs.append(f"{name}: {e}"[:300]); await pg.screenshot(path=str(OUT / f"{name}.png"))
        # the login screen, signed out
        ctx2 = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        p2 = await ctx2.new_page(); await p2.goto("http://localhost:8081/login"); await p2.wait_for_timeout(4000)
        await p2.screenshot(path=str(OUT / "login.png"))
        (OUT / "errors.json").write_text(json.dumps(errs[:40], ensure_ascii=False, indent=1))
        await b.close()
try:
    asyncio.run(main())
except Exception as e:  # noqa: BLE001
    import traceback
    (OUT / 'crash.txt').write_text(traceback.format_exc())
    print(traceback.format_exc())
srv.terminate()
