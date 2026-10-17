import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon } from '@/components/ui';
import { supabase } from '@/lib/supabase';
import { C, F, R } from '@/lib/theme';

export default function Login() {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [usePw, setUsePw] = useState(false);       // password sign-in (store-review account)
  const [pw, setPw] = useState('');

  const send = async () => {
    setBusy(true); setMsg('');
    const { error } = await supabase.auth.signInWithOtp({ email: email.trim(), options: { shouldCreateUser: true } });
    setBusy(false);
    if (error) setMsg(error.message); else { setSent(true); setMsg('메일로 받은 6자리 코드를 입력하세요.'); }
  };
  const signInPw = async () => {
    setBusy(true); setMsg('');
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password: pw });
    setBusy(false);
    if (error) setMsg('이메일이나 비밀번호가 맞지 않아요.');
  };
  const verify = async () => {
    setBusy(true); setMsg('');
    const { error } = await supabase.auth.verifyOtp({ email: email.trim(), token: code.trim(), type: 'email' });
    setBusy(false);
    if (error) setMsg('코드가 맞지 않아요. 다시 확인해 주세요.');
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={s.wrap}>
        <View style={s.mark}><Icon name="ear" size={44} color="#fff" /></View>
        <Text style={s.logo}>잉팟</Text>
        <Text style={s.sub}>진짜 영어 팟캐스트를{'\n'}대본·번역·표현과 함께 들어요</Text>
        <View style={s.box}>
          <Text style={s.label} nativeID="emailLabel">이메일</Text>
          <TextInput style={[s.input, sent && { color: C.ink3 }]} placeholder="you@example.com" placeholderTextColor={C.faint}
            autoCapitalize="none" keyboardType="email-address" autoComplete="email" accessibilityLabelledBy="emailLabel"
            value={email} onChangeText={setEmail} editable={!sent} />
          {usePw && !sent && <>
            <Text style={[s.label, { marginTop: 12 }]} nativeID="pwLabel">비밀번호</Text>
            <TextInput style={s.input} secureTextEntry autoCapitalize="none" accessibilityLabelledBy="pwLabel" value={pw} onChangeText={setPw} />
          </>}
          {sent && <>
            <Text style={[s.label, { marginTop: 12 }]} nativeID="codeLabel">인증 코드</Text>
            <TextInput style={[s.input, s.code]} placeholder="000000" placeholderTextColor={C.faint} keyboardType="number-pad"
              autoComplete="one-time-code" accessibilityLabelledBy="codeLabel" value={code} onChangeText={setCode} maxLength={6} />
          </>}
          <Pressable style={[s.btn, busy && { opacity: 0.6 }]} disabled={busy} onPress={sent ? verify : usePw ? signInPw : send} accessibilityRole="button">
            {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.btnT}>{sent || usePw ? '시작하기' : '코드 받기'}</Text>}
          </Pressable>
          {sent && <Pressable onPress={() => { setSent(false); setCode(''); setMsg(''); }} hitSlop={8}><Text style={s.link}>이메일 다시 입력</Text></Pressable>}
          {!sent && <Pressable onPress={() => { setUsePw(!usePw); setMsg(''); }} hitSlop={8}>
            <Text style={[s.link, { color: C.ink3, fontWeight: '400', fontSize: 13 }]}>{usePw ? '이메일 코드로 로그인' : '비밀번호로 로그인'}</Text></Pressable>}
          {!!msg && <Text style={s.msg}>{msg}</Text>}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const s = StyleSheet.create({
  wrap: { flex: 1, justifyContent: 'center', padding: 24 },
  mark: { width: 84, height: 84, borderRadius: 30, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center', alignSelf: 'center' },
  logo: { fontFamily: F.title, fontSize: 40, color: C.ink, textAlign: 'center', marginTop: 14 },
  sub: { color: C.ink2, textAlign: 'center', lineHeight: 22, marginTop: 6, marginBottom: 28 },
  box: { backgroundColor: C.sheet, borderRadius: 32, padding: 20 },
  label: { color: C.ink3, fontSize: 12.5, marginBottom: 6, marginLeft: 4 },
  input: { backgroundColor: C.bg, borderRadius: 18, paddingHorizontal: 16, paddingVertical: 14, fontSize: 16, color: C.ink },
  code: { fontFamily: F.enX, fontSize: 22, letterSpacing: 8, textAlign: 'center' },
  btn: { backgroundColor: C.accent, borderRadius: R.btn, minHeight: 54, alignItems: 'center', justifyContent: 'center', marginTop: 16 },
  btnT: { color: '#fff', fontWeight: '700', fontSize: 16 },
  link: { color: C.accent, textAlign: 'center', marginTop: 14, fontWeight: '600' },
  msg: { color: C.ink2, textAlign: 'center', marginTop: 14, lineHeight: 20 },
});
