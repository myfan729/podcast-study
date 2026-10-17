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
