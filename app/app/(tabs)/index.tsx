import { useFocusEffect, Link } from 'expo-router';
import { useCallback, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import EpisodeRow from '@/components/EpisodeRow';
import * as api from '@/lib/api';
import type { Episode } from '@/lib/types';
import { C } from '@/lib/theme';

export default function Home() {
  const [eps, setEps] = useState<Episode[]>([]);
  const [subs, setSubs] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    try { const ids = await api.mySubscriptions(); setSubs(ids); setEps(await api.feed(ids)); } finally { setBusy(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (subs && !subs.length) {
    return (
      <View style={s.empty}>
        <Text style={s.h}>아직 구독한 쇼가 없어요</Text>
        <Text style={s.p}>찾기 탭에서 듣고 싶은 팟캐스트를 구독하면, 새 에피소드가 여기 모여요.</Text>
        <Link href="/discover" asChild><Pressable style={s.btn}><Text style={s.btnT}>쇼 찾아보기</Text></Pressable></Link>
      </View>
    );
  }
  return (
    <FlatList contentContainerStyle={{ padding: 14 }} data={eps} keyExtractor={(e) => e.id}
      refreshControl={<RefreshControl refreshing={busy} onRefresh={load} />}
      renderItem={({ item }) => <EpisodeRow ep={item} showTitle />} />
  );
}
const s = StyleSheet.create({
  empty: { flex: 1, justifyContent: 'center', padding: 28 },
  h: { fontSize: 20, fontWeight: '700', color: C.ink, marginBottom: 8 },
  p: { color: C.ink2, lineHeight: 21, marginBottom: 20 },
  btn: { backgroundColor: C.accent, padding: 14, borderRadius: 12, alignItems: 'center' },
  btnT: { color: '#fff', fontWeight: '700' },
});
