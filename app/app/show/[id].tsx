import { Stack, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { FlatList, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import EpisodeRow from '@/components/EpisodeRow';
import * as api from '@/lib/api';
import type { Episode, Show } from '@/lib/types';
import { C } from '@/lib/theme';

export default function ShowScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [show, setShow] = useState<Show | null>(null);
  const [eps, setEps] = useState<Episode[]>([]);
  const [sub, setSub] = useState(false);
  useEffect(() => {
    api.show(id).then(setShow);
    api.showEpisodes(id).then(setEps);
    api.mySubscriptions().then((ids) => setSub(ids.includes(id)));
  }, [id]);
  const toggle = async () => { setSub(!sub); try { await api.setSubscribed(id, !sub); } catch { setSub(sub); } };
  return (
    <>
      <Stack.Screen options={{ title: show?.title ?? '' }} />
      <FlatList contentContainerStyle={{ padding: 14 }} data={eps.filter((e) => e.has_transcript)} keyExtractor={(e) => e.id}
        ListHeaderComponent={show ? (
          <View style={s.head}>
            {show.image_url ? <Image source={{ uri: show.image_url }} style={s.img} /> : null}
            <View style={{ flex: 1 }}>
              <Text style={s.title}>{show.title}</Text>
              <Text style={s.meta}>{show.author}</Text>
              <Pressable onPress={toggle} style={[s.btn, sub && s.btnOn]}>
                <Text style={[s.btnT, sub && { color: '#fff' }]}>{sub ? '구독 중' : '구독하기'}</Text>
              </Pressable>
            </View>
          </View>) : undefined}
        renderItem={({ item }) => <EpisodeRow ep={item} />} />
    </>
  );
}
const s = StyleSheet.create({
  head: { flexDirection: 'row', gap: 14, marginBottom: 16 },
  img: { width: 96, height: 96, borderRadius: 14 },
  title: { fontSize: 19, fontWeight: '700', color: C.ink },
  meta: { color: C.ink3, marginTop: 4, marginBottom: 10 },
  btn: { alignSelf: 'flex-start', borderWidth: 1, borderColor: C.accent, borderRadius: 99, paddingHorizontal: 14, paddingVertical: 7 },
  btnOn: { backgroundColor: C.accent },
  btnT: { color: C.accent, fontWeight: '600' },
});
