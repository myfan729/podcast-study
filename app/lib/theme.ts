export const C = {
  bg: '#f4f3ee', sheet: '#ffffff', ink: '#15213a', ink2: '#4a5568', ink3: '#8a94a6', line: '#e3e1d8',
  accent: '#2b59c3', hl: '#ffe45e', ok: '#1f9d55', warn: '#c2410c',
};
export const fmt = (s?: number | null) => {
  s = Math.max(0, Math.floor(s ?? 0));
  const m = Math.floor(s / 60), r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
};
export const dateKo = (iso: string) => new Date(iso).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });
