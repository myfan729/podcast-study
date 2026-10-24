"""End-to-end for web-page transcripts: build the newest 6 Minute English + Planet Money episodes with the real worker,
then check the stored pack has no text and the phone code rebuilds the transcript from the page + the pack's timing."""
import json, os, subprocess, sys
from pipeline.app_worker import supa, process, sync_pending
db = supa(); rep = []
picked = []
for title in ("6 Minute English", "Planet Money"):
    sh = db.select("shows", f"select=id&title=eq.{title.replace(' ', '%20')}")[0]
    ep = db.select("episodes", f"select=id,title,status,transcript_url,transcript_kind&show_id=eq.{sh['id']}&has_transcript=eq.true"
                               f"&transcript_url=not.is.null&order=published_at.desc&limit=1")[0]
    rep.append(f"{title}: {ep['title'][:40]} url={ep['transcript_url']}")
    if os.environ.get("CHECK_ONLY") != "1":
        db.update("episodes", f"id=eq.{ep['id']}", {"status": "queued", "attempts": 0, "error": None})
    picked.append(ep["id"])
if os.environ.get("CHECK_ONLY") != "1":
    process(db, max_n=4)
    sync_pending(db, max_n=4)
for eid in picked:
    row = db.select("episodes", f"select=title,status,error,pack_path,sync_path&id=eq.{eid}")[0]
    if row["status"] != "ready":
        rep.append(f"NOT READY {row['title'][:40]}: {row['status']} {row['error']}"); continue
    r = db.s.get(f"{db.url}/storage/v1/object/episodes/{row['pack_path']}", headers=db.h, timeout=60); pack = r.json()
    tr = pack["transcript"]
    open("/tmp/pack.json", "w").write(json.dumps(pack))
    out = subprocess.run(["node", "tools/parity/web_e2e.mjs", "/tmp/pack.json"], capture_output=True, text=True)
    rep.append(f"{row['title'][:40]}: text_free={pack.get('text_free')} has_cues={'cues' in tr} timing={len(tr.get('timing') or [])} "
               f"sync={bool(row['sync_path'])} vocab={len(pack['study'].get('vocab') or [])} phone={out.stdout.strip() or out.stderr[-300:]}")
print("::notice title=web e2e::" + " ### ".join(rep)[:3900])
