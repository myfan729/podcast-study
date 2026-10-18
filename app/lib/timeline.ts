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
  let next: Anchor | undefined;
  for (const an of anchors) { if (an.a <= a + 0.01) off = an.a - an.c; else { next = an; break; } }
  // inside an ad break: the transcript clock stops at the break (holds the sentence before it)
  // instead of running on into the next stretch, which would highlight sentences nobody is saying
  if (next && a - off >= next.c) return next.c - 0.05;
  return a - off;
}
/** Is this audio position inside an inserted ad (between the end of one stretch and the next anchor)? */
export function inAd(a: number, anchors: Anchor[]): boolean {
  let off = anchors.length ? anchors[0].a - anchors[0].c : 0;
  for (const an of anchors) { if (an.a <= a + 0.01) off = an.a - an.c; else return a - off >= an.c; }
  return false;
}
export function addAnchor(anchors: Anchor[], c: number, a: number): Anchor[] {
  // replace anchors in the same stretch (within 20 s of content time) and keep them sorted
  const rest = anchors.filter((x) => Math.abs(x.c - c) > 20);
  return [...rest, { c, a }].sort((x, y) => x.c - y.c);
}
