"""End-to-end check of every catalog show (GitHub Actions, sharded): newest usable episode →
transcript → cues/sentences (mock study pack, no API cost) → audio download + ASR sync references.
Usage: python tools/catalog/verify_catalog.py SHARD NSHARDS  → tools/catalog/verify/SHARD.json
"""
import json, sys, time, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.app_worker import show_config  # noqa: E402
from pipeline.feeds import parse_feed  # noqa: E402
from pipeline.llm import StudyGenerator  # noqa: E402
from pipeline.main import process_episode, show_filter  # noqa: E402
from pipeline import sync as SY  # noqa: E402
from pipeline.util import http_get_text, http_session  # noqa: E402

shard, n = int(sys.argv[1]), int(sys.argv[2])
cat = json.loads(Path("tools/catalog/catalog.json").read_text())["shows"]
mine = [s for i, s in enumerate(cat) if i % n == shard]
session, gen, asr = http_session(), StudyGenerator(mock=True), None
out = {}
for sh in mine:
    t0 = time.time()
    rec = {"title": sh["title"]}
    try:
        row = dict(sh, id="00000000-verify")
        cfg = show_config(row)
        _, eps = parse_feed(http_get_text(session, sh["feed_url"]))
        ok = show_filter(cfg)
        now = datetime.now(timezone.utc)
        cands = [e for e in eps if ok(e) and (e.best_transcript or (sh["path"] == "npr" and now - e.published_at > timedelta(days=2)))]
        if not cands:
            raise RuntimeError("no usable episode")
        ep = cands[0]
        rec["episode"] = ep.title
        doc = process_episode(session, gen, cfg, ep, translate=False)
        tr = doc["transcript"]
        rec.update(cues=len(tr["cues"]), sentences=len(tr.get("sentences") or []), speakers=tr["stats"].get("speakers", [])[:6],
                   words=tr["stats"]["words"], dai=doc["audio_meta"].get("dai"), markers=len(doc["audio_meta"].get("ad_markers") or []),
                   sample=[c["t"] for c in tr["cues"][1:3]])
        if asr is None:
            asr = SY.Asr()
        sy = SY.build(doc, asr, session)
        rec.update(sync=sy.get("status"), refs=len(sy.get("refs") or []))
        rec["ok"] = rec["cues"] >= 30 and sy.get("status") in ("ok", "fixed")
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error=str(e)[:300], trace=traceback.format_exc()[-600:])
    rec["sec"] = round(time.time() - t0)
    out[sh["feed_url"]] = rec
    print(json.dumps(rec, ensure_ascii=False)[:400], flush=True)
Path("tools/catalog/verify").mkdir(exist_ok=True)
Path(f"tools/catalog/verify/{shard}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
