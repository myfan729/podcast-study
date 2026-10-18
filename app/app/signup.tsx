// Sign-up, right after the first login: a nickname and the agreements (required vs optional),
// recorded with the version agreed to. Also shown again when the terms or privacy policy change.
import { useEffect, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon } from '@/components/ui';
import * as api from '@/lib/api';
import { PRIVACY_URL, PRIVACY_VERSION, TERMS_URL, TERMS_VERSION } from '@/lib/config';
import { useSession } from '@/lib/session';
import { supabase } from '@/lib/supabase';
import { C, F, R } from '@/lib/theme';

type Key = 'terms' | 'privacy' | 'age' | 'marketing';
const ITEMS: { k: Key; label: string; required: boolean; url?: string }[] = [
  { k: 'terms', label: '이용약관 동의', required: true, url: TERMS_URL },
  { k: 'privacy', label: '개인정보 수집·이용 동의', required: true, url: PRIVACY_URL },
  { k: 'age', label: '만 14세 이상입니다', required: true },
  { k: 'marketing', label: '새 기능·이벤트 소식 메일 받기', required: false },
];

export default function SignUp() {
  const { session, profile, reloadProfile } = useSession();
  const again = !!profile;                                   // already signed up: only the updated agreements
  const meta = (session?.user.user_metadata ?? {}) as { name?: string; full_name?: string; nickname?: string };
  const [nick, setNick] = useState(profile?.nickname ?? '');
  const [on, setOn] = useState<Record<Key, boolean>>({ terms: false, privacy: false, age: again, marketing: profile?.marketing_opt_in ?? false });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  useEffect(() => { if (!nick) setNick((meta.nickname || meta.name || meta.full_name || '').slice(0, 20)); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const all = ITEMS.every((i) => on[i.k]);
  const ready = nick.trim().length >= 1 && ITEMS.filter((i) => i.required).every((i) => on[i.k]);
  const submit = async () => {
    setBusy(true); setMsg('');
    try {
      await api.saveProfile({ nickname: nick.trim(), marketing: on.marketing, terms_version: TERMS_VERSION, privacy_version: PRIVACY_VERSION });
      await reloadProfile();                                 // the gate then moves on to the app
    } catch (e: any) { setMsg(String(e?.message ?? e)); } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }}>
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }} keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 24}>
        <ScrollView contentContainerStyle={s.wrap} keyboardShouldPersistTaps="handled">
          <Text style={s.h}>{again ? '약관이 바뀌었어요' : '가입을 마무리할게요'}</Text>
          <Text style={s.sub}>{again ? '바뀐 내용을 확인하고 다시 동의해 주세요.' : `${session?.user.email ?? ''} 계정으로 시작해요.`}</Text>

          <View style={s.box}>
            <Text style={s.label} nativeID="nickLabel">닉네임</Text>
            <TextInput style={s.input} value={nick} onChangeText={(t) => setNick(t.slice(0, 20))} placeholder="앱에서 부를 이름 (20자까지)"
              placeholderTextColor={C.faint} accessibilityLabelledBy="nickLabel" maxLength={20} />
          </View>

          <View style={s.box}>
            <Pressable style={s.allRow} onPress={() => { const v = !all; setOn({ terms: v, privacy: v, age: v, marketing: v }); }} accessibilityRole="checkbox" accessibilityState={{ checked: all }}>
              <Check on={all} big /><Text style={s.allT}>전체 동의</Text>
            </Pressable>
            <View style={s.line} />
            {ITEMS.map((i) => (
              <View key={i.k} style={s.row}>
                <Pressable style={s.rowL} onPress={() => setOn({ ...on, [i.k]: !on[i.k] })} accessibilityRole="checkbox" accessibilityState={{ checked: on[i.k] }}>
                  <Check on={on[i.k]} />
                  <Text style={s.rowT}><Text style={{ color: i.required ? C.accent : C.ink3 }}>[{i.required ? '필수' : '선택'}] </Text>{i.label}</Text>
                </Pressable>
                {i.url ? <Pressable onPress={() => Linking.openURL(i.url!)} hitSlop={8}><Text style={s.view}>보기</Text></Pressable> : null}
              </View>))}
          </View>

          <Pressable style={[s.btn, (!ready || busy) && { opacity: 0.45 }]} disabled={!ready || busy} onPress={submit} accessibilityRole="button">
            {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.btnT}>{again ? '동의하고 계속하기' : '가입 완료'}</Text>}
          </Pressable>
          {!!msg && <Text style={s.msg}>{msg}</Text>}
          <Pressable onPress={() => supabase.auth.signOut()} hitSlop={8}><Text style={s.out}>다른 계정으로 로그인</Text></Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Check({ on, big }: { on: boolean; big?: boolean }) {
  const z = big ? 26 : 22;
  return (
    <View style={{ width: z, height: z, borderRadius: z / 2, backgroundColor: on ? C.accent : C.line, alignItems: 'center', justifyContent: 'center' }}>
      <Icon name="checkmark" size={z * 0.62} color="#fff" />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flexGrow: 1, justifyContent: 'center', padding: 24, gap: 14 },
  h: { fontFamily: F.title, fontSize: 28, color: C.ink, textAlign: 'center' },
  sub: { color: C.ink2, textAlign: 'center', marginBottom: 8 },
  box: { backgroundColor: C.sheet, borderRadius: R.card, padding: 18 },
  label: { color: C.ink3, fontSize: 12.5, marginBottom: 6, marginLeft: 4 },
  input: { backgroundColor: C.bg, borderRadius: 18, paddingHorizontal: 16, paddingVertical: 14, fontSize: 16, color: C.ink },
  allRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 44 },
  allT: { fontSize: 17, fontWeight: '700', color: C.ink },
  line: { height: 1, backgroundColor: C.line, marginVertical: 8 },
  row: { flexDirection: 'row', alignItems: 'center', minHeight: 44 },
  rowL: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 44 },
  rowT: { color: C.ink2, fontSize: 14.5, flexShrink: 1 },
  view: { color: C.ink3, fontSize: 13, textDecorationLine: 'underline', paddingLeft: 8 },
  btn: { backgroundColor: C.accent, borderRadius: R.pill, minHeight: 54, alignItems: 'center', justifyContent: 'center', marginTop: 6 },
  btnT: { color: '#fff', fontWeight: '700', fontSize: 16 },
  msg: { color: C.warn, textAlign: 'center' },
  out: { color: C.ink3, textAlign: 'center', fontSize: 13, marginTop: 4 },
});
