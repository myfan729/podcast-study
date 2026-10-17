import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import EpisodeRow from '@/components/EpisodeRow';
import { Art, Icon, RoundBtn } from '@/components/ui';
import * as api from '@/lib/api';
import type { Episode, Show } from '@/lib/types';
import { C, F, R } from '@/lib/theme';

export default function ShowScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
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
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <View style={s.top}><RoundBtn icon="chevron-back" label="뒤로" onPress={() => router.back()} /></View>
      <FlatList contentContainerStyle={{ padding: 16, paddingBottom: 32 }} data={eps.filter((e) => e.has_transcript)} keyExtractor={(e) => e.id}
        ListHeaderComponent={show ? (
          <View style={s.head}>
            <Art uri={show.image_url} id={show.id} size={120} radius={28} />
            <Text style={s.title}>{show.title}</Text>
            <Text style={s.meta}>{show.author}{show.level ? ` · ${show.level}` : ''}</Text>
            {show.intro_ko ? <Text style={s.intro}>{show.intro_ko}</Text> : null}
            {show.description ? <Text style={s.desc} numberOfLines={3}>{show.description}</Text> : null}
            <Pressable onPress={toggle} style={[s.btn, sub && s.btnOn]} accessibilityRole="button">
              <Icon name={sub ? 'checkmark' : 'add'} size={18} color={sub ? C.accent : '#fff'} />
              <Text style={[s.btnT, sub && { color: C.accent }]}>{sub ? '구독 중' : '구독하기'}</Text>
            </Pressable>
            <Text style={s.sec}>에피소드</Text>
          </View>) : undefined}
        renderItem={({ item }) => <EpisodeRow ep={item} />} />
    </SafeAreaView>
  );
}
const s = StyleSheet.create({
  top: { paddingHorizontal: 16, paddingTop: 6 },
  head: { alignItems: 'center', marginBottom: 6 },
  title: { fontFamily: F.enX, fontSize: 22, color: C.ink, textAlign: 'center', marginTop: 14 },
  meta: { color: C.ink3, marginTop: 4 },
  intro: { color: C.ink2, textAlign: 'center', fontSize: 13.5, lineHeight: 19, marginTop: 10, paddingHorizontal: 8 },
  desc: { color: C.ink3, textAlign: 'center', fontSize: 12, lineHeight: 17, marginTop: 6, paddingHorizontal: 8 },
  btn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: C.accent, borderRadius: R.pill, paddingHorizontal: 22, minHeight: 48, marginTop: 16 },
  btnOn: { backgroundColor: C.accentSoft },
  btnT: { color: '#fff', fontWeight: '700', fontSize: 15 },
  sec: { alignSelf: 'flex-start', fontSize: 16, fontWeight: '700', color: C.ink, marginTop: 26, marginBottom: 4, marginLeft: 6 },
});
