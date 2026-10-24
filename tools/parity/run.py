"""Parity check: the app's TS transcript parser must produce exactly what pipeline/transcript.py does.
Fetches the newest transcript of several RSS shows, runs both, compares cues/segments/sentences."""
import json, subprocess, sys
from pipeline.feeds import parse_feed
from pipeline.util import http_session, http_get_text
from pipeline.transcript import parse_transcript, sentence_cues, segment_cues, group_sentences

cat = json.load(open("tools/catalog/catalog.json"))
rows = [r for r in (cat if isinstance(cat, list) else cat["shows"]) if r.get("path") == "rss"]
s = http_session(); ok = bad = 0; report = []
for r in rows:
    try:
        _, eps = parse_feed(http_get_text(s, r["feed_url"]))
        ep = next(e for e in eps[:5] if e.best_transcript)
        ref = ep.best_transcript; raw = http_get_text(s, ref.url)
    except Exception as e:
        report.append(f"SKIP {r['title']}: {e}"); continue
    cues = sentence_cues(parse_transcript(raw, ref.kind)); segs = segment_cues(cues); sents = group_sentences(cues, segs)
    py = {"cues": [[c.i, c.t, c.spk, round(c.s, 2)] for c in cues], "segs": [[g.id, g.cue_from, g.cue_to, g.speaker] for g in segs], "sents": sents}
    open("/tmp/raw.txt", "w").write(raw)
    out = subprocess.run(["node", "tools/parity/ts.mjs", "/tmp/raw.txt", ref.kind], capture_output=True, text=True)
    if out.returncode:
        report.append(f"ERR {r['title']}: {out.stderr[-300:]}"); bad += 1; continue
    ts = json.loads(out.stdout)
    diffs = []
    for key in ("cues", "segs", "sents"):
        a, b = py[key], ts[key]
        if len(a) != len(b): diffs.append(f"{key} len {len(a)} vs {len(b)}")
        for k, (x, y) in enumerate(zip(a, b)):
            if key == "cues":
                if x[:3] != y[:3] or abs(x[3] - y[3]) > 0.011: diffs.append(f"cue {k}: {x} | {y}"); break
            elif x != y: diffs.append(f"{key} {k}: {x} | {y}"); break
    if diffs: bad += 1; report.append(f"DIFF {r['title']} ({ref.kind}): " + " ; ".join(diffs)[:600])
    else: ok += 1; report.append(f"OK {r['title']} ({ref.kind}) cues={len(cues)} segs={len(segs)}")
print(f"::notice title=parity ok={ok} bad={bad}::" + " ### ".join(report)[:3900])
sys.exit(1 if bad else 0)
