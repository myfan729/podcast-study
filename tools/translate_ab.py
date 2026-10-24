"""Translate the same lines with Sonnet and Haiku, print side by side (A/B for the translation model)."""
import json, sys, time
from pipeline.llm import StudyGenerator
f, start, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
cues = json.load(open(f))["transcript"]["cues"][start:start + n]
items = [(str(c["i"]), c["t"]) for c in cues]
res = {}
for name, model in (("sonnet", "claude-sonnet-5-5"), ("haiku", "claude-haiku-5-5")):
    t0 = time.time(); res[name] = StudyGenerator(translate_model=model).translate_items(items); res[name + "_sec"] = round(time.time() - t0, 1)
out = [f"{i}. {t}\n  S: {res['sonnet'].get(i,'(없음)')}\n  H: {res['haiku'].get(i,'(없음)')}" for i, t in items]
print(f"::notice title=time::sonnet {res['sonnet_sec']}s haiku {res['haiku_sec']}s")
buf = ""
for k, o in enumerate(out):
    if len(buf) + len(o) > 3500:
        print("::notice title=ab::" + buf.replace("\n", "%0A")); buf = ""
    buf += o + "\n"
if buf: print("::notice title=ab::" + buf.replace("\n", "%0A"))
