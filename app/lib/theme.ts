// 잉팟 look: soft periwinkle ground, white rounded cards, one violet accent, Jua for Korean titles, Nunito for English.
export const C = {
  bg: '#F3F5FF', sheet: '#FFFFFF', ink: '#1E1B33', ink2: '#4A4766', ink3: '#6A6785', faint: '#A6A3BD', line: '#E4E6F5',
  accent: '#5B3DF5', accentSoft: '#ECE8FF', onAccent: '#FFFFFF',
  dark: '#1E1B33', dark2: '#2E2A48', track: '#3A3656', progress: '#9D8BFF',
  peach: '#FFD9C7', mint: '#C9F0DD', lilac: '#E3DBFF', mintInk: '#1F4D3A',
  warnBg: '#FFE3D6', warn: '#A3400F', streak: '#C2521C',
};
export const TILE = [C.peach, C.mint, C.lilac];
export const F = {
  title: 'Jua_400Regular',          // Korean display
  en: 'Nunito_600SemiBold',         // English body (sentences)
  enB: 'Nunito_800ExtraBold',       // English titles, words
  enX: 'Nunito_900Black',           // big numbers, flashcard word
};
export const R = { card: 28, tile: 24, pill: 999, btn: 22 };
export const shadow = { boxShadow: '0 8px 24px rgba(75, 47, 214, 0.12)' } as const;

export const fmt = (s?: number | null) => {
  s = Math.max(0, Math.floor(s ?? 0));
  const m = Math.floor(s / 60), r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
};
export const mins = (s?: number | null) => `${Math.max(1, Math.round((s ?? 0) / 60))}분`;
export const dateKo = (iso: string) => new Date(iso).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });
export const tileColor = (id: string) => TILE[[...id].reduce((a, ch) => a + ch.charCodeAt(0), 0) % TILE.length];
