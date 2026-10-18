// Public values (safe to ship in the app). Set them in app.json → expo.extra or as EXPO_PUBLIC_* env vars.
import Constants from 'expo-constants';

const extra = (Constants.expoConfig?.extra ?? {}) as Record<string, string | undefined>;
export const SUPABASE_URL = process.env.EXPO_PUBLIC_SUPABASE_URL ?? extra.supabaseUrl ?? '';
export const SUPABASE_ANON_KEY = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY ?? extra.supabaseAnonKey ?? '';
export const FREE_PER_WEEK = 2;
export const SITE_URL = 'https://myfan729.github.io/podcast-study/';
export const PRIVACY_URL = SITE_URL + 'privacy.html';
export const TERMS_URL = SITE_URL + 'terms.html';
export const TERMS_VERSION = '2026-10-18';      // bump with docs/terms.html; users re-agree when it changes
export const PRIVACY_VERSION = '2026-10-18';    // bump with docs/privacy.html
export const MAX_STUDY_SEC = 3600;            // study material only for episodes up to 60 min (server enforces it too)
