"""Backend end-to-end test (GitHub Actions): test users → catalog → unlock an episode → worker builds it →
the user downloads the pack; another user can't; free quota stops the 3rd episode. Writes tools/app_e2e.json."""
import json, os, subprocess, sys, time
from pathlib import Path
import requests

URL, SVC = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
ANON = json.loads(Path("app/app.json").read_text())["expo"]["extra"]["supabaseAnonKey"]
out = {}

def admin_user(email, pw):
    r = requests.post(f"{URL}/auth/v1/admin/users", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"},
                      json={"email": email, "password": pw, "email_confirm": True}, timeout=30)
    if r.status_code not in (200, 201, 422) and "already" not in r.text:
        raise RuntimeError(f"create user {r.status_code} {r.text[:200]}")

def login(email, pw):
    r = requests.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, json={"email": email, "password": pw}, timeout=30)
    r.raise_for_status()
    tok = r.json()["access_token"]
    return {"apikey": ANON, "Authorization": f"Bearer {tok}"}

def get(h, path):
    r = requests.get(f"{URL}/rest/v1/{path}", headers=h, timeout=30); r.raise_for_status(); return r.json()

def rpc(h, fn, args):
    r = requests.post(f"{URL}/rest/v1/rpc/{fn}", headers=h, json=args, timeout=30); r.raise_for_status(); return r.json()

try:
    pw = "e2e-" + SVC[-10:]
    admin_user("e2e-a@podcast-study.test", pw); admin_user("e2e-b@podcast-study.test", pw)
    A, B = login("e2e-a@podcast-study.test", pw), login("e2e-b@podcast-study.test", pw)
    shows = get(A, "shows?select=id,title&catalog=eq.true")
    out["catalog_shows"] = len(shows)
    eps = get(A, "episodes?select=id,title,status,show_id&has_transcript=eq.true&order=published_at.desc&limit=2000")
    out["episodes_listed"] = len(eps)
    ind = next(s for s in shows if s["title"].startswith("The Indicator"))
    ep = next(e for e in eps if e["show_id"] == ind["id"])
    out["test_episode"] = ep["title"]
    out["request_1"] = rpc(A, "request_episode", {"ep": ep["id"]})
    # build it here (don't depend on the dispatch trigger for the test)
    t0 = time.time()
    subprocess.run([sys.executable, "-m", "pipeline.app_worker", "process", "--max", "2"], check=False)
    row = get(A, f"episodes?select=status,pack_path,sync_path,error&id=eq.{ep['id']}")[0]
    out["after_worker"] = row; out["build_sec"] = round(time.time() - t0)
    r = requests.get(f"{URL}/storage/v1/object/authenticated/episodes/{ep['id']}.json", headers=A, timeout=60)
    out["owner_download"] = r.status_code
    if r.ok:
        d = r.json()
        out["pack"] = {"cues": len(d["transcript"]["cues"]), "translations": len(d["study"].get("translations_sent") or {}),
                       "vocab": len(d["study"].get("vocab") or []), "expressions": len(d["study"].get("expressions") or []),
                       "one_liner": d["study"].get("one_liner_ko")}
    out["other_user_download"] = requests.get(f"{URL}/storage/v1/object/authenticated/episodes/{ep['id']}.json", headers=B, timeout=60).status_code
    others = [e for e in eps if e["id"] != ep["id"]][:2]
    out["request_2"] = rpc(A, "request_episode", {"ep": others[0]["id"]})
    out["request_3_quota"] = rpc(A, "request_episode", {"ep": others[1]["id"]})
    out["ok"] = bool(out["owner_download"] == 200 and out["other_user_download"] in (400, 403, 404) and out["request_3_quota"].get("reason") == "quota")
except Exception as e:  # noqa: BLE001
    out["error"] = repr(e)[:400]; out["ok"] = False
print(json.dumps(out, ensure_ascii=False, indent=1))
Path("tools/app_e2e.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
