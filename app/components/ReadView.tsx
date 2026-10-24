// Free: read the publisher's transcript while listening. The phone downloads it straight from the
// publisher (nothing of it is stored by us) and shows it as plain paragraphs. Following the voice
// sentence by sentence (sync) and the word/expression notes are the premium study mode.
import { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Icon, RoundBtn } from '@/components/ui';
import { useNowPlaying } from '@/lib/nowPlaying';
import { fetchTranscript, type Transcript } from '@/lib/transcript';
import type { Episode } from '@/lib/types';
import { C, F, R, fmt } from '@/lib/theme';

type Para = { id: string; speaker: string | null; showSpk: boolean; text: string };

export default function ReadView({ ep, onClose, onStudy, studyLabel }: { ep: Episode; onClose: () => void; onStudy?: () => void; studyLabel?: string }) {
  const insets = useSafeAreaInsets();
  const np = useNowPlaying();
  const mine = np.ep?.id === ep.id;
  const [tr, setTr] = useState<Transcript | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (!ep.transcript_url) { setErr('대본 주소가 아직 없어요'); return; }
    fetchTranscript(ep.transcript_url, ep.transcript_kind ?? 'unknown').then(setTr).catch((e) => setErr(String(e?.message ?? e)));
  }, [ep.transcript_url, ep.transcript_kind]);

  const paras: Para[] = useMemo(() => {
    if (!tr) return [];
    let last: string | null = null;
    return tr.segments.map((g) => {
      const text = tr.cues.slice(g.cue_from, g.cue_to + 1).map((c) => c.t).join(' ');
      const showSpk = !!g.speaker && g.speaker !== last; last = g.speaker;
      return { id: g.id, speaker: g.speaker, showSpk, text };
    });
  }, [tr]);

  const st = np.status;
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <View style={s.top}>
        <RoundBtn icon="chevron-back" label="닫기" onPress={onClose} />
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={s.topShow} numberOfLines={1}>{ep.shows?.title}</Text>
          <Text style={s.topTitle} numberOfLines={1}>{ep.title}</Text>
        </View>
      </View>
      {err ? <View style={s.center}><Text style={s.p}>{err}</Text></View>
        : !tr ? <View style={s.center}><ActivityIndicator color={C.accent} /><Text style={[s.p, { marginTop: 10 }]}>방송사에서 대본을 불러오는 중…</Text></View>
        : (
          <FlatList data={paras} keyExtractor={(x) => x.id} contentContainerStyle={{ padding: 20, paddingBottom: 30 }}
            ListHeaderComponent={onStudy ? (
              <Pressable style={s.up} onPress={onStudy} accessibilityRole="button">
                <Icon name="sparkles" size={18} color={C.accent} />
                <View style={{ flex: 1 }}>
                  <Text style={s.upH}>{studyLabel ?? '학습 모드로 보기'}</Text>
                  <Text style={s.upP}>들리는 문장을 따라가며 보기 · 단어·표현 정리 · 문장 번역</Text>
                </View>
                <Icon name="chevron-forward" size={18} color={C.accent} />
              </Pressable>) : undefined}
            ListFooterComponent={<Text style={s.credit}>대본·오디오의 저작권은 {ep.shows?.title ?? '제작사'}에 있어요. 대본은 방송사가 공개한 파일을 이 기기에서 바로 불러와 보여 줘요.</Text>}
            renderItem={({ item }) => (
              <View style={{ marginBottom: 14 }}>
                {item.showSpk ? <Text style={s.spk}>{item.speaker}</Text> : null}
                <Text style={s.en} selectable={false}>{item.text}</Text>
              </View>)} />
        )}
      {mine ? (
        <View style={[s.bar, { marginBottom: Math.max(insets.bottom, 0) + 10 }]}>
          <Text style={s.time}>{fmt(st.currentTime)} / {fmt(st.duration)}</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <RoundBtn icon="play-back" label="15초 뒤로" size={42} bg="transparent" color="#fff" onPress={() => np.player.seekTo(Math.max(0, (st.currentTime ?? 0) - 15))} />
            <RoundBtn icon={st.playing ? 'pause' : 'play'} label={st.playing ? '일시정지' : '재생'} size={48} bg="#fff" color={C.dark}
              onPress={() => (st.playing ? np.player.pause() : np.player.play())} />
            <RoundBtn icon="play-forward" label="30초 앞으로" size={42} bg="transparent" color="#fff" onPress={() => np.player.seekTo((st.currentTime ?? 0) + 30)} />
          </View>
        </View>) : null}
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingTop: 6 },
  topShow: { color: C.ink3, fontSize: 12 },
  topTitle: { color: C.ink, fontFamily: F.enB, fontSize: 14.5 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28 },
  p: { color: C.ink2, fontSize: 14, lineHeight: 21, textAlign: 'center' },
  up: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: C.accentSoft, borderRadius: R.card, padding: 14, marginBottom: 18 },
  upH: { color: C.ink, fontWeight: '700', fontSize: 14.5 },
  upP: { color: C.ink2, fontSize: 12.5, marginTop: 2 },
  spk: { color: C.ink3, fontSize: 12, marginBottom: 3 },
  en: { color: C.ink, fontFamily: F.en, fontSize: 15.5, lineHeight: 24 },
  credit: { color: C.ink3, fontSize: 11.5, lineHeight: 16, marginTop: 10 },
  bar: { marginHorizontal: 12, paddingHorizontal: 18, paddingVertical: 8, borderRadius: 28, backgroundColor: C.dark, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  time: { color: '#C9C6DC', fontSize: 12, fontVariant: ['tabular-nums'] },
});
