// Transcripts that live only on the publisher's web page (NPR, BBC Learning English, SBS).
// The phone downloads the page and reads the transcript out of it — a line-for-line port of
// pipeline/webtranscript.py + align.split_sentences, kept identical by the parity check. Our server
// stores only each sentence's time and a short fingerprint ("timing"), never the text.
import { parseDocument } from 'htmlparser2';
import { decodeHTML } from 'entities';
import type { AnyNode, Element } from 'domhandler';
import { endsSentence, groupSentences, segmentCues, type TCue, type Transcript } from './transcript';

export type Para = { speaker: string; text: string };

const isTag = (n: AnyNode): n is Element => n.type === 'tag' || n.type === 'script' || n.type === 'style';
const isText = (n: AnyNode) => n.type === 'text' || n.type === 'cdata';
const nameOf = (n: AnyNode) => (isTag(n) ? n.name.toLowerCase() : '');

/** BeautifulSoup get_text(sep): every text string below the node, joined with sep. */
function getText(n: AnyNode, sep = ' '): string {
  const out: string[] = [];
  const walk = (x: AnyNode) => {
    if (isText(x)) { out.push((x as any).data as string); return; }
    if (isTag(x) && x.type === 'tag') x.children.forEach(walk);
  };
  walk(n);
  return out.join(sep);
}
/** all elements in document order (pre-order), like soup.find_all */
function allElements(root: AnyNode): Element[] {
  const out: Element[] = [];
  const walk = (x: AnyNode) => { if (isTag(x)) { out.push(x); } if ('children' in x && Array.isArray((x as any).children)) (x as any).children.forEach(walk); };
  walk(root);
  return out;
}

export function clean(s: string): string {
  let t = s.replace(/ /g, ' ');
  t = t.replace(/[ \t]+/g, ' ');
  t = t.replace(/\s+([,.;:?!])/g, '$1');
  return t.trim();
}

const SPEAKER_RE = /^[A-Z][A-Za-z.'\-]{1,20}(?: [A-Z][A-Za-z.'\-]{1,20}){0,2}$/;

function parseBbcLe(html: string): Para[] {
  const doc = parseDocument(html);
  const els = allElements(doc);
  const heads = new Set(['p', 'h2', 'h3', 'h4']);
  const markerIdx = els.findIndex((e) => heads.has(nameOf(e)) && /^transcript[:.]?$/i.test(clean(getText(e, ' '))));
  if (markerIdx < 0) throw new Error('no TRANSCRIPT marker found');
  const paras: Para[] = [];
  let speaker = '';
  const buf: string[] = [];
  const flush = () => {
    const text = clean(buf.join(' ')); buf.length = 0;
    if (text && !/not a word-for-word transcript/i.test(text) && !/^note:/i.test(text)) paras.push({ speaker, text });
  };
  for (const node of els.slice(markerIdx + 1)) {
    if (!heads.has(nameOf(node))) continue;
    if (nameOf(node) !== 'p') { if (paras.length) break; continue; }
    const txt = clean(getText(node, ' '));
    if (!txt) continue;
    if (paras.length && (/^what do you think of/i.test(txt) || /^(find|try|practise|download)\b/i.test(txt))) break;
    const children = node.children;
    children.forEach((child, idx) => {
      if (isText(child) || child.type === 'comment') buf.push((child as any).data as string);
      else if (nameOf(child) === 'br') buf.push(' ');
      else if (nameOf(child) === 'strong' || nameOf(child) === 'b') {
        const label = clean(getText(child, ' '));
        const nxt = children.slice(idx + 1).find((c) => !((isText(c) || c.type === 'comment') && !((c as any).data as string).trim()));
        const onOwnLine = nxt === undefined || nameOf(nxt) === 'br';
        if (label && SPEAKER_RE.test(label) && onOwnLine && !/^transcript$/i.test(label)) { flush(); speaker = label; }
        else buf.push(' ' + label + ' ');
      } else if (isTag(child)) buf.push(getText(child, ' '));
    });
    flush();
  }
  if (paras.length < 4) throw new Error(`transcript too short (${paras.length} paragraphs)`);
  return paras;
}

const NPR_SPEAKER_RE = /^((?:[A-ZÀ-Ý][A-ZÀ-Ý.'\-]*|\d+)(?: (?:[A-ZÀ-Ý][A-ZÀ-Ý.'\-]*|\d+)){0,3})(?:, [A-ZÀ-Ý][A-ZÀ-Ý ,.'\-]*?)?:(?:\s+|$)/;
const NPR_STAGE_RE = /[\[(](?:SOUNDBITE|SOUND|MUSIC|COIN|LAUGHTER|CROSSTALK|APPLAUSE|BEGIN|END|SPEAKING|NON-ENGLISH|FOREIGN|PH\)|INAUDIBLE)[^\])]*[\])]/gi;

/** Python str.title(): a letter after a cased letter is lowered, otherwise raised. */
function pyTitle(s: string): string {
  let out = '', prev = false;
  for (const ch of s) {
    const cased = ch.toLowerCase() !== ch.toUpperCase();
    out += cased ? (prev ? ch.toLowerCase() : ch.toUpperCase()) : ch;
    prev = cased;
  }
  return out;
}
function ownText(p: Element): string {
  const out: string[] = [];
  for (const n of p.children) {
    if (isText(n) || n.type === 'comment') out.push((n as any).data as string);
    else if (isTag(n) && nameOf(n) !== 'p') out.push(getText(n, ' '));
  }
  return clean(out.join(' '));
}
function parseNpr(html: string): Para[] {
  const doc = parseDocument(html);
  const box = allElements(doc).find((e) => nameOf(e) === 'div' && (e.attribs.class ?? '').split(/\s+/).includes('transcript'));
  if (!box) throw new Error('no transcript on the page yet');
  const paras: Para[] = [];
  let speaker = '';
  for (const p of allElements(box).filter((e) => e !== box && nameOf(e) === 'p')) {
    let txt = ownText(p);
    if (!txt || /^(copyright ©|accuracy and availability of npr transcripts)/i.test(txt)) continue;
    txt = clean(txt.replace(NPR_STAGE_RE, ' '));
    const m = NPR_SPEAKER_RE.exec(txt);
    if (m) { speaker = pyTitle(m[1]); txt = txt.slice(m[0].length); }
    txt = clean(txt);
    if (txt) paras.push({ speaker, text: txt });
  }
  if (paras.reduce((a, x) => a + x.text.split(/\s+/).filter(Boolean).length, 0) < 150) throw new Error('transcript not published yet');
  const full = new Set(paras.filter((x) => x.speaker.includes(' ')).map((x) => x.speaker));
  for (const x of paras) {
    if (x.speaker && !x.speaker.includes(' ')) {
      const m = [...full].filter((f) => f.endsWith(' ' + x.speaker));
      if (m.length === 1) x.speaker = m[0];
    }
  }
  return paras;
}

/** the JSON string literal that starts at html[at] (a '"'), decoded */
function jsonStringAt(html: string, at: number): string {
  let k = at + 1;
  while (k < html.length) {
    const c = html[k];
    if (c === '\\') { k += 2; continue; }
    if (c === '"') break;
    k++;
  }
  return JSON.parse(html.slice(at, k + 1));
}
const SPLITLINES = /\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/;
function parseSbs(html: string): Para[] {
  const m = /"transcript"\s*:\s*"/.exec(html);
  if (!m) throw new Error('no transcript on the page yet');
  const text = decodeHTML(jsonStringAt(html, m.index + m[0].length - 1));
  const paras: Para[] = [];
  const names: Record<string, string> = {};
  for (const raw of text.split(SPLITLINES)) {
    let line = clean(raw);
    const mm = /^(spk_\d+)\s*:\s*(.*)$/.exec(line);
    let spk: string;
    if (mm) { if (!(mm[1] in names)) names[mm[1]] = `Speaker ${Object.keys(names).length + 1}`; spk = names[mm[1]]; line = mm[2]; }
    else spk = paras.length ? paras[paras.length - 1].speaker : '';
    if (line) paras.push({ speaker: spk, text: line });
  }
  if (paras.reduce((a, x) => a + x.text.split(/\s+/).filter(Boolean).length, 0) < 120) throw new Error('transcript too short / not published yet');
  return paras;
}

function parseGeneric(html: string): Para[] {
  const doc = parseDocument(html);
  let best: Element[] | null = null, bestLen = 0;
  for (const div of allElements(doc).filter((e) => ['div', 'article', 'section', 'main'].includes(nameOf(e)))) {
    const ps = div.children.filter((c): c is Element => nameOf(c) === 'p');
    const n = ps.reduce((a, p) => a + clean(getText(p, ' ')).length, 0);
    if (n > bestLen) { best = ps; bestLen = n; }
  }
  const paras = (best ?? []).map((p) => ({ speaker: '', text: clean(getText(p, ' ')) })).filter((x) => x.text);
  if (paras.length < 3) throw new Error('no transcript-like block');
  return paras;
}

const PARSERS: Record<string, (h: string) => Para[]> = { bbc_le: parseBbcLe, npr: parseNpr, sbs: parseSbs, generic: parseGeneric };
export function parseParagraphs(html: string, parser: string): Para[] {
  return (PARSERS[parser || 'generic'] ?? parseGeneric)(html);
}

/** align.split_sentences: same sentence ends as the RSS path; 1–2 word fragments join the previous one */
export function splitSentences(text: string): string[] {
  const toks = text.split(/\s+/).filter(Boolean);
  const parts: string[] = []; let cur: string[] = [];
  toks.forEach((tok, k) => { cur.push(tok); if (endsSentence(tok, k + 1 < toks.length ? toks[k + 1] : null)) { parts.push(cur.join(' ')); cur = []; } });
  if (cur.length) parts.push(cur.join(' '));
  const out: string[] = [];
  for (const p of parts) {
    if (out.length && p.split(/\s+/).filter(Boolean).length <= 2) out[out.length - 1] += ' ' + p;
    else out.push(p);
  }
  return out;
}

/** short fingerprint of a sentence (same as pipeline: FNV-1a over its lowercase letters/digits) */
export function fp(text: string): string {
  const s = text.toLowerCase().replace(/[^a-z0-9]/g, '');
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, '0');
}

export function pageSentences(html: string, parser: string): { t: string; spk: string | null }[] {
  const out: { t: string; spk: string | null }[] = [];
  for (const p of parseParagraphs(html, parser)) for (const s of splitSentences(p.text)) out.push({ t: s, spk: p.speaker || null });
  return out;
}

/** Page sentences + the server's timing ([start, end, fingerprint] per sentence) → the study transcript.
 *  Sentences are matched by fingerprint (the page may have been edited a little since); the few that
 *  don't match get times between their neighbours. */
export function webTranscript(html: string, parser: string, timing: [number, number, string][]): Transcript {
  const sents = pageSentences(html, parser);
  const n = sents.length, m = timing.length;
  const a = sents.map((x) => fp(x.t)), b = timing.map((x) => x[2]);
  let at: number[] = new Array(n).fill(-1);
  if (n === m && a.every((h, i) => h === b[i])) at = a.map((_, i) => i);
  else {
    // longest common subsequence of fingerprints
    const L = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0;
    while (i < n && j < m) { if (a[i] === b[j]) { at[i] = j; i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) i++; else j++; }
  }
  const matched = at.filter((x) => x >= 0).length;
  if (matched < Math.max(5, n * 0.6)) throw new Error('방송사 페이지의 대본이 바뀌어 싱크를 맞출 수 없어요');
  const cues: TCue[] = sents.map((x, i) => ({ i, s: 0, e: 0, t: x.t, spk: x.spk }));
  for (let i = 0; i < n; i++) if (at[i] >= 0) { cues[i].s = timing[at[i]][0]; cues[i].e = timing[at[i]][1]; }
  // unmatched runs: spread between the neighbours
  for (let i = 0; i < n; i++) {
    if (at[i] >= 0) continue;
    let j = i; while (j < n && at[j] < 0) j++;
    const t0 = i > 0 ? cues[i - 1].e : (j < n ? Math.max(0, cues[j].s - 3 * (j - i)) : 0);
    const t1 = j < n ? cues[j].s : t0 + 3 * (j - i);
    const step = (t1 - t0) / (j - i);
    for (let k = i; k < j; k++) { cues[k].s = t0 + step * (k - i); cues[k].e = t0 + step * (k - i + 1); }
    i = j;
  }
  const segments = segmentCues(cues);
  return { cues, segments, sentences: groupSentences(cues, segments) };
}

const pages = new Map<string, Promise<string>>();
export function fetchPage(url: string): Promise<string> {
  let p = pages.get(url);
  if (!p) {
    p = fetch(url, { headers: { Accept: 'text/html' } }).then((r) => { if (!r.ok) throw new Error(`방송사 페이지를 열지 못했어요 (${r.status})`); return r.text(); });
    p.catch(() => pages.delete(url));
    pages.set(url, p);
  }
  return p;
}
