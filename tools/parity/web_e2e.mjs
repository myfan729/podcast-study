import fs from 'node:fs';
import ts from 'typescript';
fs.mkdirSync('app/.parity', { recursive: true });
for (const f of ['transcript', 'webTranscript']) {
  let js = ts.transpileModule(fs.readFileSync(`app/lib/${f}.ts`, 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
  fs.writeFileSync(`app/.parity/${f}.mjs`, js.replace(/from '\.\/transcript'/g, "from './transcript.mjs'"));
}
const m = await import(process.cwd() + '/app/.parity/webTranscript.mjs');
const pack = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const html = await (await fetch(pack.transcript.url, { headers: { 'User-Agent': 'Mozilla/5.0' } })).text();
const sents = m.pageSentences(html, pack.transcript.parser);
const t = m.webTranscript(html, pack.transcript.parser, pack.transcript.timing);
const exact = sents.filter((x, i) => pack.transcript.timing[i] && m.fp(x.t) === pack.transcript.timing[i][2]).length;
console.log(`sentences=${t.cues.length} exact=${exact}/${pack.transcript.timing.length} segs=${t.segments.length} first="${t.cues[2]?.t.slice(0, 40)}"@${t.cues[2]?.s}`);
