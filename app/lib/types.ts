export type Show = {
  id: string; title: string; author: string | null; image_url: string | null; description: string | null;
  category: string | null; level: string | null; catalog: boolean;
};
export type EpisodeStatus = 'none' | 'queued' | 'processing' | 'ready' | 'failed' | 'no_transcript';
export type Episode = {
  id: string; show_id: string; title: string; published_at: string; duration_sec: number | null;
  audio_url: string | null; image_url: string | null; status: EpisodeStatus; one_liner_ko: string | null;
  has_transcript: boolean; pack_path: string | null; sync_path: string | null;
  shows?: Pick<Show, 'title' | 'image_url'>;
};
export type Cue = { s: number; e: number; t: string; spk?: string | null };
export type Segment = { id: string; cue_from: number; cue_to: number; start: number; end: number; display_speaker?: string };
export type Vocab = { word: string; pos?: string; meaning_ko: string; example?: string };
export type Expression = {
  expression: string; type?: string; meaning_ko: string; nuance_ko?: string; quote?: string; segment_id?: string;
  examples?: string[]; similar?: { expression: string; example: string }[];
};
export type Pack = {
  id: string; title: string; duration_sec: number; audio_url: string;
  show: { name: string; image?: string };
  audio_meta?: { fixed?: boolean; ad_markers?: { type: string; sec: number }[]; content_duration?: number };
  transcript: { cues: Cue[]; sentences?: [number, number][]; segments: Segment[] };
  study: { one_liner_ko?: string; translations_sent?: Record<string, string>; vocab?: Vocab[]; expressions?: Expression[] };
};
export type RequestResult = { status: EpisodeStatus; unlocked: boolean; free_left: number; pro: boolean; reason?: string };
export type SavedItem = {
  id: string; kind: 'word' | 'expression' | 'sentence'; text: string; meaning_ko: string | null; example: string | null;
  note: string | null; due_at: string; interval_days: number; ease: number; reps: number; episode_id: string | null;
};
