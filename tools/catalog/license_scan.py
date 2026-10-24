"""Scan active English podcasts (Podcast Index dump) for licences that allow commercial use + adaptation."""
import asyncio, json, re, sqlite3, sys, time
import aiohttp

DB = sys.argv[1]; OUT = sys.argv[2]
since = int(time.time()) - 150 * 86400
con = sqlite3.connect(DB)
cols = [r[1] for r in con.execute("pragma table_info(podcasts)")]
print("columns:", cols)
rows = con.execute(f"""select url, title, itunesAuthor, itunesOwnerName, host, episodeCount, popularityScore, newestItemPubdate, link
  from podcasts where dead=0 and lower(language) like 'en%' and newestItemPubdate > {since} and episodeCount >= 8""").fetchall()
print("candidates:", len(rows))

LIC = re.compile(r"creativecommons\.org/(licenses|publicdomain)/([a-z\-]+)/?([\d.]*)|\bCC[ -]?(0|BY(?:[ -](?:SA|NC|ND))*)\b|public domain|Open Government Licen[cs]e|<podcast:license[^>]*>[^<]*", re.I)
def classify(hits, text):
    s = " ".join(hits).lower()
    if not s: return None
    if re.search(r"\bnc\b|by-nc|noncommercial|non-commercial|nc-", s): return "NC"
    if re.search(r"\bnd\b|by-nd|-nd|noderiv", s): return "ND"
    if "publicdomain/zero" in s or "cc0" in s or "cc 0" in s: return "CC0"
    if "public domain" in s: return "PD?"
    if "open government licen" in s: return "OGL"
    if re.search(r"licenses/by-sa|cc[ -]?by[ -]sa", s): return "BY-SA"
    if re.search(r"licenses/by/|cc[ -]?by\b", s): return "BY"
    return "OTHER"

async def one(sess, sem, r, out):
    url = r[0]
    gov = bool(re.search(r"\.(gov|mil)(/|$)", (r[4] or "") + "/") or re.search(r"\.(gov|mil)/", (r[8] or "") + "/"))
    async with sem:
        try:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=20), headers={"User-Agent": "Mozilla/5.0 (podcast app license scan)"}) as resp:
                raw = await resp.content.read(80000)
        except Exception:
            if gov: out.append({"url": url, "title": r[1], "author": r[2], "cls": "GOV-unreachable", "gov": True})
            return
    t = raw.decode("utf-8", "replace")
    head = t.split("<item", 1)[0]
    hits = [m.group(0)[:120] for m in LIC.finditer(head)]
    cp = re.search(r"<copyright>(.*?)</copyright>", head, re.S)
    cls = classify(hits, head)
    tx = t.count("<podcast:transcript")
    if cls or gov:
        out.append({"url": url, "title": r[1], "author": r[2], "owner": r[3], "eps": r[5], "pop": r[6], "last": r[7], "cls": cls or "GOV",
                    "gov": gov, "hits": hits[:4], "copyright": (cp.group(1).strip()[:150] if cp else None), "transcripts_in_head": tx, "link": r[8]})

async def main():
    out = []; sem = asyncio.Semaphore(300)
    conn = aiohttp.TCPConnector(limit=300, ttl_dns_cache=600, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        B = 5000
        for i in range(0, len(rows), B):
            await asyncio.gather(*(one(sess, sem, r, out) for r in rows[i:i+B]))
            print(i + B, "done,", len(out), "hits", flush=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=0)
asyncio.run(main())
