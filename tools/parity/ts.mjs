import fs from 'node:fs';
import ts from 'typescript';
const src = fs.readFileSync('app/lib/transcript.ts', 'utf8');
const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
fs.writeFileSync('/tmp/transcript.mjs', js);
const m = await import('/tmp/transcript.mjs');
const raw = fs.readFileSync(process.argv[2], 'utf8');
const t = m.buildTranscript(raw, process.argv[3]);
process.stdout.write(JSON.stringify({
  cues: t.cues.map((c) => [c.i, c.t, c.spk, Math.round(c.s * 100) / 100]),
  segs: t.segments.map((g) => [g.id, g.cue_from, g.cue_to, g.speaker]),
  sents: t.sentences,
}));
