"""Probe 5: re-time the 6 Minute English 'alcohol' cues with wav2vec2 CTC forced alignment and compare
with the Whisper-based cue times stored in docs/data (ground-truth check for the reported sync gap)."""
import io, json, re, sys, time
from pathlib import Path

import numpy as np
import requests
import torch, torchaudio

EP = "docs/data/episodes/bbc-6-minute-english-2026-10-08-are-people-drinking-less-alcohol.json"


def decode_pcm(path, sr=16000):
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def norm_word(w):
    w = w.upper().replace("’", "'")
    w = re.sub(r"[^A-Z']", "", w)
    return w


def main():
    t0 = time.time()
    doc = json.loads(Path(EP).read_text())
    cues = doc["transcript"]["cues"]
    pre = doc["audio_meta"]["alignment"]["preroll_runner"]
    url = doc["audio_url"]
    audio = Path("a.mp3"); audio.write_bytes(requests.get(url, timeout=120).content)
    pcm = decode_pcm(audio)
    bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    model = bundle.get_model().eval()
    labels = bundle.get_labels()
    lab = {c: i for i, c in enumerate(labels)}
    blank = 0
    out = {"model": "WAV2VEC2_ASR_BASE_960H", "cues": [], "load_s": round(time.time() - t0, 1)}
    # chunk the file into 90 s windows; for each window take the cues whose whisper times fall inside (+margin)
    CH = 90.0
    results = {}
    n_chunks = int(np.ceil(len(pcm) / 16000 / CH))
    for k in range(n_chunks):
        a, b = k * CH, min(len(pcm) / 16000, (k + 1) * CH)
        # cues inside [a, b) in runner time (whisper estimate)
        sel = [c for c in cues if a <= c["s"] + pre < b]
        if not sel:
            continue
        # expand the audio window a little around the cue span to be safe
        wa = max(0.0, min(c["s"] + pre for c in sel) - 1.0); wb = min(len(pcm) / 16000, max(c["e"] + pre for c in sel) + 1.0)
        wav = torch.from_numpy(pcm[int(wa * 16000):int(wb * 16000)]).unsqueeze(0)
        with torch.inference_mode():
            emission, _ = model(wav)
        emission = torch.log_softmax(emission[0], dim=-1)
        # transcript tokens for the window
        words = []
        for c in sel:
            for w in c["t"].split():
                nw = norm_word(w)
                if nw:
                    words.append((c["i"], nw))
        if not words:
            continue
        chars = []
        spans = []  # (cue_i, start_idx, end_idx) in chars
        for ci, w in words:
            start = len(chars)
            chars.extend(lab[ch] for ch in w if ch in lab)
            spans.append((ci, start, len(chars)))
            chars.append(lab["|"])
        targets = torch.tensor([chars[:-1]], dtype=torch.int32)
        try:
            aligned, scores = torchaudio.functional.forced_align(emission.unsqueeze(0), targets, blank=blank)
        except Exception as e:  # noqa: BLE001
            out.setdefault("errors", []).append({"chunk": k, "error": str(e)[:200]})
            continue
        aligned = aligned[0].tolist()
        # frame → time: 20 ms per frame
        frame_sec = (wb - wa) / len(aligned)
        # map each target index to frames: walk aligned frames, counting non-blank, non-repeat tokens
        tok_frames = {}
        ti = -1; prev = None
        for f, t in enumerate(aligned):
            if t != blank and t != prev:
                ti += 1
                tok_frames.setdefault(ti, [f, f])
            if t != blank:
                if ti in tok_frames: tok_frames[ti][1] = f
            prev = t
        # per cue: first char frame of first word, last char frame of last word
        per_cue = {}
        for ci, s, e in spans:
            if s in tok_frames and (e - 1) in tok_frames:
                st = wa + tok_frames[s][0] * frame_sec; en = wa + tok_frames[e - 1][1] * frame_sec
                cur = per_cue.setdefault(ci, [st, en]); cur[0] = min(cur[0], st); cur[1] = max(cur[1], en)
        for ci, (st, en) in per_cue.items():
            results[ci] = (round(st - pre, 2), round(en - pre, 2))
    for c in cues:
        r = results.get(c["i"])
        out["cues"].append({"i": c["i"], "whisper": [c["s"], c["e"]], "ctc": r, "diff_start": round(r[0] - c["s"], 2) if r else None, "t": c["t"][:50]})
    out["seconds"] = round(time.time() - t0, 1)
    Path("tools/probe_result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "cues"}))
    for c in out["cues"]:
        print(c)


if __name__ == "__main__":
    sys.exit(main())
