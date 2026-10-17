import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon, PageTitle } from '@/components/ui';
import * as api from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { useSession } from '@/lib/session';
import { FREE_PER_WEEK, PRIVACY_URL } from '@/lib/config';
import { C, F, R } from '@/lib/theme';

export default function Settings() {
  const { session } = useSession();
  const [plan, setPlan] = useState<{ free_left: number; pro: boolean } | null>(null);
  useFocusEffect(useCallback(() => { api.freeLeft().then(setPlan).catch(() => {}); }, []));
  const email = session?.user.email ?? '';
  const remove = () => {
    const run = () => api.deleteMyAccount().catch((e) => Alert.alert('삭제하지 못했어요', String(e.message ?? e)));
    const msg = '계정과 저장한 단어장, 듣기 기록이 모두 지워지고 되돌릴 수 없어요.';
    if (Platform.OS === 'web') { if (globalThis.confirm?.(msg)) run(); return; }
    Alert.alert('계정을 삭제할까요?', msg, [{ text: '취소', style: 'cancel' }, { text: '삭제', style: 'destructive', onPress: run }]);
  };
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <PageTitle>나</PageTitle>
        <View style={s.me}>
          <View style={s.avatar}><Text style={s.avatarT}>{email.slice(0, 1).toUpperCase() || '?'}</Text></View>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={s.label}>로그인 계정</Text>
            <Text style={s.email} numberOfLines={1}>{email}</Text>
          </View>
        </View>
        <View style={[s.plan, plan?.pro && { backgroundColor: C.accent }]}>
          <Text style={[s.planLabel, plan?.pro && { color: '#E6E0FF' }]}>이용권</Text>
          <Text style={[s.planH, plan?.pro && { color: '#fff' }]}>{plan?.pro ? '프로 · 무제한' : '무료'}</Text>
          {!plan?.pro && <>
            <View style={s.dots}>
              {Array.from({ length: FREE_PER_WEEK }).map((_, i) => (
                <View key={i} style={[s.dot, i < (plan?.free_left ?? 0) && { backgroundColor: C.accent }]} />))}
            </View>
            <Text style={s.planP}>이번 주 새 에피소드 {plan?.free_left ?? '-'} / {FREE_PER_WEEK}편 남았어요. 한 번 연 에피소드는 계속 들을 수 있어요.</Text>
            <View style={s.soon}><Icon name="time-outline" size={15} color={C.ink2} /><Text style={s.soonT}>프로 구독은 다음 업데이트에서 열려요</Text></View>
          </>}
        </View>
        <Pressable style={s.out} onPress={() => supabase.auth.signOut()} accessibilityRole="button">
          <Icon name="log-out-outline" size={18} color={C.warn} /><Text style={s.outT}>로그아웃</Text>
        </Pressable>
        <View style={s.links}>
          <Pressable onPress={() => Linking.openURL(PRIVACY_URL)} hitSlop={8}><Text style={s.link}>개인정보처리방침</Text></Pressable>
          <Text style={s.link}>·</Text>
          <Pressable onPress={remove} hitSlop={8} accessibilityRole="button"><Text style={s.link}>계정 삭제</Text></Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
const s = StyleSheet.create({
  me: { flexDirection: 'row', alignItems: 'center', gap: 14, marginHorizontal: 22, padding: 18, backgroundColor: C.sheet, borderRadius: R.card },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: C.peach, alignItems: 'center', justifyContent: 'center' },
  avatarT: { fontFamily: F.enX, fontSize: 22, color: C.ink },
  label: { color: C.ink3, fontSize: 12.5 },
  email: { color: C.ink, fontSize: 16, fontWeight: '700', marginTop: 2 },
  plan: { marginHorizontal: 22, marginTop: 12, padding: 20, backgroundColor: C.sheet, borderRadius: R.card },
  planLabel: { color: C.ink3, fontSize: 12.5 },
  planH: { fontFamily: F.title, fontSize: 24, color: C.ink, marginTop: 2 },
  dots: { flexDirection: 'row', gap: 6, marginTop: 14 },
  dot: { flex: 1, height: 8, borderRadius: 4, backgroundColor: C.line },
  planP: { color: C.ink2, fontSize: 13.5, lineHeight: 20, marginTop: 12 },
  soon: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 14, backgroundColor: C.bg, borderRadius: 16, padding: 12 },
  soonT: { color: C.ink2, fontSize: 13 },
  out: { flexDirection: 'row', gap: 6, alignItems: 'center', justifyContent: 'center', minHeight: 52, marginTop: 18 },
  outT: { color: C.warn, fontWeight: '700' },
  links: { flexDirection: 'row', justifyContent: 'center', gap: 10, marginTop: 4 },
  link: { color: C.ink3, fontSize: 13, textDecorationLine: 'none' },
});
