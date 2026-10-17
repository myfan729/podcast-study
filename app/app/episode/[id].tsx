import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import * as api from '@/lib/api';
import { addAnchor, toAudio, toContent, type Anchor } from '@/lib/timeline';
import type { Episode, Expression, Pack, RequestResult } from '@/lib/types';
import { C, fmt } from '@/lib/theme';

type Sent = { a: number; b: number; s: number; text: string; ko?: string; speaker?: string; showSpk: boolean };
const RATES = [0.8, 1, 1.2];

export default function EpisodeScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [ep, setEp] = useState<Episode | null>(null);
  const [req, setReq] = useState<RequestResult | null>(null);
  const [pack, setPack] = useState<Pack | null>(null);
  const [err, setErr] = useState('');

  // 1) unlock + queue, 2) poll until ready, 3) load the pack
  useEffect(() => {
    let alive = true, timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const e = await api.episode(id);
        if (!alive) return;
        setEp(e);
        if (e.status === 'ready' && e.pack_path) { setPack(await api.pack(e.pack_path)); return; }
        if (e.status === 'failed' || e.status === 'no_transcript') return;
        timer = setTimeout(tick, 8000);
      } catch (x: any) { setErr(x.message); }
    };
    api.requestEpisode(id).then((r) => {
      if (!alive) return;
      setReq(r);
      if (r.unlocked) tick();
    }).catch((x) => setErr(x.message));
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [id]);

  if (err) return <Center text={'문제가 생겼어요: ' + err} />;
  if (!req) return <Center spin />;
  if (!req.unlocked) {
    return (
      <View style={st.center}>
        <Text style={st.h}>{req.reason === 'quota' ? '이번 주 무료 에피소드를 다 썼어요' : '이 에피소드는 대본이 없어요'}</Text>
        {req.reason === 'quota' && <Text style={st.p}>무료는 일주일에 {2}편까지예요. 프로로 업그레이드하면 무제한으로 들을 수 있어요.</Text>}
        {req.reason === 'quota' && <Pressable style={st.btn} onPress={() => router.push('/settings')}><Text style={st.btnT}>프로 알아보기</Text></Pressable>}
      </View>
    );
  }
  if (!pack) {
    const failed = ep?.status === 'failed' || ep?.status === 'no_transcript';
    return <Center spin={!failed} text={failed ? '이 에피소드는 준비하지 못했어요. 다른 에피소드를 골라 주세요.'
      : '대본·번역·표현을 준비하고 있어요.\n처음 여는 에피소드는 5분 정도 걸려요. 이 화면을 나가도 계속 준비돼요.'} />;
  }
  return <Player pack={pack} ep={ep!} />;
}

function Center({ text, spin }: { text?: string; spin?: boolean }) {
  return <View style={st.center}>{spin && <ActivityIndicator size="large" color={C.accent} />}{text && <Text style={[st.p, { textAlign: 'center', marginTop: 14 }]}>{text}</Text>}</View>;
}

function Player({ pack, ep }: { pack: Pack; ep: Episode }) {
  const player = useAudioPlayer(pack.audio_url, { updateInterval: 250 });
  const status = useAudioPlayerStatus(player);
  const [tab, setTab] = useState<'script' | 'words'>('script');
  const [ko, setKo] = useState(true);
  const [rate, setRate] = useState(1);
  const [syncMode, setSyncMode] = useState(false);
  const [anchors, setAnchors] = useState<Anchor[]>([]);
  const listRef = useRef<FlatList<Sent>>(null);
  const userScroll = useRef(0);
  const key = `anchors:${ep.id}`;

  // sentences (with Korean) from the pack
  const sents: Sent[] = useMemo(() => {
    const cues = pack.transcript.cues, tr = pack.study.translations_sent ?? {};
    const spkOf: Record<number, string | undefined> = {};
    pack.transcript.segments.forEach((sg) => { for (let i = sg.cue_from; i <= sg.cue_to; i++) spkOf[i] = sg.display_speaker; });
    const pairs = pack.transcript.sentences ?? cues.map((_, i) => [i, i] as [number, number]);
    let last: string | undefined;
    return pairs.map(([a, b]) => {
      const sp = spkOf[a]; const showSpk = !!sp && sp !== last; last = sp;
      return { a, b, s: cues[a].s, text: cues.slice(a, b + 1).map((c) => c.t).join(' '), ko: tr[`${a}-${b}`], speaker: sp, showSpk };
    });
  }, [pack]);

  useEffect(() => {
    AsyncStorage.getItem(key).then((v) => { if (v) setAnchors(JSON.parse(v)); }).catch(() => {});
    player.setActiveForLockScreen?.(true, { title: pack.title, artist: pack.show.name, artworkUrl: pack.show.image });
    api.lastPosition(ep.id).then((p) => { if (p > 20) player.seekTo(p); }).catch(() => {});
    return () => { api.saveProgress(ep.id, player.currentTime ?? 0).catch(() => {}); };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const c = toContent(status.currentTime ?? 0, anchors);
  const cur = useMemo(() => { let i = 0; for (let k = 0; k < sents.length; k++) { if (sents[k].s <= c + 0.15) i = k; else break; } return i; }, [c, sents]);
  useEffect(() => {
    if (tab !== 'script' || !status.playing || Date.now() - userScroll.current < 4000) return;
    listRef.current?.scrollToIndex({ index: cur, viewPosition: 0.3, animated: true });
  }, [cur, tab, status.playing]);

  const onSentence = useCallback((sn: Sent) => {
    if (syncMode) {
      const next = addAnchor(anchors, sn.s, Math.max(0, (player.currentTime ?? 0) - 0.4));
      setAnchors(next); AsyncStorage.setItem(key, JSON.stringify(next)).catch(() => {}); setSyncMode(false);
      return;
    }
    player.seekTo(toAudio(sn.s, anchors)); if (!status.playing) player.play();
  }, [syncMode, anchors, player, status.playing, key]);

  const setSpeed = () => { const r = RATES[(RATES.indexOf(rate) + 1) % RATES.length]; setRate(r); player.setPlaybackRate(r); };
  const offset = anchors.length ? Math.round(anchors[anchors.length - 1].a - anchors[anchors.length - 1].c) : 0;

  return (
    <View style={{ flex: 1 }}>
      <Stack.Screen options={{ title: pack.show.name }} />
      <View style={st.tabs}>
        {(['script', 'words'] as const).map((t) => (
          <Pressable key={t} onPress={() => setTab(t)} style={[st.tab, tab === t && st.tabOn]}>
            <Text style={[st.tabT, tab === t && { color: C.ink }]}>{t === 'script' ? '스크립트' : '단어 및 표현'}</Text>
          </Pressable>))}
        {tab === 'script' && <Pressable onPress={() => setKo(!ko)} style={[st.pill, ko && st.pillOn]}><Text style={[st.pillT, ko && { color: '#fff' }]}>한국어</Text></Pressable>}
      </View>
      {tab === 'script' ? (
        <FlatList ref={listRef} data={sents} keyExtractor={(x) => String(x.a)} contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
          ListHeaderComponent={<View style={{ marginBottom: 14 }}><Text style={st.title}>{pack.title}</Text>
            {pack.study.one_liner_ko ? <Text style={st.p}>{pack.study.one_liner_ko}</Text> : null}</View>}
          onScrollBeginDrag={() => { userScroll.current = Date.now(); }}
          onScrollToIndexFailed={() => {}}
          renderItem={({ item, index }) => <SentRow sn={item} active={index === cur} ko={ko} onPress={onSentence} />} />
      ) : (
        <Words pack={pack} episodeId={ep.id} onJump={(sec) => player.seekTo(toAudio(sec, anchors))} />
      )}
      {syncMode && <Text style={st.syncHint}>지금 들리는 문장을 누르세요</Text>}
      <View style={st.bar}>
        <Text style={st.time}>{fmt(status.currentTime)} / {fmt(status.duration)}</Text>
        <View style={st.ctrls}>
          <Btn label="↺5" onPress={() => player.seekTo(Math.max(0, (status.currentTime ?? 0) - 5))} />
          <Pressable onPress={() => (status.playing ? player.pause() : player.play())} style={st.play}>
            <Text style={{ color: '#fff', fontSize: 20 }}>{status.playing ? '❚❚' : '▶'}</Text>
          </Pressable>
          <Btn label="5↻" onPress={() => player.seekTo((status.currentTime ?? 0) + 5)} />
          <Btn label={`${rate.toFixed(1)}×`} onPress={setSpeed} />
          <Btn label={syncMode ? '취소' : offset ? `싱크 ${offset > 0 ? '+' : ''}${offset}s` : '싱크'} onPress={() => setSyncMode(!syncMode)} />
        </View>
      </View>
    </View>
  );
}

const SentRow = memo(function SentRow({ sn, active, ko, onPress }: { sn: Sent; active: boolean; ko: boolean; onPress: (s: Sent) => void }) {
  return (
    <Pressable onPress={() => onPress(sn)} style={[st.sent, active && st.sentOn]}>
      {sn.showSpk && <Text style={st.spk}>{fmt(sn.s)}  {sn.speaker}</Text>}
      <Text style={st.en}>{sn.text}</Text>
      {ko && sn.ko ? <Text style={st.ko}>{sn.ko}</Text> : null}
    </Pressable>
  );
});

function Words({ pack, episodeId, onJump }: { pack: Pack; episodeId: string; onJump: (sec: number) => void }) {
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const segStart = Object.fromEntries(pack.transcript.segments.map((s) => [s.id, s.start]));
  const save = async (kind: 'word' | 'expression', text: string, meaning: string, example?: string) => {
    setSaved(new Set(saved).add(text));
    try { await api.saveItem({ kind, text, meaning_ko: meaning, example, episode_id: episodeId }); } catch { /* shown as saved; retried on next tap */ }
  };
  const vocab = pack.study.vocab ?? [], exprs = pack.study.expressions ?? [];
  return (
    <FlatList data={[{ k: 'v' }, ...exprs.map((e, i) => ({ k: 'e' + i, e }))] as { k: string; e?: Expression }[]}
      keyExtractor={(x) => x.k} contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      renderItem={({ item }) => item.k === 'v' ? (
        <View style={st.card}>
          <Text style={st.cardH}>단어 {vocab.length}</Text>
          {vocab.map((v) => (
            <View key={v.word} style={st.vrow}>
              <View style={{ flex: 1 }}>
                <Text style={st.word}>{v.word} <Text style={st.pos}>{v.pos}</Text></Text>
                <Text style={st.mean}>{v.meaning_ko}</Text>
                {v.example ? <Text style={st.ex}>{v.example}</Text> : null}
              </View>
              <SaveBtn on={saved.has(v.word)} onPress={() => save('word', v.word, v.meaning_ko, v.example)} />
            </View>))}
          <Text style={[st.cardH, { marginTop: 18 }]}>표현 {exprs.length}</Text>
        </View>
      ) : (
        <View style={st.card}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Text style={[st.word, { flex: 1 }]}>{item.e!.expression}</Text>
            {item.e!.segment_id && segStart[item.e!.segment_id] != null &&
              <Pressable onPress={() => onJump(segStart[item.e!.segment_id!])}><Text style={st.jump}>▶ {fmt(segStart[item.e!.segment_id!])}</Text></Pressable>}
            <SaveBtn on={saved.has(item.e!.expression)} onPress={() => save('expression', item.e!.expression, item.e!.meaning_ko, item.e!.examples?.[0])} />
          </View>
          <Text style={st.mean}>{item.e!.meaning_ko}</Text>
          {item.e!.nuance_ko ? <Text style={st.p}>{item.e!.nuance_ko}</Text> : null}
          {item.e!.quote ? <Text style={st.quote}>“{item.e!.quote}”</Text> : null}
          {(item.e!.examples ?? []).map((x) => <Text key={x} style={st.ex}>• {x}</Text>)}
          {(item.e!.similar ?? []).map((x) => <Text key={x.expression} style={st.ex}>≈ <Text style={{ fontWeight: '600' }}>{x.expression}</Text> — {x.example}</Text>)}
        </View>
      )} />
  );
}

const Btn = ({ label, onPress }: { label: string; onPress: () => void }) => (
  <Pressable onPress={onPress} style={st.btnS}><Text style={st.btnST}>{label}</Text></Pressable>);
const SaveBtn = ({ on, onPress }: { on: boolean; onPress: () => void }) => (
  <Pressable onPress={onPress} hitSlop={8}><Text style={{ fontSize: 18, color: on ? C.accent : C.ink3 }}>{on ? '★' : '☆'}</Text></Pressable>);

const st = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28 },
  h: { fontSize: 18, fontWeight: '700', color: C.ink, textAlign: 'center', marginBottom: 8 },
  p: { color: C.ink2, lineHeight: 21, fontSize: 14 },
  btn: { backgroundColor: C.accent, padding: 14, borderRadius: 12, marginTop: 18, paddingHorizontal: 24 },
  btnT: { color: '#fff', fontWeight: '700' },
  title: { fontSize: 20, fontWeight: '700', color: C.ink, lineHeight: 27, marginBottom: 6 },
  tabs: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingTop: 8 },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 99 },
  tabOn: { backgroundColor: C.sheet },
  tabT: { color: C.ink3, fontWeight: '600' },
  pill: { marginLeft: 'auto', borderWidth: 1, borderColor: C.accent, borderRadius: 99, paddingHorizontal: 10, paddingVertical: 5 },
  pillOn: { backgroundColor: C.accent },
  pillT: { color: C.accent, fontSize: 12.5, fontWeight: '600' },
  sent: { paddingVertical: 7, paddingHorizontal: 8, borderRadius: 10 },
  sentOn: { backgroundColor: '#fff6c2' },
  spk: { color: C.ink3, fontSize: 12, marginTop: 10, marginBottom: 2 },
  en: { color: C.ink, fontSize: 17, lineHeight: 26 },
  ko: { color: C.ink3, fontSize: 13.5, lineHeight: 20, marginTop: 2 },
  syncHint: { textAlign: 'center', backgroundColor: C.ink, color: '#fff', padding: 8 },
  bar: { borderTopWidth: 1, borderColor: C.line, backgroundColor: C.sheet, paddingHorizontal: 14, paddingTop: 8, paddingBottom: 22 },
  time: { color: C.ink3, fontSize: 12, textAlign: 'center', marginBottom: 6 },
  ctrls: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  play: { width: 52, height: 52, borderRadius: 26, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center' },
  btnS: { minWidth: 46, height: 38, borderRadius: 19, borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 10 },
  btnST: { color: C.ink, fontSize: 13 },
  card: { backgroundColor: C.sheet, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: C.line, marginBottom: 12 },
  cardH: { fontWeight: '700', color: C.ink, marginBottom: 8 },
  vrow: { flexDirection: 'row', gap: 10, paddingVertical: 8, borderTopWidth: 1, borderColor: C.line },
  word: { fontWeight: '700', color: C.ink, fontSize: 15.5 },
  pos: { fontWeight: '400', color: C.ink3, fontSize: 12.5 },
  mean: { color: C.ink, marginTop: 3, fontSize: 14.5 },
  ex: { color: C.ink2, fontSize: 13.5, marginTop: 4, lineHeight: 19 },
  quote: { color: C.ink2, fontStyle: 'italic', marginTop: 6, fontSize: 13.5 },
  jump: { color: C.accent, fontSize: 13 },
});
