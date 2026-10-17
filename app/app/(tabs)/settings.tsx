import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import * as api from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { useSession } from '@/lib/session';
import { FREE_PER_WEEK } from '@/lib/config';
import { C } from '@/lib/theme';

export default function Settings() {
  const { session } = useSession();
  const [plan, setPlan] = useState<{ free_left: number; pro: boolean } | null>(null);
  useFocusEffect(useCallback(() => { api.freeLeft().then(setPlan).catch(() => {}); }, []));
  return (
    <View style={{ padding: 16, gap: 12 }}>
      <View style={s.card}>
        <Text style={s.label}>계정</Text>
        <Text style={s.val}>{session?.user.email}</Text>
      </View>
      <View style={s.card}>
        <Text style={s.label}>이용권</Text>
        <Text style={s.val}>{plan?.pro ? '프로 · 무제한' : `무료 · 이번 주 ${plan?.free_left ?? '-'} / ${FREE_PER_WEEK}편 남음`}</Text>
        {!plan?.pro && <Text style={s.note}>프로 구독(앱 스토어 결제)은 다음 업데이트에서 열려요.</Text>}
      </View>
      <Pressable style={s.out} onPress={() => supabase.auth.signOut()}><Text style={{ color: C.warn, fontWeight: '600' }}>로그아웃</Text></Pressable>
    </View>
  );
}
const s = StyleSheet.create({
  card: { backgroundColor: C.sheet, borderRadius: 14, padding: 16, borderWidth: 1, borderColor: C.line },
  label: { color: C.ink3, fontSize: 12.5, marginBottom: 4 },
  val: { color: C.ink, fontSize: 16, fontWeight: '600' },
  note: { color: C.ink3, marginTop: 8, fontSize: 13 },
  out: { padding: 14, alignItems: 'center' },
});
