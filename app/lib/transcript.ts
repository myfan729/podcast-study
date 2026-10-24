// The publisher's transcript, fetched and parsed on the phone. Our server never stores the text:
// it keeps only the study notes and timing, and this file rebuilds the same sentences and paragraphs
// the server used (a line-for-line port of pipeline/transcript.py, so segment ids like "s12" match).
export type TCue = { i: number; s: number; e: number; t: string; spk: string | null };
export type TSegment = { id: string; start: number; end: number; speaker: string | null; cue_from: number; cue_to: number };
export type Transcript = { cues: TCue[]; segments: TSegment[]; sentences: [number, number][] };

const TIMESTAMP_RE = /^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})$/;
const CUE_LINE_RE = /^\s*((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})/;
const VOICE_TAG_RE = /<v(?:\.[^\s>]*)?\s+([^>]*)>/i;
const TAG_RE = /<\/?[a-zA-Z][^>]*>/g;
const SPEAKER_PREFIX_RE = /^\s*([A-Z][A-Za-z0-9 .'\-]{0,40}?):\s+(?=\S)/;
const SENTENCE_END_RE = /[.!?]['")\]]?$/;
const SENT_END_RE = /[.!?…]["'”’)\]]*$/;
const END_RE = /(?:[.!?]|…|\.\.\.)["'”’)\]]*$/;
const CLOSERS = `"'”’)]`;
const MAX_SENTENCE_WORDS = 70;
const ABBREV = new Set(['mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs', 'etc', 'e.g', 'i.e', 'inc', 'corp', 'co',
  'ltd', 'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec', 'no',
  'fig', 'approx', 'dept', 'gov', 'gen', 'sen', 'rep', 'rev', 'mt', 'ft', 'u.s', 'u.k', 'u.n', 'e.u',
  'a.m', 'p.m', 'd.c']);

const words = (s: string) => s.split(/\s+/).filter(Boolean);
const rstripChars = (s: string, chars: string) => { let k = s.length; while (k > 0 && chars.includes(s[k - 1])) k--; return s.slice(0, k); };
const lstripChars = (s: string, chars: string) => { let k = 0; while (k < s.length && chars.includes(s[k])) k++; return s.slice(k); };
const stripChars = (s: string, chars: string) => lstripChars(rstripChars(s, chars), chars);
const isUpper = (ch: string) => ch !== ch.toLowerCase() && ch === ch.toUpperCase();
const isDigit = (ch: string) => /\d/.test(ch);

function parseTimestamp(raw: string): number {
  const m = TIMESTAMP_RE.exec(raw.trim());
  if (!m) throw new Error('bad timestamp ' + raw);
  const ms = (m[4] + '000').slice(0, 3);
  return Number(m[1] ?? 0) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Number(ms) / 1000;
}

export function cleanText(text: string): string {
  let t = text.replace(TAG_RE, '');
  t = t.replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
  t = t.replace(/\s+/g, ' ').trim();
  t = t.replace(/\$\s+(\d)/g, '$$$1');
  t = t.replace(/(\d)\.\s+(\d{2}\b)/g, '$1.$2');
  t = t.replace(/\s+([,.;:?!])/g, '$1');
  return t;
}

function extractSpeaker(text: string, allowPrefix: boolean): [string | null, string] {
  const v = VOICE_TAG_RE.exec(text);
  if (v) return [v[1].trim() || null, text];
  if (allowPrefix) {
    const m = SPEAKER_PREFIX_RE.exec(text);
    if (m && !/^\d/.test(m[1])) return [m[1].trim(), text.slice(m[0].length)];
  }
  return [null, text];
}

function parseVtt(text: string, speakerPrefix = true): TCue[] {
  const lines = text.replace(/^﻿+/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const cues: TCue[] = [];
  let i = 0; const n = lines.length;
  while (i < n) {
    const m = CUE_LINE_RE.exec(lines[i]);
    if (!m) { i++; continue; }
    const start = parseTimestamp(m[1]), end = parseTimestamp(m[2]);
    i++;
    const body: string[] = [];
    while (i < n && lines[i].trim() !== '') {
      if (CUE_LINE_RE.test(lines[i])) break;
      if (/^\d+$/.test(lines[i].trim()) && i + 1 < n && CUE_LINE_RE.test(lines[i + 1])) break;
      body.push(lines[i]); i++;
    }
    const [spk, raw] = extractSpeaker(body.join(' '), speakerPrefix);
    const t = cleanText(raw);
    if (t) cues.push({ i: cues.length, s: start, e: Math.max(end, start), t, spk });
  }
  return cues;
}

function parseJson(text: string): TCue[] {
  const data = JSON.parse(text);
  const segs = data && !Array.isArray(data) && typeof data === 'object' ? data.segments : data;
  const cues: TCue[] = [];
  for (const seg of segs ?? []) {
    const body = cleanText(String(seg.body || seg.text || ''));
    if (!body) continue;
    const s = Number(('startTime' in seg ? seg.startTime : seg.start ?? 0) || 0);
    const e = Number(('endTime' in seg ? seg.endTime : seg.end ?? s) || s);
    cues.push({ i: cues.length, s, e: Math.max(e, s), t: body, spk: seg.speaker || null });
  }
  return cues;
}

const LINE_TS_RE = /^\s*(?:([A-Z][A-Za-z0-9 .'\-]{0,40}?)\s*)?[\[(]?((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)[\])]?\s*[:\-–]?\s*(.+)$/;
function parseTimestampedText(text: string): TCue[] {
  const cues: TCue[] = [];
  for (const line of text.replace(/\r/g, '').split('\n')) {
    const m = LINE_TS_RE.exec(line);
    if (!m) continue;
    let ts = m[2]; if (!/[.,]\d/.test(ts)) ts += '.000';
    let s: number; try { s = parseTimestamp(ts); } catch { continue; }
    const t = cleanText(m[3]);
    if (t) cues.push({ i: cues.length, s, e: s, t, spk: (m[1] ?? '').trim() || null });
  }
  for (let k = 0; k + 1 < cues.length; k++) cues[k].e = Math.max(cues[k].s, cues[k + 1].s);
  if (cues.length) { const l = cues[cues.length - 1]; l.e = l.s + Math.max(2, words(l.t).length / 2.5); }
  return cues;
}

export function parseTranscript(text: string, kind: string): TCue[] {
  const k = (kind || '').toLowerCase();
  if (k === 'json') return parseJson(text);
  if (['vtt', 'srt', 'unknown', 'html'].includes(k)) { const c = parseVtt(text); if (c.length) return c; }
  if (k === 'text' || k === 'unknown') return parseTimestampedText(text);
  const c = parseVtt(text); return c.length ? c : parseTimestampedText(text);
}

const round3 = (x: number) => Math.round(x * 1000) / 1000;

function endsSentence(tok: string, nxt: string | null): boolean {
  if (!END_RE.test(tok)) return false;
  const bare = rstripChars(tok, CLOSERS);
  if (bare.endsWith('.') && !bare.endsWith('..')) {
    const core = lstripChars(bare.slice(0, -1).toLowerCase(), `"'“‘(`);
    if (ABBREV.has(core) || /^[a-z]$/.test(core) || /^(?:[a-z]\.)+[a-z]$/.test(core)) return false;
  }
  if (nxt === null) return true;
  const first = lstripChars(nxt, `"'“‘(`);
  return !!first && (isUpper(first[0]) || isDigit(first[0]));
}

type W = [string, number, number, string | null];
function splitLong(ws: W[]): W[][] {
  if (ws.length <= MAX_SENTENCE_WORDS) return [ws];
  const mid = Math.floor(ws.length / 2);
  const cuts: number[] = [];
  for (let k = 8; k < ws.length - 8; k++) if (',;:—–'.includes(rstripChars(ws[k][0], CLOSERS).slice(-1))) cuts.push(k);
  let k = mid;
  if (cuts.length) { k = cuts[0]; for (const c of cuts) if (Math.abs(c - mid) < Math.abs(k - mid)) k = c; }
  return [...splitLong(ws.slice(0, k + 1)), ...splitLong(ws.slice(k + 1))];
}

/** Publisher caption lines → one cue per sentence (see sentence_cues in pipeline/transcript.py). */
export function sentenceCues(cues: TCue[], mergeShort = 2): TCue[] {
  const ws: W[] = [];
  for (const c of cues) {
    const toks = words(c.t); if (!toks.length) continue;
    const dur = Math.max(0.05, c.e - c.s);
    const weights = toks.map((t) => t.length + 1);
    const total = weights.reduce((a, b) => a + b, 0); let acc = 0;
    toks.forEach((t, j) => { const s0 = c.s + dur * acc / total; acc += weights[j]; ws.push([t, s0, c.s + dur * acc / total, c.spk]); });
  }
  const sents: W[][] = []; let cur: W[] = [];
  ws.forEach((w, k) => {
    cur.push(w);
    const nxt = k + 1 < ws.length ? ws[k + 1] : null;
    if (nxt === null || (nxt[3] || null) !== (w[3] || null) || endsSentence(w[0], nxt[0])) { sents.push(cur); cur = []; }
  });
  const merged: W[][] = []; let carry: W[] = [];
  sents.forEach((s0, k) => {
    const s = [...carry, ...s0]; carry = [];
    const nxt = k + 1 < sents.length ? sents[k + 1] : null;
    if (s.length <= mergeShort && nxt && (nxt[0][3] || null) === (s[0][3] || null)) { carry = s; return; }
    merged.push(s);
  });
  if (carry.length) merged.push(carry);
  const out: TCue[] = [];
  for (const s of merged) for (const part of splitLong(s)) {
    out.push({ i: out.length, s: round3(part[0][1]), e: round3(part[part.length - 1][2]), t: part.map((w) => w[0]).join(' '), spk: part[0][3] });
  }
  return out;
}

function normalizeSpeakers(cues: TCue[]) {
  for (const c of cues) {
    if (!c.spk) continue;
    const spk = stripChars(c.spk.replace(/\s+/g, ' '), ' :');
    const m = /^speaker\s*(\d+)$/i.exec(spk);
    c.spk = m ? `Speaker ${m[1]}` : spk;
  }
}

export function segmentCues(cues: TCue[], targetWords = 70, maxWords = 120, gapBreak = 1.6): TSegment[] {
  normalizeSpeakers(cues);
  const segs: TSegment[] = []; let buf: TCue[] = [];
  const flush = () => {
    if (!buf.length) return;
    segs.push({ id: `s${segs.length + 1}`, start: buf[0].s, end: buf[buf.length - 1].e, speaker: buf[0].spk, cue_from: buf[0].i, cue_to: buf[buf.length - 1].i });
    buf = [];
  };
  for (const c of cues) {
    if (buf.length) {
      const prev = buf[buf.length - 1];
      const w = buf.reduce((a, x) => a + words(x.t).length, 0);
      const prevEnds = SENTENCE_END_RE.test(prev.t);
      if ((c.spk || null) !== (prev.spk || null)) flush();
      else if (prevEnds && c.s - prev.e > gapBreak) flush();
      else if (prevEnds && w >= targetWords) flush();
      else if (w >= maxWords && (prevEnds || w >= maxWords + 40)) flush();
    }
    buf.push(c);
  }
  flush();
  return segs;
}

export function groupSentences(cues: TCue[], segs: TSegment[], maxWords = 45): [number, number][] {
  const bounds = new Set(segs.map((s) => s.cue_from));
  const out: [number, number][] = []; let start: number | null = null, w = 0;
  cues.forEach((c, idx) => {
    const nxt = idx + 1 < cues.length ? cues[idx + 1] : null;
    if (start === null) { start = c.i; w = 0; }
    w += words(c.t).length;
    let ends = SENT_END_RE.test(c.t.trim()) || nxt === null || w >= maxWords;
    if (nxt && !ends && ((nxt.spk || null) !== (c.spk || null) || bounds.has(nxt.i))) ends = true;
    if (ends) { out.push([start, c.i]); start = null; }
  });
  return out;
}

/** Everything the study screen needs, from the publisher's raw transcript file. */
export function buildTranscript(raw: string, kind: string): Transcript {
  const cues = sentenceCues(parseTranscript(raw, kind));
  const segments = segmentCues(cues);
  return { cues, segments, sentences: groupSentences(cues, segments) };
}

/** Download and parse on the phone (cached for the session). */
const cache = new Map<string, Promise<Transcript>>();
export function fetchTranscript(url: string, kind: string): Promise<Transcript> {
  const k = kind + '|' + url;
  let p = cache.get(k);
  if (!p) {
    p = fetch(url, { headers: { Accept: '*/*' } }).then(async (r) => {
      if (!r.ok) throw new Error(`대본을 받지 못했어요 (${r.status})`);
      const t = buildTranscript(await r.text(), kind);
      if (t.cues.length < 10) throw new Error('대본 형식을 읽지 못했어요');
      return t;
    });
    p.catch(() => cache.delete(k));
    cache.set(k, p);
  }
  return p;
}
