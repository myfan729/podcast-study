/* Automatic ad-aware sync.
   The page downloads the publisher's stream once (with that download's own ads), plays it from memory,
   and aligns the transcript by fingerprinting the audio right after each ad break and matching it
   against reference fingerprints the pipeline computed from the ad-free content timeline.
   Fingerprint algorithm mirrors pipeline/fingerprint.py exactly. */
window.PodSync = (function () {
  'use strict';

  // ---------------- MP3 frame index: byte offset ↔ time ----------------
  const BITRATES = { 1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320], 2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160] };
  const SAMPLERATES = { 3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000] };

  function indexMp3(bytes) {
    const u = new Uint8Array(bytes);
    let pos = 0;
    if (u[0] === 0x49 && u[1] === 0x44 && u[2] === 0x33) {       // ID3v2
      const size = ((u[6] & 0x7f) << 21) | ((u[7] & 0x7f) << 14) | ((u[8] & 0x7f) << 7) | (u[9] & 0x7f);
      pos = 10 + size + ((u[5] & 0x10) ? 10 : 0);
    }
    const offsets = [], times = []; let t = 0, bad = 0;
    while (pos + 4 <= u.length) {
      if (u[pos] !== 0xff || (u[pos + 1] & 0xe0) !== 0xe0) { pos++; bad++; continue; }
      const b1 = u[pos + 1], b2 = u[pos + 2];
      const ver = (b1 >> 3) & 3, layer = (b1 >> 1) & 3;
      if (ver === 1 || layer !== 1) { pos++; bad++; continue; }            // Layer III only
      const brIdx = b2 >> 4, srIdx = (b2 >> 2) & 3, pad = (b2 >> 1) & 1;
      const br = BITRATES[ver === 3 ? 1 : 2][brIdx], sr = SAMPLERATES[ver] ? SAMPLERATES[ver][srIdx] : 0;
      if (!br || !sr) { pos++; bad++; continue; }
      const len = ver === 3 ? Math.floor(144000 * br / sr) + pad : Math.floor(72000 * br / sr) + pad;
      const samples = ver === 3 ? 1152 : 576;
      offsets.push(pos); times.push(t);
      t += samples / sr; pos += len;
    }
    return { offsets, times, duration: t, bad };
  }

  // ---------------- fingerprint (mirror of pipeline/fingerprint.py) ----------------
  const N_BANDS = 16, F_MIN = 300, F_MAX = 3000;
  function params(sr) {
    const nfft = Math.round(0.256 * sr), hop = Math.round(0.064 * sr);
    const edges = [];
    for (let i = 0; i <= N_BANDS; i++) edges.push(Math.floor(F_MIN * Math.pow(F_MAX / F_MIN, i / N_BANDS) * nfft / sr));
    return { nfft, hop, edges };
  }
  // iterative radix-2 FFT on interleaved re/im arrays (length must be a power of two)
  function fft(re, im) {
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1; for (; j & bit; bit >>= 1) j ^= bit; j ^= bit;
      if (i < j) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        for (let j = 0; j < len / 2; j++) {
          const a = i + j, b = a + len / 2;
          const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
          re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
          const ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
        }
      }
    }
  }
  function isPow2(n) { return (n & (n - 1)) === 0; }

  /** Fingerprint PCM (Float32Array at `sr`) with hop divided by `sub` (sub=2 → 32 ms steps for phase search). */
  function fingerprint(pcm, sr, sub) {
    const { nfft, hop, edges } = params(sr);
    if (!isPow2(nfft)) throw new Error('unsupported sample rate ' + sr);
    const step = Math.round(hop / (sub || 1));
    const win = new Float32Array(nfft);
    for (let i = 0; i < nfft; i++) win[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (nfft - 1));   // numpy.hanning
    const nFrames = Math.max(0, 1 + Math.floor((pcm.length - nfft) / step));
    const re = new Float64Array(nfft), im = new Float64Array(nfft);
    const L = new Float64Array(nFrames * N_BANDS);
    for (let f = 0; f < nFrames; f++) {
      const off = f * step;
      for (let i = 0; i < nfft; i++) { re[i] = pcm[off + i] * win[i]; im[i] = 0; }
      fft(re, im);
      for (let b = 0; b < N_BANDS; b++) {
        let e = 0; for (let k = edges[b]; k < edges[b + 1]; k++) e += re[k] * re[k] + im[k] * im[k];
        L[f * N_BANDS + b] = Math.log(e + 1e-9);
      }
    }
    // bits against the previous frame at the SAME hop as the reference (i.e. `sub` frames back)
    const bits = new Uint16Array(nFrames);
    for (let f = 0; f < nFrames; f++) {
      const p = f - (sub || 1); let v = 0;
      for (let m = 0; m < 15; m++) {
        const d = L[f * N_BANDS + m] - L[f * N_BANDS + m + 1];
        const dp = p >= 0 ? L[p * N_BANDS + m] - L[p * N_BANDS + m + 1] : d;
        if (d - dp > 0) v |= (1 << m);
      }
      bits[f] = v;
    }
    return { bits, step, stepSec: step / sr };
  }

  const POP = new Uint8Array(65536); for (let i = 1; i < 65536; i++) POP[i] = POP[i >> 1] + (i & 1);
  function ber(ref, probe, start, stride) {
    let bad = 0, n = 0;
    for (let i = 0; i < ref.length; i++) { const j = start + i * stride; if (j >= probe.length) break; bad += POP[ref[i] ^ probe[j]]; n++; }
    return n ? bad / (15 * n) : 1;
  }
  /** Slide `ref` (reference hop) over `probe` (reference hop / sub). Returns best probe index. */
  function bestMatch(ref, probe, sub) {
    let best = 1, bestAt = -1, second = 1;
    const maxStart = probe.bits.length - ref.length * sub;
    for (let s = 0; s <= maxStart; s++) {
      const e = ber(ref, probe.bits, s, sub);
      if (e < best) { if (bestAt >= 0 && Math.abs(s - bestAt) > 3 * sub) second = best; best = e; bestAt = s; }
      else if (e < second && Math.abs(s - bestAt) > 3 * sub) second = e;
    }
    return { at: bestAt, ber: best, second };
  }

  function b64ToU16(s) { const bin = atob(s); const out = new Uint16Array(bin.length >> 1); for (let i = 0; i < out.length; i++) out[i] = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8); return out; }

  // ---------------- decoding windows ----------------
  const decodeLog = [];     // which decoder path worked, for the diagnostics sheet
  function decodeWith(ctx, bytes) {   // promise- and callback-style decodeAudioData (older Safari)
    return new Promise((resolve, reject) => {
      let p = null;
      try { p = ctx.decodeAudioData(bytes, resolve, reject); } catch (e) { reject(e); return; }
      if (p && typeof p.then === 'function') p.then(resolve, reject);
    });
  }
  /** Low-pass + resample to 8 kHz (for browsers whose audio contexts only run at 44.1/48 kHz). */
  function resampleTo8k(pcm, sr) {
    const ratio = sr / 8000, half = Math.ceil(4 * ratio), fc = 3600 / sr;
    const taps = new Float32Array(2 * half + 1); let sum = 0;
    for (let i = -half; i <= half; i++) { const x = i === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * i) / (Math.PI * i); const w = 0.5 + 0.5 * Math.cos(Math.PI * i / half); taps[i + half] = x * w; sum += x * w; }
    for (let i = 0; i < taps.length; i++) taps[i] /= sum;
    const out = new Float32Array(Math.floor(pcm.length / ratio));
    for (let n = 0; n < out.length; n++) {
      const c = Math.round(n * ratio); let acc = 0;
      const k0 = Math.max(-half, -c), k1 = Math.min(half, pcm.length - 1 - c);
      for (let k = k0; k <= k1; k++) acc += pcm[c + k] * taps[k + half];
      out[n] = acc;
    }
    return out;
  }
  async function decodeBytes(bytes) {
    let lastErr = null;
    const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!Ctx) throw new Error('no OfflineAudioContext');
    for (const sr of [8000, 16000, 48000, 44100]) {
      let ctx;
      try { ctx = new Ctx(1, 1, sr); } catch (e) { lastErr = e; continue; }
      try {
        const buf = await decodeWith(ctx, bytes.slice(0));
        let pcm = buf.getChannelData(0), rate = buf.sampleRate;
        if (rate !== 8000 && rate !== 16000) { pcm = resampleTo8k(pcm, rate); rate = 8000; }
        if (decodeLog.length < 6) decodeLog.push('ctx' + sr + '→' + rate);
        return { pcm, sr: rate };
      } catch (e) { lastErr = e; }
    }
    throw new Error('decode failed: ' + (lastErr && lastErr.message || lastErr));
  }
  let wholeFile = null;   // {pcm, sr} — fallback when a browser refuses to decode a mid-stream slice
  async function decodeWindow(blob, index, startSec, endSec) {
    const times = index.times, offsets = index.offsets;
    if (!wholeFile) {
      try {
        let i0 = lowerBound(times, startSec), i1 = lowerBound(times, endSec);
        i0 = Math.max(0, i0 - 2); i1 = Math.min(offsets.length - 1, i1 + 1);  // frames of lead-in for the bit reservoir
        const d = await decodeBytes(await blob.slice(offsets[i0], offsets[i1]).arrayBuffer());
        return { pcm: d.pcm, sr: d.sr, startSec: times[i0] };
      } catch (e) {
        if (decodeLog.length < 6) decodeLog.push('slice failed: ' + (e.message || e));
        const d = await decodeBytes(await blob.arrayBuffer());   // whole file at 8 kHz: ~40 MB for 20 min
        wholeFile = { pcm: d.pcm, sr: d.sr };
        if (decodeLog.length < 6) decodeLog.push('whole file @' + d.sr);
      }
    }
    const a = Math.max(0, Math.floor(startSec * wholeFile.sr)), b = Math.min(wholeFile.pcm.length, Math.ceil(endSec * wholeFile.sr));
    return { pcm: wholeFile.pcm.subarray(a, b), sr: wholeFile.sr, startSec: a / wholeFile.sr };
  }
  function lowerBound(arr, x) { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < x) lo = m + 1; else hi = m; } return lo; }

  // ---------------- orchestration ----------------
  /**
   * @param blob      the downloaded audio
   * @param syncData  docs/data/sync/<id>.json: { refs: [{c, len, fp(b64)}], content_duration }
   * @param onStatus  progress callback(text)
   * @returns {anchors: [{c, a}], breaks: [...], report}
   */
  async function align(blob, syncData, onStatus, opts) {
    const t0 = performance.now(); wholeFile = null; decodeLog.length = 0;
    const slack = (opts && opts.slack) || 0;                   // extra seconds searched on both sides (fixed files)
    const index = indexMp3(await blob.slice(0, Math.min(blob.size, 64 * 1024 * 1024)).arrayBuffer());
    if (index.offsets.length < 100) throw new Error('not an MP3 stream (' + index.offsets.length + ' frames)');
    const fileDur = index.duration;
    const contentDur = syncData.content_duration;
    let budget = Math.max(0, fileDur - contentDur);           // total inserted ad time in this download
    let offset = 0;
    const anchors = [], report = { fileDur: +fileDur.toFixed(2), contentDur, adTotal: +budget.toFixed(2), fixed: !!syncData.fixed, refs: [], decode: decodeLog };
    const refs = (syncData.refs || []).slice().sort((x, y) => x.c - y.c);
    // playback can start as soon as everything up to where the listener resumes is aligned;
    // the rest is matched while it plays (opts.onPartial gets the anchors so far, once)
    const readyAt = (opts && opts.readyAt) || 0;
    let partialSent = !(opts && opts.onPartial);
    for (let k = 0; k < refs.length; k++) {
      const ref = refs[k]; const fp = b64ToU16(ref.fp);
      const expA = ref.c + offset;
      onStatus && onStatus(`자동 싱크 ${k + 1}/${refs.length}…`);
      // Most refs sit where nothing new was inserted since the last match: look right there first
      // (a few seconds of audio). Only if that fails, search the whole span an ad could push it to.
      const tries = [[Math.max(0, expA - 3), Math.min(fileDur, expA + ref.len + 3)],
                     [Math.max(0, expA - 2.5 - slack), Math.min(fileDur, expA + budget + ref.len + 6 + slack)]];
      if (k === 0 || slack) tries.shift();                      // the first ref (and fixed files) go straight to the wide search
      let r = { c: ref.c, ok: false };
      for (const [winStart, winEnd] of tries) {
        try {
          const w = await decodeWindow(blob, index, winStart, winEnd);
          const probe = fingerprint(w.pcm, w.sr, 2);
          const m = bestMatch(fp, probe, 2);
          r = { c: ref.c, ok: false, ber: +m.ber.toFixed(3), second: +m.second.toFixed(3), win: [+winStart.toFixed(1), +winEnd.toFixed(1)], sr: w.sr };
          if (m.at >= 0 && m.ber < 0.33 && m.second - m.ber > 0.04) {
            const a = w.startSec + m.at * probe.stepSec;
            const newOffset = a - ref.c;
            r.a = +a.toFixed(3); r.offset = +newOffset.toFixed(3); r.ok = true;
            if (k === 0 || Math.abs(newOffset - offset) > 0.5) anchors.push({ c: ref.c, a });
            budget = Math.max(0, budget - Math.max(0, newOffset - offset)); offset = newOffset;
            break;
          }
        } catch (e) { r.error = String(e && e.message || e); }
      }
      report.refs.push(r);
      if (!partialSent && anchors.length && (k === refs.length - 1 || refs[k + 1].c > readyAt + 30)) {
        partialSent = true;
        report.partialMs = Math.round(performance.now() - t0);
        opts.onPartial(anchors.slice());
      }
    }
    report.ms = Math.round(performance.now() - t0);
    return { anchors, report, index };
  }

  /**
   * Refine a listener's tap: look for reference `ref` within ±radius s of `approxA` (audio seconds).
   * The search space is tiny, so a slightly looser threshold than align() is safe.
   */
  async function alignLocal(blob, index, ref, approxA, radius) {
    const fp = b64ToU16(ref.fp);
    const winStart = Math.max(0, approxA - radius - 1), winEnd = Math.min(index.duration, approxA + radius + ref.len + 1);
    const w = await decodeWindow(blob, index, winStart, winEnd);
    const probe = fingerprint(w.pcm, w.sr, 2);
    const m = bestMatch(fp, probe, 2);
    const ok = m.at >= 0 && (m.ber < 0.30 || (m.ber < 0.36 && m.second - m.ber > 0.03));
    return { ok, a: ok ? w.startSec + m.at * probe.stepSec : null, ber: +m.ber.toFixed(3), second: +m.second.toFixed(3) };
  }

  /**
   * Re-wrap the audio as 16-bit PCM WAV. Safari (all iOS browsers) times VBR MP3 playback from byte
   * positions, so currentTime can be seconds off the sound actually playing; uncompressed audio has no
   * such ambiguity. Mono at `rate` Hz (22.05 kHz ≈ 2.6 MB per minute).
   */
  async function toWav(blob, rate) {
    const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const bytes = await blob.arrayBuffer();
    let buf = null, lastErr = null;
    for (const sr of [rate || 22050, 24000, 16000, 44100, 48000]) {
      try { buf = await decodeWith(new Ctx(1, 1, sr), bytes.slice(0)); break; } catch (e) { lastErr = e; }
    }
    if (!buf) throw new Error('wav decode failed: ' + (lastErr && lastErr.message || lastErr));
    const n = buf.length, sr = buf.sampleRate, ch = buf.numberOfChannels;
    const out = new ArrayBuffer(44 + n * 2), v = new DataView(out), pcm = new Int16Array(out, 44);
    const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVE'); w(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, n * 2, true);
    const chans = []; for (let c = 0; c < ch; c++) chans.push(buf.getChannelData(c));
    for (let i = 0; i < n; i++) { let s = 0; for (let c = 0; c < ch; c++) s += chans[c][i]; s /= ch; pcm[i] = s <= -1 ? -32768 : s >= 1 ? 32767 : (s * 32767) | 0; }
    return { blob: new Blob([out], { type: 'audio/wav' }), sr, seconds: n / sr };
  }

  /** Download with progress; resolves to a Blob. */
  async function download(url, onProgress) {
    const res = await fetch(url, { mode: 'cors', credentials: 'omit' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const total = +res.headers.get('content-length') || 0;
    const reader = res.body.getReader(); const chunks = []; let got = 0;
    for (;;) { const { done, value } = await reader.read(); if (done) break; chunks.push(value); got += value.length; onProgress && onProgress(got, total); }
    return new Blob(chunks, { type: res.headers.get('content-type') || 'audio/mpeg' });
  }

  return { indexMp3, fingerprint, bestMatch, decodeWindow, align, alignLocal, download, toWav, b64ToU16, ber, resampleTo8k };
})();
