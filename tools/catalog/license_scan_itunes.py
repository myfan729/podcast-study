"""Collect podcast feeds via iTunes search over many topic words, then scan channel headers for open licences."""
import asyncio, json, re, sys, time
from email.utils import parsedate_to_datetime
import aiohttp, requests

OUT = sys.argv[1]
WORDS = """creative commons;cc by;public domain;open licence;open license;government;nasa;noaa;nih;cdc;usgs;library of congress;national archives;smithsonian;
federal;department of;agency;university;lecture;research;science;history;economics;business;finance;money;investing;technology;programming;software;linux;open source;
startup;marketing;leadership;management;career;education;teaching;learning english;english lessons;esl;language;linguistics;grammar;vocabulary;pronunciation;
news;politics;world news;daily news;climate;environment;energy;space;astronomy;physics;chemistry;biology;medicine;health;nutrition;fitness;psychology;mental health;
philosophy;religion;culture;art;design;architecture;photography;film;movies;tv;books;literature;poetry;short stories;fiction;audio drama;storytelling;comedy;
interview;conversation;society;law;justice;crime;true crime;sports;football;soccer;basketball;baseball;cricket;travel;food;cooking;wine;coffee;gardening;
nature;wildlife;ocean;birds;dogs;cats;parenting;family;relationships;self improvement;productivity;mindfulness;meditation;sleep;music;jazz;classical music;
gaming;video games;board games;anime;comics;fantasy;science fiction;horror;mystery;kids;children;teens;students;college;military;veterans;aviation;cars;
cycling;running;hiking;outdoors;farming;agriculture;real estate;personal finance;crypto;bitcoin;ai;artificial intelligence;machine learning;data science;
security;privacy;internet;web development;python;javascript;devops;cloud;math;statistics;engineering;robotics;innovation;entrepreneur;small business;
nonprofit;community;activism;human rights;development;international;africa;asia;europe;australia;canada;uk;britain;ireland;new zealand;india;
podcast about podcasting;radio;public radio;documentary;oral history;archive;museum;heritage;genealogy;geography;maps;weather;earth science;geology;
volcano;oceanography;marine;ecology;conservation;sustainability;transport;cities;urban;housing;economy;markets;trade;policy;think tank;tutorial;howto;
wikipedia;open education;oer;mooc;free culture;remix;indie;audiobook;librivox;gutenberg;classic literature;bible;sermon;church;theology""".replace("\n", "").split(";")

def collect():
    s = requests.Session(); feeds = {}
    for i, w in enumerate(w.strip() for w in WORDS if w.strip()):
        for attempt in range(3):
            try:
                r = s.get("https://itunes.apple.com/search", params={"term": w, "media": "podcast", "entity": "podcast", "limit": 200, "lang": "en_us"}, timeout=30)
                if r.status_code == 200:
                    for h in r.json().get("results", []):
                        if h.get("feedUrl"): feeds[h["feedUrl"]] = {"title": h.get("collectionName"), "author": h.get("artistName"), "genre": h.get("primaryGenreName")}
                    break
            except Exception: pass
            time.sleep(10)
        time.sleep(3.2)
        if i % 20 == 0: print(i, w, len(feeds), flush=True)
    return feeds

LIC = re.compile(r"creativecommons\.org/(licenses|publicdomain)/([a-z\-]+)/?([\d.]*)|\bCC[ -]?(0|BY(?:[ -](?:SA|NC|ND))*)\b|public domain|Open Government Licen[cs]e|<podcast:license[^>]*>[^<]*", re.I)
def classify(s):
    s = s.lower()
    if not s: return None
    if re.search(r"\bnc\b|by-nc|noncommercial|non-commercial|nc-", s): return "NC"
    if re.search(r"\bnd\b|by-nd|-nd|noderiv", s): return "ND"
    if "publicdomain/zero" in s or "cc0" in s or "cc 0" in s: return "CC0"
    if "public domain" in s: return "PD?"
    if "open government licen" in s: return "OGL"
    if re.search(r"licenses/by-sa|cc[ -]?by[ -]sa", s): return "BY-SA"
    if re.search(r"licenses/by/|cc[ -]?by\\b|cc[ -]?by$|cc by ", s): return "BY"
    return "OTHER"

async def one(sess, sem, url, meta, out):
    async with sem:
        try:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=20), headers={"User-Agent": "Mozilla/5.0 (podcast app)"}) as resp:
                raw = await resp.content.read(120000)
        except Exception: return
    t = raw.decode("utf-8", "replace"); head = t.split("<item", 1)[0]
    lang = (re.search(r"<language>\s*([^<]+)", head) or [None, ""])[1].strip().lower()
    link = (re.search(r"<link>\s*([^<]+)", head) or [None, ""])[1].strip()
    owner = (re.search(r"<itunes:email>\s*([^<]+)", head) or [None, ""])[1].strip()
    gov = bool(re.search(r"\.(gov|mil)\b", link + " " + owner + " " + url))
    hits = [m.group(0)[:120] for m in LIC.finditer(head)]
    cls = classify(" ".join(hits)) if hits else None
    if not (cls or gov): return
    pd = re.search(r"<pubDate>(.*?)</pubDate>", t.split("<item", 1)[1] if "<item" in t else "")
    try: last = parsedate_to_datetime(pd.group(1).strip()).date().isoformat() if pd else None
    except Exception: last = None
    cp = re.search(r"<copyright>(.*?)</copyright>", head, re.S)
    out.append({"url": url, **meta, "lang": lang, "cls": cls or "GOV", "gov": gov, "hits": hits[:4], "copyright": (cp.group(1).strip()[:150] if cp else None),
                "last": last, "items": t.count("<item"), "tx": t.count("<podcast:transcript"), "link": link, "owner": owner})

async def scan(feeds):
    out = []; sem = asyncio.Semaphore(200)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=200, ssl=False)) as sess:
        await asyncio.gather(*(one(sess, sem, u, m, out) for u, m in feeds.items()))
    return out

feeds = collect(); print("feeds:", len(feeds), flush=True)
out = asyncio.run(scan(feeds)); print("hits:", len(out))
json.dump({"feeds_scanned": len(feeds), "hits": out}, open(OUT, "w"), ensure_ascii=False, indent=0)
