import fs from 'node:fs';
import ts from 'typescript';
// transpile both modules next to the app's node_modules so 'htmlparser2' etc. resolve
fs.mkdirSync('app/.parity', { recursive: true });
for (const f of ['transcript', 'webTranscript']) {
  let js = ts.transpileModule(fs.readFileSync(`app/lib/${f}.ts`, 'utf8'), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
  js = js.replace(/from '\.\/transcript'/g, "from './transcript.mjs'");
  fs.writeFileSync(`app/.parity/${f}.mjs`, js);
}
const m = await import(process.cwd() + '/app/.parity/webTranscript.mjs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const out = m.pageSentences(html, process.argv[3]).map((x) => ({ t: x.t, spk: x.spk, fp: m.fp(x.t) }));
process.stdout.write(JSON.stringify(out));
