import { Link, useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import EpisodeRow from '@/components/EpisodeRow';
import { Art, Btn, Icon, Logo } from '@/components/ui';
import * as api from '@/lib/api';
import type { Episode } from '@/lib/types';
import { C, F, R, mins } from '@/lib/theme';

type Cont = { position: number; ep: Episode } | null;

export default function Home() {
  const router = useRouter();
  const [eps, setEps] = useState<Episode[]>([]);
  const [subs, setSubs] = useState<string[] | null>(null);
  const [cont, setCont] = useState<Cont>(null);
  const [plan, setPlan] = useState<{ free_left: number; pro: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    try {
      const ids = await api.mySubscriptions(); setSubs(ids);
      const [f, c, p] = await Promise.all([api.feed(ids), api.continueListening().catch(() => null), api.freeLeft().catch(() => null)]);
      setEps(f); setCont(c); setPlan(p);
    } finally { setBusy(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const fresh = eps.slice(0, 6), rest = eps.slice(6);
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }} refreshControl={<RefreshControl refreshing={busy} onRefresh={load} tintColor={C.accent} />}>
        <View style={s.head}>
          <Logo />
          {plan && <View style={s.plan}><Text style={s.planT}>{plan.pro ? '프로' : `학습자료 ${plan.free_left}회 남음`}</Text></View>}
        </View>
        <Text style={s.hello}>{cont ? '어제 듣던 거,\n마저 들어볼까요?' : '오늘은 뭘\n들어볼까요?'}</Text>

        {cont && (
          <Pressable style={s.cont}
            onPress={() => router.push({ pathname: '/episode/[id]', params: { id: cont.ep.id } })}>
            <View style={s.play}><Icon name="play" size={22} color={C.accent} /></View>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={s.contMeta}>이어 듣기 · {mins(Math.max(0, (cont.ep.duration_sec ?? 0) - cont.position))} 남음</Text>
              <Text style={s.contT} numberOfLines={2}>{cont.ep.title}</Text>
              <View style={s.track}><View style={[s.fill, { width: `${Math.round(100 * Math.min(1, cont.position / (cont.ep.duration_sec || 1)))}%` }]} /></View>
            </View>
          </Pressable>
        )}

        {subs && !subs.length ? (
          <View style={s.empty}>
            <View style={s.emptyArt}><Icon name="headset" size={34} color={C.accent} /></View>
            <Text style={s.emptyH}>구독한 쇼가 아직 없어요</Text>
            <Text style={s.emptyP}>듣고 싶은 팟캐스트를 구독하면{'\n'}새 에피소드가 여기 모여요.</Text>
            <Link href="/discover" asChild><Btn label="쇼 찾아보기" style={{ alignSelf: 'stretch', marginTop: 18 }} /></Link>
          </View>
        ) : (
          <>
            {fresh.length > 0 && <View style={s.secRow}>
              <Text style={[s.sec, { paddingHorizontal: 0, marginTop: 0, marginBottom: 0 }]}>새로 올라온 에피소드</Text>
              <Link href={{ pathname: '/discover', params: { tab: 'subs' } }} asChild>
                <Pressable hitSlop={8} accessibilityRole="button"><Text style={s.manage}>구독 {subs?.length ?? 0}개 관리 ›</Text></Pressable>
              </Link>
            </View>}
            <FlatList horizontal data={fresh} keyExtractor={(e) => e.id} showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: 22, gap: 12 }}
              renderItem={({ item }) => (
                <Link href={{ pathname: '/episode/[id]', params: { id: item.id } }} asChild>
                  <Pressable style={s.tile}>
                    <Art uri={item.shows?.image_url} id={item.show_id} size={126} />
                    <Text style={s.tileShow} numberOfLines={1}>{item.shows?.title}</Text>
                    <Text style={s.tileT} numberOfLines={2}>{item.title}</Text>
                    {item.intro_ko ? <Text style={s.tileIntro} numberOfLines={2}>{item.intro_ko}</Text> : null}
                    <Text style={s.tileMeta}>{mins(item.duration_sec)}</Text>
                  </Pressable>
                </Link>)} />
            {rest.length > 0 && <Text style={s.sec}>지난 에피소드</Text>}
            <View style={{ paddingHorizontal: 16 }}>{rest.map((e) => <EpisodeRow key={e.id} ep={e} showTitle />)}</View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 22, paddingTop: 10 },
  plan: { backgroundColor: C.sheet, borderRadius: R.pill, paddingHorizontal: 12, paddingVertical: 7 },
  planT: { color: C.streak, fontSize: 12.5, fontWeight: '700' },
  hello: { fontFamily: F.title, fontSize: 25, lineHeight: 34, color: C.ink, paddingHorizontal: 22, marginTop: 18 },
  cont: { flexDirection: 'row', alignItems: 'center', gap: 14, marginHorizontal: 22, marginTop: 16, padding: 18, borderRadius: R.card, backgroundColor: C.accent },
  contMeta: { color: '#E6E0FF', fontSize: 12 },
  contT: { color: '#fff', fontFamily: F.enB, fontSize: 16, lineHeight: 21, marginTop: 4 },
  play: { width: 56, height: 56, borderRadius: 28, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', paddingLeft: 3 },
  track: { height: 5, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.3)', marginTop: 10 },
  fill: { height: 5, borderRadius: 3, backgroundColor: '#fff' },
  secRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 22, marginTop: 26, marginBottom: 12 },
  manage: { color: C.accent, fontSize: 13, fontWeight: '700' },
  sec: { fontSize: 16, fontWeight: '700', color: C.ink, paddingHorizontal: 22, marginTop: 26, marginBottom: 12 },
  tile: { width: 150, padding: 12, borderRadius: R.tile, backgroundColor: C.sheet, gap: 6 },
  tileShow: { color: C.ink3, fontSize: 11.5, marginTop: 4 },
  tileT: { color: C.ink, fontFamily: F.enB, fontSize: 14, lineHeight: 18, minHeight: 36 },
  tileMeta: { color: C.ink3, fontSize: 12 },
  tileIntro: { color: C.ink3, fontSize: 11.5, lineHeight: 15 },
  empty: { margin: 22, marginTop: 28, padding: 24, borderRadius: R.card, backgroundColor: C.sheet, alignItems: 'center' },
  emptyArt: { width: 72, height: 72, borderRadius: 36, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  emptyH: { fontFamily: F.title, fontSize: 20, color: C.ink },
  emptyP: { color: C.ink2, textAlign: 'center', lineHeight: 21, marginTop: 8 },
});
