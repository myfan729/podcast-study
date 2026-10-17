import { Link, useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, Image, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import * as api from '@/lib/api';
import type { Show } from '@/lib/types';
import { C } from '@/lib/theme';

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
    <View style={{ flex: 1 }}>
      <TextInput style={s.search} placeholder="쇼 이름 검색" value={q} onChangeText={setQ} />
      <FlatList horizontal data={cats} keyExtractor={(c) => c} style={{ flexGrow: 0, minHeight: 44 }} contentContainerStyle={{ paddingHorizontal: 14, gap: 8, alignItems: 'center', paddingBottom: 6 }}
        showsHorizontalScrollIndicator={false}
        renderItem={({ item }) => (
          <Pressable onPress={() => setCat(item)} style={[s.chip, cat === item && s.chipOn]}>
            <Text style={[s.chipT, cat === item && { color: '#fff' }]}>{item}</Text>
          </Pressable>)} />
      <FlatList contentContainerStyle={{ padding: 14 }} data={list} keyExtractor={(x) => x.id}
        renderItem={({ item }) => (
          <Link href={{ pathname: '/show/[id]', params: { id: item.id } }} asChild>
            <Pressable style={s.row}>
              {item.image_url ? <Image source={{ uri: item.image_url }} style={s.img} /> : <View style={s.img} />}
              <View style={{ flex: 1 }}>
                <Text style={s.title} numberOfLines={1}>{item.title}</Text>
                <Text style={s.meta} numberOfLines={1}>{item.author}{item.level ? ` · ${item.level}` : ''}</Text>
              </View>
              <Pressable onPress={() => toggle(item.id)} style={[s.sub, subs.has(item.id) && s.subOn]}>
                <Text style={[s.subT, subs.has(item.id) && { color: '#fff' }]}>{subs.has(item.id) ? '구독 중' : '구독'}</Text>
              </Pressable>
            </Pressable>
          </Link>)} />
    </View>
  );
}
const s = StyleSheet.create({
  search: { margin: 14, marginBottom: 10, backgroundColor: C.sheet, borderRadius: 12, borderWidth: 1, borderColor: C.line, padding: 12, fontSize: 15 },
  chip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 99, backgroundColor: C.sheet, borderWidth: 1, borderColor: C.line },
  chipOn: { backgroundColor: C.ink, borderColor: C.ink },
  chipT: { color: C.ink2, fontSize: 13 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, backgroundColor: C.sheet, borderRadius: 14, marginBottom: 10, borderWidth: 1, borderColor: C.line },
  img: { width: 56, height: 56, borderRadius: 10, backgroundColor: C.line },
  title: { color: C.ink, fontWeight: '600', fontSize: 15 },
  meta: { color: C.ink3, fontSize: 12.5, marginTop: 3 },
  sub: { borderWidth: 1, borderColor: C.accent, borderRadius: 99, paddingHorizontal: 12, paddingVertical: 6 },
  subOn: { backgroundColor: C.accent },
  subT: { color: C.accent, fontWeight: '600', fontSize: 13 },
});
