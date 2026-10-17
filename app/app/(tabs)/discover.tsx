import { Link, useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Art, Chip, Icon, PageTitle } from '@/components/ui';
import * as api from '@/lib/api';
import type { Show } from '@/lib/types';
import { C, F, R } from '@/lib/theme';

export default function Discover() {
  const [shows, setShows] = useState<Show[]>([]);
  const [subs, setSubs] = useState<Set<string>>(new Set());
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('전체');
  useFocusEffect(useCallback(() => {
    api.catalog().then(setShows).catch(() => {});
    api.mySubscriptions().then((ids) => setSubs(new Set(ids))).catch(() => {});
  }, []));
  const cats = useMemo(() => ['전체', ...Array.from(new Set(shows.map((x) => x.category).filter(Boolean) as string[]))], [shows]);
  const list = shows.filter((x) => (cat === '전체' || x.category === cat) &&
    (!q || (x.title + ' ' + (x.author ?? '')).toLowerCase().includes(q.toLowerCase())));
  const toggle = async (id: string) => {
    const on = !subs.has(id);
    const next = new Set(subs); on ? next.add(id) : next.delete(id); setSubs(next);
    try { await api.setSubscribed(id, on); } catch { setSubs(subs); }
  };
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <PageTitle>찾기</PageTitle>
      <View style={s.search}>
        <Icon name="search" size={18} color={C.ink3} />
        <TextInput style={s.input} placeholder="쇼 이름으로 찾기" placeholderTextColor={C.ink3} value={q} onChangeText={setQ}
          accessibilityLabel="쇼 검색" returnKeyType="search" />
      </View>
      <FlatList horizontal data={cats} keyExtractor={(c) => c} style={{ flexGrow: 0, minHeight: 50 }}
        contentContainerStyle={{ paddingHorizontal: 22, gap: 8, alignItems: 'center' }} showsHorizontalScrollIndicator={false}
        renderItem={({ item }) => <Chip label={item} on={cat === item} onPress={() => setCat(item)} />} />
      <FlatList contentContainerStyle={{ padding: 16, paddingTop: 8 }} data={list} keyExtractor={(x) => x.id}
        ListEmptyComponent={<Text style={s.none}>{shows.length ? '찾는 쇼가 없어요.' : '불러오는 중…'}</Text>}
        renderItem={({ item }) => {
          const on = subs.has(item.id);
          return (
            <Link href={{ pathname: '/show/[id]', params: { id: item.id } }} asChild>
              <Pressable style={s.row}>
                <Art uri={item.image_url} id={item.id} size={58} radius={16} />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={s.title} numberOfLines={1}>{item.title}</Text>
                  <Text style={s.meta} numberOfLines={1}>{item.author}{item.level ? ` · ${item.level}` : ''}</Text>
                </View>
                <Pressable onPress={() => toggle(item.id)} accessibilityLabel={on ? '구독 취소' : '구독'} hitSlop={6}
                  style={[s.sub, on && { backgroundColor: C.accent }]}>
                  <Icon name={on ? 'checkmark' : 'add'} size={16} color={on ? '#fff' : C.accent} />
                  <Text style={[s.subT, on && { color: '#fff' }]}>{on ? '구독 중' : '구독'}</Text>
                </Pressable>
              </Pressable>
            </Link>);
        }} />
    </SafeAreaView>
  );
}
const s = StyleSheet.create({
  search: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 22, marginBottom: 6, backgroundColor: C.sheet, borderRadius: R.pill, paddingHorizontal: 16, minHeight: 50 },
  input: { flex: 1, fontSize: 15, color: C.ink, paddingVertical: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, backgroundColor: C.sheet, borderRadius: 24, marginBottom: 10 },
  title: { color: C.ink, fontFamily: F.enB, fontSize: 15.5 },
  meta: { color: C.ink3, fontSize: 12.5, marginTop: 3 },
  sub: { flexDirection: 'row', alignItems: 'center', gap: 3, backgroundColor: C.accentSoft, borderRadius: R.pill, paddingHorizontal: 12, minHeight: 38 },
  subT: { color: C.accent, fontWeight: '700', fontSize: 13 },
  none: { color: C.ink3, textAlign: 'center', marginTop: 40 },
});
