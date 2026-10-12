"""Probe 6: run the new alignment (ad-free mode, squeeze repair, ASR-grid interpolation) on the real
6 Minute English 'alcohol' episode and compare every cue with the wav2vec2 ground truth from probe 5
(tools/probe_result.json, content timeline → shifted by the old pre-roll). Also dumps the Whisper words so the
alignment can be iterated offline."""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests  # noqa: E402

from pipeline import fingerprint as F  # noqa: E402
from pipeline import webtranscript as W  # noqa: E402
from pipeline.align import align_paragraphs  # noqa: E402
from pipeline.sync import Asr  # noqa: E402

EP = "docs/data/episodes/bbc-6-minute-english-2026-10-08-are-people-drinking-less-alcohol.json"
PAGE = "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2026/ep-261008"


def main():
    t0 = time.time()
    doc = json.loads(Path(EP).read_text())
    old = json.loads(Path("tools/probe_result.json").read_text())
    pre_old = float(doc["audio_meta"]["alignment"].get("preroll_runner") or 0.0)
    ctc = {c["t"]: [c["ctc"][0] + pre_old, c["ctc"][1] + pre_old] for c in old.get("cues", [])}   # runner clock

    s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 podcast-study probe"
    html = W.fetch_page(s, PAGE)
    paras = W.parse_bbc_le(html)
    url = W.find_audio_link(html, PAGE) or doc["audio_url"]
    audio = Path("a.mp3"); audio.write_bytes(s.get(url, timeout=120).content)
    pcm16 = F.decode_pcm(audio, 16000)
    dur = len(pcm16) / 16000
    asr = Asr("base.en")
    words = asr.words(pcm16, 0.0, dur)
    cues, info = align_paragraphs(paras, words, dur, ad_free=True)

    rows, diffs = [], []
    for c in cues:
        g = ctc.get(c.t)
        d = round(c.s - g[0], 2) if g else None
        if d is not None:
            diffs.append(abs(d))
        rows.append({"i": c.i, "s": c.s, "e": c.e, "ctc": g and [round(g[0], 2), round(g[1], 2)], "d": d, "t": c.t[:70]})
    diffs.sort()
    out = {
        "probe": 6, "url": url, "duration": round(dur, 2), "info": info, "seconds": round(time.time() - t0, 1),
        "n": len(diffs), "median_abs": diffs[len(diffs) // 2] if diffs else None, "p90_abs": diffs[int(len(diffs) * 0.9)] if diffs else None,
        "max_abs": diffs[-1] if diffs else None, "over_1s": sum(1 for d in diffs if d > 1.0),
        "cues": rows, "words": [[w[0], round(w[1], 2), round(w[2], 2)] for w in words],
    }
    Path("tools/probe_result.json").write_text(json.dumps(out, ensure_ascii=False))
    print(json.dumps({k: v for k, v in out.items() if k not in ("cues", "words")}, ensure_ascii=False))
    for r in rows:
        if r["d"] is not None and abs(r["d"]) > 0.6:
            print(r)


if __name__ == "__main__":
    main()
