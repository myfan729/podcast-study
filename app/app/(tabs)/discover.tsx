import { Link, useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Art, Chip, Icon, PageTitle } from '@/components/ui';
import * as api from '@/lib/api';
import type { Show } from '@/lib/types';
import { C, F, R } from '@/lib/theme';

const LEVELS = ['초급', '초중', '중', '중상', '상'];                 // easy → hard
const rank = (lv?: string | null) => { const i = LEVELS.indexOf(lv ?? ''); return i < 0 ? 99 : i; };
type Sort = 'name' | 'easy' | 'hard';
const SORTS: { k: Sort; label: string }[] = [{ k: 'name', label: '이름순' }, { k: 'easy', label: '쉬운 순' }, { k: 'hard', label: '어려운 순' }];

export default function Discover() {
  const [shows, setShows] = useState<Show[]>([]);
  const [subs, setSubs] = useState<Set<string>>(new Set());
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('전체');
  const [sort, setSort] = useState<Sort>('name');
  useFocusEffect(useCallback(() => {
    api.catalog().then(setShows).catch(() => {});
    api.mySubscriptions().then((ids) => setSubs(new Set(ids))).catch(() => {});
  }, []));
  const cats = useMemo(() => ['전체', ...Array.from(new Set(shows.map((x) => x.category).filter(Boolean) as string[]))], [shows]);
  const list = shows.filter((x) => (cat === '전체' || x.category === cat) &&
    (!q || (x.title + ' ' + (x.author ?? '')).toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => sort === 'name' ? a.title.localeCompare(b.title)
      : (sort === 'easy' ? rank(a.level) - rank(b.level) : (rank(b.level) % 99) - (rank(a.level) % 99)) || a.title.localeCompare(b.title));
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
      <View style={s.sortRow}>
        <Icon name="swap-vertical" size={15} color={C.ink3} />
        {SORTS.map((o) => (
          <Pressable key={o.k} onPress={() => setSort(o.k)} hitSlop={6} accessibilityRole="button" accessibilityState={{ selected: sort === o.k }}
            style={[s.sortB, sort === o.k && s.sortOn]}>
            <Text style={[s.sortT, sort === o.k && { color: C.accent, fontWeight: '700' }]}>{o.label}</Text>
          </Pressable>))}
      </View>
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
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 3 }}>
                    {item.level ? <View style={[s.lv, { backgroundColor: LV_BG[rank(item.level)] ?? C.line }]}><Text style={s.lvT}>{item.level}</Text></View> : null}
                    <Text style={[s.meta, { marginTop: 0, flex: 1 }]} numberOfLines={1}>{item.author}</Text>
                  </View>
                  {item.intro_ko ? <Text style={s.intro} numberOfLines={2}>{item.intro_ko}</Text> : null}
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
const LV_BG = ['#D9F2E3', '#E3F1D2', '#FFF0C7', '#FFE0CC', '#FAD4D8'];   // easy (green) → hard (rose)
const s = StyleSheet.create({
  sortRow: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 24, paddingTop: 2, paddingBottom: 2 },
  sortB: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: R.pill },
  sortOn: { backgroundColor: C.accentSoft },
  sortT: { color: C.ink3, fontSize: 13 },
  lv: { borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2 },
  lvT: { color: C.ink, fontSize: 11, fontWeight: '700' },
  search: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 22, marginBottom: 6, backgroundColor: C.sheet, borderRadius: R.pill, paddingHorizontal: 16, minHeight: 50 },
  input: { flex: 1, fontSize: 15, color: C.ink, paddingVertical: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, backgroundColor: C.sheet, borderRadius: 24, marginBottom: 10 },
  title: { color: C.ink, fontFamily: F.enB, fontSize: 15.5 },
  meta: { color: C.ink3, fontSize: 12.5, marginTop: 3 },
  intro: { color: C.ink2, fontSize: 12, marginTop: 4, lineHeight: 16 },
  sub: { flexDirection: 'row', alignItems: 'center', gap: 3, backgroundColor: C.accentSoft, borderRadius: R.pill, paddingHorizontal: 12, minHeight: 38 },
  subT: { color: C.accent, fontWeight: '700', fontSize: 13 },
  none: { color: C.ink3, textAlign: 'center', marginTop: 40 },
});
