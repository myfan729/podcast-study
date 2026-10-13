"""Probe: list posts of the owner's Naver blog(s) with each public endpoint and show what would be linked."""
import json, sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import blog_index as B
from pipeline.util import http_session

IDS = ["oorange0123"]
s = http_session()
out = {}
for bid in IDS:
    rec = {}
    for name, fn in (("mobile-api", B.fetch_mobile_api), ("title-list", B.fetch_title_list), ("rss", B.fetch_rss)):
        try:
            posts = fn(s, bid)
            rec[name] = {"count": len(posts), "sample": [p["title"] for p in posts[:5]]}
            rec.setdefault("posts", posts)
        except Exception as e:  # noqa: BLE001
            rec[name] = {"error": str(e)[:300]}
    try:
        r = s.get(f"https://m.blog.naver.com/api/blogs/{bid}/category-list",
                  headers={"User-Agent": B.MOBILE_UA, "Referer": f"https://m.blog.naver.com/{bid}"}, timeout=20)
        cats = ((r.json() or {}).get("result") or {}).get("mylogCategoryList") or []
        rec["categories"] = [{"no": c.get("categoryNo"), "name": c.get("categoryName"), "posts": c.get("postCnt")} for c in cats]
    except Exception as e:  # noqa: BLE001
        rec["categories"] = {"error": str(e)[:300]}
    posts = rec.get("posts") or []
    rec["titles"] = [{"t": p["title"], "cat": p.get("category"), "phr": B.title_phrases(p["title"])} for p in posts]
    rec.pop("posts", None)
    rec["links"] = B.link_episodes(posts) if posts else {}
    out[bid] = rec
Path("tools/probe_blog.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("titles",)} for k, v in out.items()}, ensure_ascii=False, indent=1)[:4000])
