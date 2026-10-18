// Plain listening: what opening an episode does by default, like any podcast app. The audio streams
// straight from the publisher; no study pack, no quota. "학습자료 만들기" turns on the study mode
// (transcript, translation, words) — that is the part free users get twice a week.
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Art, Icon, RoundBtn } from '@/components/ui';
import SeekBar from '@/components/SeekBar';
import * as api from '@/lib/api';
import { useNowPlaying } from '@/lib/nowPlaying';
import { FREE_PER_WEEK } from '@/lib/config';
import type { Episode } from '@/lib/types';
import { C, F, R, fmt } from '@/lib/theme';

const RATES = [0.8, 1, 1.2, 1.5];
const plain = (html?: string | null) =>
  (html ?? '').replace(/<br\s*\/?>|<\/p>/gi, '\n').replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
    .replace(/&#39;|&rsquo;/g, "'").replace(/&quot;|&ldquo;|&rdquo;/g, '"').replace(/\n{3,}/g, '\n\n').trim();

export default function ListenView({ ep, unlocked, onStudy }: { ep: Episode; unlocked: boolean; onStudy: () => void }) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  // the app-wide player: keeps going when the user leaves this screen (mini player, lock screen)
  const np = useNowPlaying();
  const player = np.player;
  const mine = np.ep?.id === ep.id;
  const status = mine ? np.status : { ...np.status, playing: false, isLoaded: false, currentTime: 0, duration: 0 };
  const [rate, setRate] = useState(1);
  const [dragSec, setDragSec] = useState<number | null>(null);    // time under the finger while dragging the bar
  const [plan, setPlan] = useState<{ free_left: number; pro: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);

  useEffect(() => { api.freeLeft().then(setPlan).catch(() => {}); }, []);
  useEffect(() => { np.load(ep); }, [ep.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const dur = status.duration || ep.duration_sec || 1;
  const pct = Math.min(1, (status.currentTime ?? 0) / dur);
  const left = plan?.free_left ?? 0;
  const canMake = ep.has_transcript && (unlocked || plan?.pro || left > 0);

  const study = async () => {
    if (unlocked) { leave(); return; }
    const go = async () => {
      setBusy(true);
      try {
        const r = await api.requestEpisode(ep.id);
        if (r.unlocked) leave();
        else Alert.alert(r.reason === 'quota' ? '이번 주 무료 학습자료를 다 썼어요' : '학습자료를 만들 수 없어요',
          r.reason === 'quota' ? '무료는 일주일에 2편까지예요. 듣기는 계속 무제한이에요.' : '방송사 대본이 아직 없어요. 나중에 다시 시도해 주세요.');
      } catch (e: any) { Alert.alert('문제가 생겼어요', String(e?.message ?? e)); } finally { setBusy(false); }
    };
    if (plan?.pro) { go(); return; }
    const msg = `이번 주 무료 학습자료 ${left}회 중 1회를 써요. 한 번 만든 에피소드는 언제든 다시 볼 수 있어요.`;
    if (Platform.OS === 'web') { if (globalThis.confirm?.(msg)) go(); return; }
    Alert.alert('학습자료를 만들까요?', msg, [{ text: '취소', style: 'cancel' }, { text: '만들기', onPress: go }]);
  };
  const leave = () => { np.stop(); onStudy(); };   // the study mode plays its own synced copy, from the same position

  const desc = plain(ep.description);
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <View style={s.top}><RoundBtn icon="chevron-back" label="뒤로" onPress={() => router.back()} /></View>
      <ScrollView contentContainerStyle={{ paddingHorizontal: 22, paddingBottom: 24 }}>
        <View style={{ alignItems: 'center' }}>
          <Art uri={ep.image_url ?? ep.shows?.image_url} id={ep.show_id} size={200} radius={28} />
          <Text style={s.show}>{ep.shows?.title}</Text>
          <Text style={s.title}>{ep.title}</Text>
          <Text style={s.meta}>{ep.published_at?.slice(0, 10)}{ep.duration_sec ? ` · ${Math.round(ep.duration_sec / 60)}분` : ''}</Text>
          {ep.intro_ko ? <Text style={s.intro}>{ep.intro_ko}</Text> : null}
        </View>

        <View style={s.studyCard}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Icon name="sparkles" size={18} color={C.accent} />
            <Text style={s.studyH}>{unlocked ? '학습자료' : '학습자료 만들기'}</Text>
            {!unlocked && plan && !plan.pro ? <Text style={s.quota}>이번 주 {left}/{FREE_PER_WEEK}회</Text> : null}
          </View>
          <Text style={s.studyP}>대본을 문장별로 따라가며 듣고, 한국어 번역과 단어·표현 정리를 볼 수 있어요.</Text>
          {!ep.has_transcript
            ? <Text style={s.note}>이 에피소드는 방송사 대본이 없어 학습자료를 만들 수 없어요.</Text>
            : (
              <Pressable onPress={study} disabled={busy || !canMake} accessibilityRole="button"
                style={[s.studyBtn, (!canMake) && { opacity: 0.45 }]}>
                {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.studyBtnT}>
                  {unlocked ? '학습 모드로 보기' : canMake ? '학습자료 만들기' : '이번 주 무료 횟수를 다 썼어요'}</Text>}
              </Pressable>)}
          {!unlocked && plan && !plan.pro && !canMake && ep.has_transcript
            ? <Text style={s.note}>프로는 무제한이에요. 듣기는 계속 무료예요.</Text> : null}
        </View>

        {desc ? (
          <Pressable onPress={() => setMore(!more)}>
            <Text style={s.desc} numberOfLines={more ? undefined : 5}>{desc}</Text>
            <Text style={s.moreT}>{more ? '접기' : '더 보기'}</Text>
          </Pressable>) : null}
      </ScrollView>

      <View style={[s.bar, { marginBottom: Math.max(insets.bottom, 0) + 12 }]}>
        <SeekBar position={status.currentTime ?? 0} duration={dur} onDrag={setDragSec} onSeek={(sec) => player.seekTo(sec)} />
        <View style={s.timeRow}>
          <Text style={s.time}>{fmt(dragSec ?? status.currentTime)}</Text>
          <Text style={s.time}>-{fmt(Math.max(0, dur - (status.currentTime ?? 0)))}</Text>
        </View>
        <View style={s.ctrls}>
          <Pressable onPress={() => { const r = RATES[(RATES.indexOf(rate) + 1) % RATES.length]; setRate(r); player.setPlaybackRate(r); }}
            style={s.side} accessibilityLabel="재생 속도"><Text style={s.sideT}>{rate.toFixed(1)}x</Text></Pressable>
          <RoundBtn icon="play-back" label="15초 뒤로" size={48} bg="transparent" color="#fff"
            onPress={() => player.seekTo(Math.max(0, (status.currentTime ?? 0) - 15))} />
          {!status.isLoaded
            ? <View style={s.wait}><ActivityIndicator color={C.dark} /></View>
            : <RoundBtn icon={status.playing ? 'pause' : 'play'} label={status.playing ? '일시정지' : '재생'} size={64} bg="#fff" color={C.dark}
                onPress={() => (status.playing ? player.pause() : player.play())} />}
          <RoundBtn icon="play-forward" label="30초 앞으로" size={48} bg="transparent" color="#fff"
            onPress={() => player.seekTo((status.currentTime ?? 0) + 30)} />
          <View style={[s.side, { backgroundColor: 'transparent' }]} />
        </View>
      </View>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  top: { paddingHorizontal: 16, paddingTop: 6 },
  show: { color: C.ink3, fontSize: 12.5, marginTop: 16 },
  title: { fontFamily: F.enX, fontSize: 20, lineHeight: 26, color: C.ink, textAlign: 'center', marginTop: 4 },
  meta: { color: C.ink3, fontSize: 12, marginTop: 6 },
  intro: { color: C.ink2, fontSize: 13, lineHeight: 19, textAlign: 'center', marginTop: 8 },
  studyCard: { marginTop: 22, padding: 18, borderRadius: R.card, backgroundColor: C.sheet, gap: 10 },
  studyH: { fontFamily: F.title, fontSize: 18, color: C.ink },
  quota: { marginLeft: 'auto', color: C.accent, fontSize: 12.5, fontWeight: '700' },
  studyP: { color: C.ink2, fontSize: 13.5, lineHeight: 20 },
  studyBtn: { backgroundColor: C.accent, borderRadius: R.pill, minHeight: 50, alignItems: 'center', justifyContent: 'center', marginTop: 4 },
  studyBtnT: { color: '#fff', fontWeight: '700', fontSize: 15.5 },
  note: { color: C.ink3, fontSize: 12.5, lineHeight: 18 },
  desc: { color: C.ink2, fontSize: 13.5, lineHeight: 21, marginTop: 22 },
  moreT: { color: C.accent, fontSize: 13, fontWeight: '700', marginTop: 6 },
  bar: { marginHorizontal: 12, paddingHorizontal: 18, paddingTop: 16, paddingBottom: 12, borderRadius: 32, backgroundColor: C.dark, gap: 6 },
  track: { height: 6, borderRadius: 3, backgroundColor: C.track, overflow: 'hidden' },
  fill: { height: 6, borderRadius: 3, backgroundColor: C.progress },
  timeRow: { flexDirection: 'row', justifyContent: 'space-between' },
  time: { color: '#C9C6DC', fontSize: 12, fontVariant: ['tabular-nums'] },
  ctrls: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', height: 66 },
  side: { width: 56, height: 40, borderRadius: 20, backgroundColor: C.dark2, alignItems: 'center', justifyContent: 'center' },
  sideT: { color: '#fff', fontWeight: '700', fontSize: 13 },
  wait: { width: 64, height: 64, borderRadius: 32, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
});
