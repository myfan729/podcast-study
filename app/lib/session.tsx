import type { Session } from '@supabase/supabase-js';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { supabase } from './supabase';

export type Profile = { nickname: string; marketing_opt_in: boolean; terms_version: string; privacy_version: string };
type Ctx = { session: Session | null; loading: boolean; profile: Profile | null; profileLoading: boolean; reloadProfile: () => Promise<void> };
const SessionCtx = createContext<Ctx>({ session: null, loading: true, profile: null, profileLoading: true, reloadProfile: async () => {} });

/** The signed-in user and their sign-up record (null until they finish sign-up). */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setLoading(false); });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);
  const uid = session?.user.id;
  const reloadProfile = useCallback(async () => {
    if (!uid) { setProfile(null); setProfileLoading(false); return; }
    setProfileLoading(true);
    const r = await supabase.from('profiles').select('nickname,marketing_opt_in,terms_version,privacy_version').eq('user_id', uid).maybeSingle();
    if (!r.error) setProfile((r.data as Profile | null) ?? null);
    setProfileLoading(false);
  }, [uid]);
  useEffect(() => { reloadProfile(); }, [reloadProfile]);
  return <SessionCtx.Provider value={{ session, loading, profile, profileLoading, reloadProfile }}>{children}</SessionCtx.Provider>;
}
export const useSession = () => useContext(SessionCtx);
