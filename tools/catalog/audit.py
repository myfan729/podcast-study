"""Can we really serve this show? (GitHub Actions, sharded)

For every show (the app catalog + tools/catalog/new_candidates.json):
  1. transcripts — of the 8 newest usable episodes, how many have a transcript we can get
     (RSS transcript tag, or the publisher's web page for npr/web shows); NPR-style shows are judged on
     episodes older than 2 days, since they post transcripts late;
  2. end to end — newest episode with a transcript: build the pack (mock study pack, no API cost) and the
     server's sync references, then download a SECOND copy of the audio (a new ad session, like a listener's),
     run the phone's matching on it, and check the result with speech recognition at 6 points spread over the
     episode: is the transcript sentence really being said where the synced player would show it?
Usage: python tools/catalog/audit.py SHARD NSHARDS → tools/catalog/audit/SHARD.json
"""
import json, sys, tempfile, time, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline import fingerprint as F  # noqa: E402
from pipeline import sync as SY  # noqa: E402
from pipeline.app_worker import show_config  # noqa: E402
from pipeline.feeds import parse_feed  # noqa: E402
from pipeline.llm import StudyGenerator  # noqa: E402
from pipeline.main import process_episode, show_filter, web_transcript_ready  # noqa: E402
from pipeline.util import http_get_text, http_session  # noqa: E402

N_RECENT, N_POINTS, TOL = 8, 6, 1.5
shard, nsh = int(sys.argv[1]), int(sys.argv[2])
shows = json.loads(Path("tools/catalog/catalog.json").read_text())["shows"]
extra = Path("tools/catalog/new_candidates.json")
if extra.exists():
    shows += [dict(s, candidate=True) for s in json.loads(extra.read_text())["shows"]]
mine = [s for i, s in enumerate(shows) if i % nsh == shard]
session, gen, asr = http_session(), StudyGenerator(mock=True), None


def has_transcript(cfg, ep) -> bool:
    if cfg.get("transcript") == "web":
        return web_transcript_ready(session, cfg, ep)
    return bool(ep.best_transcript)


def client_match(sync: dict, pcm8, content_dur: float) -> list[dict]:
    """The phone's matching (docs/assets/sync.js align), on a second copy of the audio."""
    dur = len(pcm8) / F.SR
    probe = F.fingerprint(pcm8)
    budget, offset, out = max(0.0, dur - content_dur), 0.0, []
    slack = 30.0 if sync.get("fixed") else 0.0
    for ref in sorted(sync.get("refs") or [], key=lambda r: r["c"]):
        fp = F.decode(ref["fp"])
        exp = ref["c"] + offset
        lo = int(max(0.0, exp - 2.5 - slack) / F.HOP_SEC)
        hi = int(min(dur, exp + budget + ref["len"] + 6 + slack) / F.HOP_SEC)
        o, b, second = F.best_offset(fp, probe, lo, hi)
        ok = b < 0.33 and second - b > 0.04
        a = o * F.HOP_SEC
        out.append({"c": ref["c"], "a": round(a, 3), "ber": round(b, 3), "ok": bool(ok)})
        if ok:
            new = a - ref["c"]
            budget = max(0.0, budget - max(0.0, new - offset))
            offset = new
    return out


def to_audio(c: float, matches: list[dict]) -> float:
    off = 0.0
    oks = [m for m in matches if m["ok"]]
    if oks:
        off = oks[0]["a"] - oks[0]["c"]
    for m in oks:
        if m["c"] <= c + 0.01:
            off = m["a"] - m["c"]
    return c + off


def check_points(doc: dict, matches: list[dict], pcm16) -> list[dict]:
    cues = doc["transcript"]["cues"]
    end = cues[-1]["e"]
    usable = [c for c in cues if 30 <= c["s"] <= end - 20 and len(SY.tokens(c["t"])) >= 6]
    if not usable:
        return []
    picks = [usable[int(i * (len(usable) - 1) / max(1, N_POINTS - 1))] for i in range(N_POINTS)]
    res = []
    for cue in picks:
        pred = to_audio(cue["s"], matches)
        words = asr.words(pcm16, pred - 10, pred + 16)
        hit = SY.locate(SY.cue_tokens(cues, cue["s"], 14), words, pred - 10, pred + 16)
        if not hit:
            res.append({"c": cue["s"], "pred": round(pred, 1), "found": False, "text": cue["t"][:60]})
            continue
        err = (cue["s"] + hit["offset"]) - pred
        res.append({"c": cue["s"], "pred": round(pred, 1), "err": round(err, 2), "ok": abs(err) <= TOL, "score": hit["score"]})
    return res


out = {}
for sh in mine:
    t0 = time.time()
    rec = {"title": sh["title"], "path": sh.get("path"), "candidate": bool(sh.get("candidate"))}
    try:
        cfg = show_config(dict(sh, id="00000000-audit"))
        meta, eps = parse_feed(http_get_text(session, sh["feed_url"]))
        rec["meta"] = {k: (meta.get(k) if isinstance(meta, dict) else getattr(meta, k, None)) for k in ("title", "author", "image", "image_url", "description")}
        ok = show_filter(cfg)
        now = datetime.now(timezone.utc)
        usable = [e for e in eps if ok(e)][:N_RECENT]
        late = cfg.get("transcript") == "web" and sh.get("path") == "npr"
        settled = [e for e in usable if not late or now - e.published_at > timedelta(days=2)]
        avail = [e for e in settled if has_transcript(cfg, e)]
        rec.update(recent=len(usable), judged=len(settled), with_transcript=len(avail),
                   transcript_rate=round(len(avail) / len(settled), 2) if settled else 0.0,
                   newest=usable[0].published_iso if usable else None)
        if not avail:
            raise RuntimeError("no episode with a transcript")
        ep = avail[0]
        rec["episode"] = ep.title
        doc = process_episode(session, gen, cfg, ep, translate=False)
        rec.update(cues=len(doc["transcript"]["cues"]), dai=doc["audio_meta"].get("dai"),
                   fixed=bool(doc["audio_meta"].get("fixed")), duration=doc.get("duration_sec"))
        if asr is None:
            asr = SY.Asr()
        sync = SY.build(doc, asr, session)
        rec.update(sync=sync.get("status"), refs=len(sync.get("refs") or []))
        time.sleep(20)                                            # a new ad session for the "listener" copy
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "listener.mp3"
            SY.download(session, doc.get("audio_url_original") or doc["audio_url"], p)
            pcm8, pcm16 = F.decode_pcm(p, F.SR), F.decode_pcm(p, 16000)
        content_dur = float(sync.get("content_duration") or doc.get("duration_sec") or doc["transcript"]["cues"][-1]["e"])
        matches = client_match(sync, pcm8, content_dur)
        rec["listener"] = {"duration": round(len(pcm8) / F.SR, 1), "refs_ok": sum(m["ok"] for m in matches), "refs": len(matches),
                           "offsets": sorted({round(m["a"] - m["c"], 1) for m in matches if m["ok"]})[:8]}
        pts = check_points(doc, matches, pcm16)
        rec["points"] = pts
        rec["accuracy"] = round(sum(1 for p in pts if p.get("ok")) / len(pts), 2) if pts else 0.0
    except Exception as e:  # noqa: BLE001
        rec.update(error=str(e)[:300], trace=traceback.format_exc()[-500:])
    rec["verdict"] = ("keep" if rec.get("transcript_rate", 0) >= 0.6 and rec.get("accuracy", 0) >= 0.8
                      else "check" if rec.get("transcript_rate", 0) >= 0.4 and rec.get("accuracy", 0) >= 0.5 else "drop")
    rec["sec"] = round(time.time() - t0)
    out[sh["feed_url"]] = rec
    print(json.dumps({k: rec.get(k) for k in ("title", "verdict", "transcript_rate", "accuracy", "sync", "refs", "error")},
                     ensure_ascii=False), flush=True)
Path("tools/catalog/audit").mkdir(exist_ok=True)
Path(f"tools/catalog/audit/{shard}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
