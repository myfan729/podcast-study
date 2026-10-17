import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { supabase } from '@/lib/supabase';
import { C } from '@/lib/theme';

export default function Login() {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const send = async () => {
    setBusy(true); setMsg('');
    const { error } = await supabase.auth.signInWithOtp({ email: email.trim(), options: { shouldCreateUser: true } });
    setBusy(false);
    if (error) setMsg(error.message); else { setSent(true); setMsg('메일로 받은 6자리 코드를 입력하세요.'); }
  };
  const verify = async () => {
    setBusy(true); setMsg('');
    const { error } = await supabase.auth.verifyOtp({ email: email.trim(), token: code.trim(), type: 'email' });
    setBusy(false);
    if (error) setMsg('코드가 맞지 않아요. 다시 확인해 주세요.');
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={s.wrap}>
      <Text style={s.logo}>Podcast Study</Text>
      <Text style={s.sub}>진짜 영어 팟캐스트를 대본·번역·표현과 함께</Text>
      <TextInput style={s.input} placeholder="이메일" autoCapitalize="none" keyboardType="email-address"
        value={email} onChangeText={setEmail} editable={!sent} />
      {sent && <TextInput style={s.input} placeholder="6자리 코드" keyboardType="number-pad" value={code} onChangeText={setCode} maxLength={6} />}
      <Pressable style={[s.btn, busy && { opacity: 0.6 }]} disabled={busy} onPress={sent ? verify : send}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.btnText}>{sent ? '로그인' : '코드 받기'}</Text>}
      </Pressable>
      {sent && <Pressable onPress={() => { setSent(false); setCode(''); }}><Text style={s.link}>이메일 다시 입력</Text></Pressable>}
      {!!msg && <Text style={s.msg}>{msg}</Text>}
    </KeyboardAvoidingView>
  );
}
const s = StyleSheet.create({
  wrap: { flex: 1, justifyContent: 'center', padding: 28, backgroundColor: C.bg },
  logo: { fontSize: 30, fontWeight: '700', color: C.ink, marginBottom: 6 },
  sub: { color: C.ink2, marginBottom: 28 },
  input: { backgroundColor: C.sheet, borderColor: C.line, borderWidth: 1, borderRadius: 12, padding: 14, fontSize: 16, marginBottom: 12 },
  btn: { backgroundColor: C.accent, borderRadius: 12, padding: 15, alignItems: 'center', marginTop: 4 },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  link: { color: C.accent, textAlign: 'center', marginTop: 14 },
  msg: { color: C.ink2, textAlign: 'center', marginTop: 16 },
});
