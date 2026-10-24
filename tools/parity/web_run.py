"""Parity: the phone's web-page transcript reader (app/lib/webTranscript.ts) vs pipeline/webtranscript.py + split_sentences.
Recent episodes of every web-transcript show; compares sentences, speakers and fingerprints."""
import json, subprocess, sys
from pipeline.feeds import parse_feed
from pipeline.util import http_session, http_get_text
from pipeline import webtranscript as W
from pipeline.app_worker import show_config, page_sentences, fp

cat = json.load(open("tools/catalog/catalog.json"))
rows = [r for r in (cat if isinstance(cat, list) else cat["shows"]) if r.get("path") in ("npr", "web")]
s = http_session(); ok = bad = 0; rep = []
for r in rows:
    cfg = show_config({**r, "id": "x"})
    try:
        _, eps = parse_feed(http_get_text(s, r["feed_url"]))
    except Exception as e:
        rep.append(f"SKIP {r['title']}: feed {e}"); continue
    tried = 0
    for ep in eps[:6]:
        try:
            url = W.resolve_page_url(s, cfg, ep); html = W.fetch_page(s, url)
            py = page_sentences(html, cfg.get("parser") or "generic")
        except Exception as e:
            continue
        tried += 1
        open("/tmp/page.html", "w").write(html)
        out = subprocess.run(["node", "tools/parity/web_ts.mjs", "/tmp/page.html", cfg.get("parser") or "generic"], capture_output=True, text=True)
        if out.returncode:
            bad += 1; rep.append(f"ERR {r['title']}: {out.stderr[-300:]}"); break
        ts = json.loads(out.stdout)
        a = [[x["t"], x["spk"], fp(x["t"])] for x in py]
        b = [[x["t"], x["spk"], x["fp"]] for x in ts]
        if a == b:
            ok += 1; rep.append(f"OK {r['title']} n={len(a)} {url[-40:]}")
        else:
            bad += 1
            k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            rep.append(f"DIFF {r['title']} py={len(a)} ts={len(b)} at {k}: {a[k] if k < len(a) else None} | {b[k] if k < len(b) else None}"[:700])
        if tried >= 2:
            break
    if tried == 0:
        rep.append(f"SKIP {r['title']}: no page with a transcript")
for k in range(0, len(rep), 8):
    print(f"::notice title=web parity ok={ok} bad={bad} [{k}]::" + " ### ".join(rep[k:k + 8])[:3900])
sys.exit(1 if bad else 0)
