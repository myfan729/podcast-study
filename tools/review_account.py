"""Create (or reset) the store-review account: email + password login, Pro plan so reviewers are never blocked.
The password is random and is written only to public._admin_notes (read it in the Supabase SQL editor):
    select value from public._admin_notes where key = 'review_password';
"""
import os, secrets, string
import requests

URL, SVC = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}
EMAIL = "review@ingpot.app"
pw = "Ingpot-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))

r = requests.post(f"{URL}/auth/v1/admin/users", headers=H, timeout=30, json={"email": EMAIL, "password": pw, "email_confirm": True})
if r.status_code in (200, 201):
    uid = r.json()["id"]
else:  # exists → find it and reset the password
    users = requests.get(f"{URL}/auth/v1/admin/users?per_page=1000", headers=H, timeout=30).json()["users"]
    uid = next(u["id"] for u in users if u.get("email") == EMAIL)
    requests.put(f"{URL}/auth/v1/admin/users/{uid}", headers=H, timeout=30, json={"password": pw}).raise_for_status()
requests.post(f"{URL}/rest/v1/entitlements?on_conflict=user_id", headers={**H, "Prefer": "resolution=merge-duplicates"}, timeout=30,
              json={"user_id": uid, "plan": "pro", "source": "store-review"}).raise_for_status()
# follow a few shows so the reviewer lands on a full home screen
shows = requests.get(f"{URL}/rest/v1/shows?select=id,title&catalog=eq.true", headers=H, timeout=30).json()
pick = [s["id"] for s in shows if s["title"].startswith(("The Indicator", "Up First", "Odd Lots", "Think Fast"))]
requests.post(f"{URL}/rest/v1/subscriptions", headers={**H, "Prefer": "resolution=ignore-duplicates"}, timeout=30,
              json=[{"user_id": uid, "show_id": s} for s in pick])
requests.post(f"{URL}/rest/v1/_admin_notes?on_conflict=key", headers={**H, "Prefer": "resolution=merge-duplicates"}, timeout=30,
              json=[{"key": "review_email", "value": EMAIL}, {"key": "review_password", "value": pw}]).raise_for_status()
print(f"review account ready: {EMAIL} (password in public._admin_notes), following {len(pick)} shows")
