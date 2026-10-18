import * as WebBrowser from 'expo-web-browser';
import { SUPABASE_ANON_KEY, SUPABASE_URL } from './config';
import * as Linking from 'expo-linking';
import { supabase } from './supabase';

/** Where the sign-in e-mail's link sends the user back to: the app itself. */
export const AUTH_REDIRECT = Linking.createURL('login');

/** Sign in from a link the e-mail opened (works whether the e-mail carried a code or a link). */
export async function handleAuthUrl(url: string | null) {
  if (!url || !/access_token|token_hash|[?&]code=/.test(url)) return false;
  const params = new URLSearchParams(url.replace(/^[^?#]*[?#]/, '').replace('#', '&'));
  const at = params.get('access_token'), rt = params.get('refresh_token');
  if (at && rt) { await supabase.auth.setSession({ access_token: at, refresh_token: rt }); return true; }
  const th = params.get('token_hash'), type = params.get('type');
  if (th && type) { await supabase.auth.verifyOtp({ token_hash: th, type: type as 'magiclink' | 'signup' | 'email' }); return true; }
  const code = params.get('code');
  if (code) { await supabase.auth.exchangeCodeForSession(code); return true; }
  return false;
}

// ---------- Google / Kakao ----------

export type Social = 'google' | 'kakao';
/** Which social logins are switched on in Supabase (so a button only shows once it works). */
export async function enabledSocial(): Promise<Social[]> {
  try {
    const r = await fetch(`${SUPABASE_URL}/auth/v1/settings`, { headers: { apikey: SUPABASE_ANON_KEY } });
    const ext = ((await r.json()) as { external?: Record<string, boolean> }).external ?? {};
    return (['google', 'kakao'] as Social[]).filter((p) => ext[p]);
  } catch { return []; }
}
/** Sign in through the provider's page in an in-app browser; it comes back to podcaststudy://login. */
export async function signInWith(provider: Social) {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider, options: { redirectTo: AUTH_REDIRECT, skipBrowserRedirect: true,
      ...(provider === 'kakao' ? { scopes: 'account_email profile_nickname' } : {}) },
  });
  if (error || !data?.url) throw new Error(error?.message ?? '로그인을 시작하지 못했어요');
  const res = await WebBrowser.openAuthSessionAsync(data.url, AUTH_REDIRECT);
  if (res.type === 'success') await handleAuthUrl(res.url);
}
