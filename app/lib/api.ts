import { supabase } from './supabase';
import type { Episode, Pack, RequestResult, SavedItem, Show } from './types';

const ok = <T,>(r: { data: T | null; error: { message: string } | null }): T => {
  if (r.error) throw new Error(r.error.message);
  return r.data as T;
};

export async function catalog(): Promise<Show[]> {
  return ok(await supabase.from('shows').select('id,title,author,image_url,description,category,level,catalog,intro_ko').eq('catalog', true).order('title'));
}
export async function show(id: string): Promise<Show> {
  return ok(await supabase.from('shows').select('id,title,author,image_url,description,category,level,catalog,intro_ko').eq('id', id).single());
}
export async function mySubscriptions(): Promise<string[]> {
  const rows = ok(await supabase.from('subscriptions').select('show_id'));
  return (rows as { show_id: string }[]).map((r) => r.show_id);
}
export async function setSubscribed(showId: string, on: boolean) {
  const { data } = await supabase.auth.getUser();
  if (!data.user) throw new Error('로그인이 필요해요');
  if (on) ok(await supabase.from('subscriptions').upsert({ user_id: data.user.id, show_id: showId }));
  else ok(await supabase.from('subscriptions').delete().eq('show_id', showId));
}
const EP_COLS = 'id,show_id,title,published_at,duration_sec,audio_url,image_url,status,one_liner_ko,has_transcript,pack_path,sync_path,error,intro_ko,episode_url';
const EP_ONE = EP_COLS + ',description';
export async function showEpisodes(showId: string): Promise<Episode[]> {
  return ok(await supabase.from('episodes').select(EP_COLS).eq('show_id', showId).order('published_at', { ascending: false }).limit(30));
}
export async function feed(showIds: string[]): Promise<Episode[]> {
  if (!showIds.length) return [];
  return ok(await supabase.from('episodes').select(EP_COLS + ',shows(title,image_url)').in('show_id', showIds)
    .order('published_at', { ascending: false }).limit(40)) as unknown as Episode[];
}
export async function episode(id: string): Promise<Episode> {
  return ok(await supabase.from('episodes').select(EP_ONE + ',shows(title,image_url)').eq('id', id).single()) as unknown as Episode;
}
/** Has this user already made (unlocked) the study pack for this episode? Free to reopen. */
export async function isUnlocked(id: string): Promise<boolean> {
  const r = await supabase.from('unlocks').select('episode_id').eq('episode_id', id).maybeSingle();
  return !!r.data;
}
export async function requestEpisode(id: string): Promise<RequestResult> {
  return ok(await supabase.rpc('request_episode', { ep: id })) as RequestResult;
}
async function download<T>(path: string): Promise<T> {
  // Blob.text() doesn't exist in React Native: fetch through a short-lived signed URL instead
  const r = await supabase.storage.from('episodes').createSignedUrl(path, 120);
  if (r.error || !r.data?.signedUrl) throw new Error(r.error?.message ?? '내려받기 실패');
  const res = await fetch(r.data.signedUrl);
  if (!res.ok) throw new Error(`내려받기 실패 (${res.status})`);
  return (await res.json()) as T;
}
export const pack = (path: string) => download<Pack>(path);
export const syncData = (path: string) => download<any>(path);

export async function saveProgress(episodeId: string, position: number, finished = false) {
  const { data } = await supabase.auth.getUser();
  if (!data.user) return;
  const now = new Date().toISOString();
  await supabase.from('listens').upsert({ user_id: data.user.id, episode_id: episodeId, position_sec: position, finished, played_at: now });
  await supabase.from('unlocks').update({ position_sec: position, finished, played_at: now }).eq('episode_id', episodeId);   // no row → no-op
}
/** The episode the user was last in the middle of (for "이어 듣기"), listened to or studied. */
export async function continueListening(): Promise<{ position: number; ep: Episode } | null> {
  const r = await supabase.from('listens').select('position_sec,episodes(' + EP_COLS + ',shows(title,image_url))')
    .eq('finished', false).gt('position_sec', 20).order('played_at', { ascending: false }).limit(1);
  const row = (r.data as unknown as { position_sec: number; episodes: Episode | null }[] | null)?.[0];
  return row?.episodes ? { position: row.position_sec, ep: row.episodes } : null;
}
export async function lastPosition(episodeId: string): Promise<number> {
  const r = await supabase.from('listens').select('position_sec').eq('episode_id', episodeId).maybeSingle();
  return (r.data as { position_sec: number } | null)?.position_sec ?? 0;
}
export async function freeLeft(): Promise<{ free_left: number; pro: boolean }> {
  const { data } = await supabase.auth.getUser();
  if (!data.user) return { free_left: 0, pro: false };
  const [fl, pro] = await Promise.all([supabase.rpc('free_left', { uid: data.user.id }), supabase.rpc('is_pro', { uid: data.user.id })]);
  return { free_left: (fl.data as number) ?? 0, pro: !!pro.data };
}

// ---- 단어장 ----
export async function saveItem(item: { kind: SavedItem['kind']; text: string; meaning_ko?: string; example?: string; episode_id?: string }) {
  const { data } = await supabase.auth.getUser();
  if (!data.user) throw new Error('로그인이 필요해요');
  ok(await supabase.from('vocab').upsert({ ...item, user_id: data.user.id }, { onConflict: 'user_id,kind,text' }));
}
export async function myItems(): Promise<SavedItem[]> {
  return ok(await supabase.from('vocab').select('*').order('created_at', { ascending: false }));
}
export async function deleteItem(id: string) { ok(await supabase.from('vocab').delete().eq('id', id)); }
/** SM-2 review: grade 0 (again) … 3 (easy) */
export async function review(item: SavedItem, grade: 0 | 1 | 2 | 3) {
  let { ease, interval_days: iv, reps } = item;
  if (grade === 0) { reps = 0; iv = 0; ease = Math.max(1.3, ease - 0.2); }
  else {
    reps += 1;
    iv = reps === 1 ? 1 : reps === 2 ? 3 : Math.round(iv * ease * (grade === 3 ? 1.3 : grade === 1 ? 0.8 : 1));
    ease = Math.max(1.3, ease + (grade === 3 ? 0.15 : grade === 1 ? -0.15 : 0));
  }
  const due = new Date(Date.now() + (iv ? iv * 86400e3 : 10 * 60e3)).toISOString();
  ok(await supabase.from('vocab').update({ ease, interval_days: iv, reps, due_at: due }).eq('id', item.id));
}

/** Permanently deletes the signed-in user's account and everything saved under it. */
export async function deleteMyAccount() {
  ok(await supabase.rpc('delete_my_account'));
  await supabase.auth.signOut();
}

/** Auto-sync diagnostics from this phone (best effort). */
export async function reportSync(episodeId: string, ok: boolean, anchors: unknown, report: unknown, error?: string) {
  await supabase.from('sync_reports').insert({ episode_id: episodeId, ok, anchors, report, error: error ?? null });
}

/** Android blocks plain-http audio. Some feeds (BBC) still list http:// enclosures, and BBC's
 *  media selector picks the protocol from the path (/proto/http/ → an http redirect), so ask for https. */
export function secureAudio(url: string | null | undefined): string {
  if (!url) return '';
  return url.replace(/^http:\/\//i, 'https://').replace('/proto/http/', '/proto/https/');
}

// ---------- sign-up record ----------
export async function saveProfile(p: { nickname: string; marketing: boolean; terms_version: string; privacy_version: string }) {
  const { data } = await supabase.auth.getUser();
  if (!data.user) throw new Error('로그인이 필요해요');
  const now = new Date().toISOString();
  ok(await supabase.from('profiles').upsert({
    user_id: data.user.id, nickname: p.nickname, terms_version: p.terms_version, privacy_version: p.privacy_version,
    age14_confirmed: true, agreed_at: now, marketing_opt_in: p.marketing, marketing_at: now, updated_at: now,
  }));
}
export async function setMarketing(on: boolean) {
  const now = new Date().toISOString();
  const { data } = await supabase.auth.getUser();
  if (!data.user) return;
  ok(await supabase.from('profiles').update({ marketing_opt_in: on, marketing_at: now, updated_at: now }).eq('user_id', data.user.id));
}
export async function setNickname(nickname: string) {
  const { data } = await supabase.auth.getUser();
  if (!data.user) return;
  ok(await supabase.from('profiles').update({ nickname, updated_at: new Date().toISOString() }).eq('user_id', data.user.id));
}
