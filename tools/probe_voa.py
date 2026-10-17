"""VOA Learning English feeds (public domain) — list feeds, newest items, whether article pages carry transcripts."""
import json, sys
sys.path.insert(0, ".")
from pipeline.feeds import parse_feed
from pipeline.util import http_get_text, http_session
from pipeline import webtranscript as W
s = http_session(); out = {}
for term in ["VOA Learning English", "Let's Learn English VOA", "Everyday Grammar VOA", "English in a Minute VOA", "VOA Learning English As It Is",
             "America's Presidents VOA", "VOA Learning English Science & Technology", "VOA Learning English Health"]:
    try:
        r = s.get("https://itunes.apple.com/search", params={"term": term, "entity": "podcast", "limit": 6}, timeout=30).json()
        for h in r.get("results", []):
            f = h.get("feedUrl")
            if not f or "voa" not in (f + h.get("artistName", "") + h.get("collectionName", "")).lower() or f in out:
                continue
            rec = {"name": h.get("collectionName"), "artist": h.get("artistName")}
            try:
                _, eps = parse_feed(http_get_text(s, f))
                rec["n"] = len(eps); rec["newest"] = eps[0].published_iso if eps else None
                rec["eps"] = [{"t": e.title[:60], "d": e.duration_sec, "link": e.link, "tr": bool(e.best_transcript)} for e in eps[:2]]
                if eps and eps[0].link:
                    try:
                        ps = W.parse_paragraphs(W.fetch_page(s, eps[0].link), "voa_le"); rec["paras"] = len(ps); rec["words"] = sum(len(p["text"].split()) for p in ps)
                    except Exception as e:  # noqa: BLE001
                        rec["parse_error"] = str(e)[:120]
            except Exception as e:  # noqa: BLE001
                rec["error"] = str(e)[:120]
            out[f] = rec
    except Exception as e:  # noqa: BLE001
        out[term] = {"error": str(e)[:120]}
for f, r in out.items():
    print(f"::notice::{r.get('name')} | {f} | n={r.get('n')} newest={r.get('newest')} paras={r.get('paras')} words={r.get('words')} {r.get('parse_error','')}{r.get('error','')} | {json.dumps(r.get('eps'), ensure_ascii=False)[:300]}")
