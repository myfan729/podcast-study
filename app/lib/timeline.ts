// Content time (transcript clock, ads removed) ↔ audio time (the file this listener streams, ads included).
// Dynamic ads differ per listener, so the mapping comes from anchors: (c, a) pairs set automatically or by
// the listener ("싱크": tap the sentence you hear now). Between anchors the offset of the previous one holds.
export type Anchor = { c: number; a: number };

export function toAudio(c: number, anchors: Anchor[]): number {
  let off = anchors.length ? anchors[0].a - anchors[0].c : 0;
  for (const an of anchors) { if (an.c <= c + 0.01) off = an.a - an.c; else break; }
  return Math.max(0, c + off);
}
export function toContent(a: number, anchors: Anchor[]): number {
  let off = anchors.length ? anchors[0].a - anchors[0].c : 0;
  for (const an of anchors) { if (an.a <= a + 0.01) off = an.a - an.c; else break; }
  return a - off;
}
export function addAnchor(anchors: Anchor[], c: number, a: number): Anchor[] {
  // replace anchors in the same stretch (within 20 s of content time) and keep them sorted
  const rest = anchors.filter((x) => Math.abs(x.c - c) > 20);
  return [...rest, { c, a }].sort((x, y) => x.c - y.c);
}
