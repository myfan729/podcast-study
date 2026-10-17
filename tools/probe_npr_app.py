"""Why do NPR episodes fail in the app? For the newest episodes of a few NPR shows: resolve the transcript
page, try to parse it, and save the page when parsing fails (tools/npr_samples/fail-*.html)."""
import json, re
from pathlib import Path
from pipeline.feeds import parse_feed
from pipeline.util import http_get_text, http_session
from pipeline import webtranscript as W

SHOWS = {"Life Kit": "https://feeds.npr.org/510338/podcast.xml",
         "The Indicator": "https://feeds.npr.org/510325/podcast.xml",
         "Up First": "https://feeds.npr.org/510318/podcast.xml"}
s = http_session(); out = {}
Path("tools/npr_samples").mkdir(exist_ok=True)
for name, feed in SHOWS.items():
    _, eps = parse_feed(http_get_text(s, feed))
    rows = []
    for ep in eps[:8]:
        if name != "Life Kit":
            continue
        r = {"title": ep.title, "pub": ep.published_iso, "link": ep.link}
        try:
            url = W.resolve_page_url(s, {"parser": "npr"}, ep); r["url"] = url
            html = W.fetch_page(s, url)
            try:
                paras = W.parse_paragraphs(html, "npr"); r["ok"] = True; r["paras"] = len(paras)
            except Exception as e:  # noqa: BLE001
                r["ok"] = False; r["error"] = f"{type(e).__name__}: {e}"[:200]
                sid = url.rsplit("/", 1)[-1]
                Path(f"tools/npr_samples/fail-{sid}.html").write_text(html[:400000])
                r["has_transcript_word"] = "transcript" in html.lower(); r["len"] = len(html)
                m = re.search(r"<title>(.*?)</title>", html, re.S); r["page_title"] = m.group(1).strip()[:120] if m else None
                body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
                cls = sorted(set(re.findall(r'class="([^"]*transcript[^"]*)"', html, re.I)))[:6]
                txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
                i = txt.lower().find("transcript", txt.lower().find(ep.title.lower()[:20]) + 1)
                r["page_title"] = f"classes={cls} text≈{txt[max(0, i - 80):i + 320]}"
        except Exception as e:  # noqa: BLE001
            r["ok"] = False; r["error"] = f"{type(e).__name__}: {e}"[:200]
        rows.append(r)
    out[name] = rows
Path("tools/probe_npr_app.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
for k, v in out.items():
    for r in v:
        print(f"::notice title={k}::{'OK' if r.get('ok') else 'FAIL'} {r['pub'][:16]} {r['title'][:50]} | paras={r.get('paras','')} "
              f"{r.get('error','')} | {r.get('page_title') or ''} | {r.get('url','')}")
