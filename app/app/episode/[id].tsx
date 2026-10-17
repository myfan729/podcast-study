import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { memo, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Btn, Icon, RoundBtn } from '@/components/ui';
import AutoSync, { type SyncResult } from '@/components/AutoSync';
import * as api from '@/lib/api';
import { addAnchor, toAudio, toContent, type Anchor } from '@/lib/timeline';
import type { Episode, Expression, Pack, RequestResult } from '@/lib/types';
import { C, F, R, fmt, shadow } from '@/lib/theme';

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
      <Center icon={req.reason === 'quota' ? 'lock-closed' : 'document-text-outline'}
        title={req.reason === 'quota' ? '이번 주 무료 에피소드를 다 썼어요' : '이 에피소드는 대본이 없어요'}
        text={req.reason === 'quota' ? '무료는 일주일에 2편까지예요. 프로로 업그레이드하면 무제한으로 들을 수 있어요.' : undefined}>
        {req.reason === 'quota' && <Btn label="프로 알아보기" onPress={() => router.push('/settings')} style={{ alignSelf: 'stretch', marginTop: 20 }} />}
      </Center>
    );
  }
  if (!pack) {
    const failed = ep?.status === 'failed' || ep?.status === 'no_transcript';
    return failed
      ? <Center icon="alert-circle-outline" title="준비하지 못했어요" text="이 에피소드는 대본을 만들 수 없었어요. 다른 에피소드를 골라 주세요." />
      : <Center spin title="에피소드를 준비하고 있어요" text={'대본·번역·표현을 만드는 중이에요.\n처음 여는 에피소드는 1~2분 정도 걸려요.\n이 화면을 나가도 계속 준비돼요.'} />;
  }
  return <Player pack={pack} ep={ep!} />;
}

function Center({ text, title, spin, icon, children }: { text?: string; title?: string; spin?: boolean; icon?: 'lock-closed' | 'document-text-outline' | 'alert-circle-outline'; children?: ReactNode }) {
  const router = useRouter();
  return (
    <SafeAreaView style={{ flex: 1 }}>
      <View style={{ paddingHorizontal: 16, paddingTop: 6 }}><RoundBtn icon="chevron-back" label="뒤로" onPress={() => router.back()} /></View>
      <View style={st.center}>
        <View style={st.centerArt}>{spin ? <ActivityIndicator size="large" color={C.accent} /> : icon ? <Icon name={icon} size={34} color={C.accent} /> : null}</View>
        {title ? <Text style={st.h}>{title}</Text> : null}
        {text ? <Text style={[st.p, { textAlign: 'center', marginTop: 8 }]}>{text}</Text> : null}
        {children}
      </View>
    </SafeAreaView>
  );
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

  // automatic ad-aware sync (needs the server's reference fingerprints for this episode)
  const [syncRef, setSyncRef] = useState<unknown>(null);
  const [auto, setAuto] = useState<'off' | 'working' | 'auto' | 'failed'>('off');
  const [autoMsg, setAutoMsg] = useState('');
  useEffect(() => {
    if (!ep.sync_path || Platform.OS === 'web') return;              // the web build has no WebView / file system
    setAuto('working');
    api.syncData(ep.sync_path).then(setSyncRef).catch(() => setAuto('failed'));
  }, [ep.sync_path]);
  const onAutoDone = useCallback(async (r: SyncResult | null) => {
    if (!r || !r.ok) { setAuto('failed'); return; }
    const c = toContent(player.currentTime ?? 0, anchors), wasPlaying = player.playing;
    setAnchors(r.anchors); AsyncStorage.setItem(key, JSON.stringify(r.anchors)).catch(() => {});
    player.replace({ uri: r.fileUri });                         // play exactly the copy that was aligned
    player.setActiveForLockScreen?.(true, { title: pack.title, artist: pack.show.name, artworkUrl: pack.show.image });
    setAuto('auto');
    await new Promise((res) => setTimeout(res, 700));
    await player.seekTo(toAudio(c, r.anchors));
    if (wasPlaying) player.play();
  }, [anchors, player, key, pack]);

  const setSpeed = () => { const r = RATES[(RATES.indexOf(rate) + 1) % RATES.length]; setRate(r); player.setPlaybackRate(r); };
  const offset = anchors.length ? Math.round(anchors[anchors.length - 1].a - anchors[anchors.length - 1].c) : 0;

  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [barW, setBarW] = useState(1);
  const dur = status.duration || pack.duration_sec || 1;
  const pct = Math.min(1, (status.currentTime ?? 0) / dur);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      {syncRef && auto === 'working' && pack.audio_url ? (
        <AutoSync episodeId={ep.id} audioUrl={pack.audio_url} syncRef={syncRef} onStatus={setAutoMsg} onDone={onAutoDone} />) : null}
      <View style={st.top}>
        <RoundBtn icon="chevron-back" label="뒤로" onPress={() => router.back()} />
        <View style={{ flex: 1, minWidth: 0, alignItems: 'center' }}>
          <Text style={st.topShow} numberOfLines={1}>{pack.show.name}</Text>
          <Text style={st.topTitle} numberOfLines={1}>{pack.title}</Text>
        </View>
        <View style={{ width: 44 }} />
      </View>
      <View style={st.seg}>
        {(['script', 'words'] as const).map((t) => (
          <Pressable key={t} onPress={() => setTab(t)} style={[st.segB, tab === t && st.segOn]} accessibilityRole="tab" accessibilityState={{ selected: tab === t }}>
            <Text style={[st.segT, tab === t && { color: C.ink, fontWeight: '700' }]}>{t === 'script' ? '스크립트' : '단어·표현'}</Text>
          </Pressable>))}
      </View>
      {tab === 'script' ? (
        <FlatList ref={listRef} data={sents} keyExtractor={(x) => String(x.a)} contentContainerStyle={{ padding: 18, paddingBottom: 40 }}
          ListHeaderComponent={pack.study.one_liner_ko ? <View style={st.oneBox}><Icon name="bulb-outline" size={16} color={C.accent} /><Text style={st.one}>{pack.study.one_liner_ko}</Text></View> : undefined}
          onScrollBeginDrag={() => { userScroll.current = Date.now(); }}
          onScrollToIndexFailed={() => {}}
          renderItem={({ item, index }) => <SentRow sn={item} state={index === cur ? 'cur' : index < cur ? 'past' : 'next'} ko={ko} onPress={onSentence} />} />
      ) : (
        <Words pack={pack} episodeId={ep.id} onJump={(sec) => player.seekTo(toAudio(sec, anchors))} />
      )}
      {auto === 'failed' && !syncMode && !anchors.length && <View style={st.syncHint}><Icon name="information-circle-outline" size={16} color={C.accent} /><Text style={st.syncT}>자동 싱크 실패 · 싱크를 누르고 들리는 문장을 눌러 주세요</Text></View>}
      {syncMode && <View style={st.syncHint}><Icon name="hand-left-outline" size={16} color={C.accent} /><Text style={st.syncT}>지금 들리는 문장을 눌러 주세요</Text></View>}
      <View style={[st.bar, { marginBottom: Math.max(insets.bottom, 0) + 12 }]}>
        <View style={st.timeRow}>
          <Text style={st.time}>{fmt(status.currentTime)} / {fmt(status.duration)}</Text>
          <Pressable onPress={() => setSyncMode(!syncMode)} style={[st.sync, syncMode && { backgroundColor: C.progress }]} hitSlop={6}
            accessibilityLabel="대본 싱크 맞추기">
            <Text style={[st.syncBtnT, syncMode && { color: C.dark }]}>{syncMode ? '취소' : auto === 'working' ? '맞추는 중…' : auto === 'auto' ? '자동 싱크' : offset ? `싱크 ${offset > 0 ? '+' : ''}${offset}s` : '싱크'}</Text>
          </Pressable>
        </View>
        <Pressable onLayout={(e) => setBarW(e.nativeEvent.layout.width || 1)} hitSlop={{ top: 12, bottom: 12 }} accessibilityLabel="재생 위치"
          onPress={(e) => player.seekTo((e.nativeEvent.locationX / barW) * dur)} style={st.track}>
          <View style={[st.fill, { width: `${pct * 100}%` }]} />
        </Pressable>
        <View style={st.ctrls}>
          <Pressable onPress={setSpeed} style={st.side} accessibilityLabel="재생 속도"><Text style={st.sideT}>{rate.toFixed(1)}x</Text></Pressable>
          <RoundBtn icon="play-back" label="5초 뒤로" size={48} bg="transparent" color="#fff"
            onPress={() => player.seekTo(Math.max(0, (status.currentTime ?? 0) - 5))} />
          <RoundBtn icon={status.playing ? 'pause' : 'play'} label={status.playing ? '일시정지' : '재생'} size={64} bg="#fff" color={C.dark}
            onPress={() => (status.playing ? player.pause() : player.play())} />
          <RoundBtn icon="play-forward" label="5초 앞으로" size={48} bg="transparent" color="#fff"
            onPress={() => player.seekTo((status.currentTime ?? 0) + 5)} />
          <Pressable onPress={() => setKo(!ko)} style={[st.side, ko && { backgroundColor: C.progress }]} accessibilityLabel="한국어 번역 보기"
            accessibilityState={{ checked: ko }}>
            <Text style={[st.sideT, ko && { color: C.dark }]}>한글</Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

const SentRow = memo(function SentRow({ sn, state, ko, onPress }: { sn: Sent; state: 'past' | 'cur' | 'next'; ko: boolean; onPress: (s: Sent) => void }) {
  if (state === 'cur') {
    return (
      <Pressable onPress={() => onPress(sn)} style={[st.curCard, shadow]}>
        <View style={st.spkRow}>
          {sn.speaker ? <View style={st.spkDot}><Text style={st.spkDotT}>{sn.speaker.slice(0, 1).toUpperCase()}</Text></View> : null}
          <Text style={st.spk}>{sn.speaker ? sn.speaker + ' · ' : ''}{fmt(sn.s)}</Text>
        </View>
        <Text style={st.curEn}>{sn.text}</Text>
        {ko && sn.ko ? <View style={st.koBox}><Text style={st.curKo}>{sn.ko}</Text></View> : null}
      </Pressable>
    );
  }
  return (
    <Pressable onPress={() => onPress(sn)} style={st.sent}>
      {sn.showSpk && <Text style={st.spkSmall}>{sn.speaker}</Text>}
      <Text style={[st.en, state === 'past' && { color: C.faint }]}>{sn.text}</Text>
      {ko && sn.ko ? <Text style={[st.ko, state === 'past' && { color: C.faint }]}>{sn.ko}</Text> : null}
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
        <View>
          <Text style={st.secH}>단어 <Text style={st.secN}>{vocab.length}</Text></Text>
          <View style={st.card}>
            {vocab.map((v, i) => (
              <View key={v.word} style={[st.vrow, i > 0 && st.vrowLine]}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={st.word}>{v.word} {v.pos ? <Text style={st.pos}>{v.pos}</Text> : null}</Text>
                  <Text style={st.mean}>{v.meaning_ko}</Text>
                  {v.example ? <Text style={st.ex}>{v.example}</Text> : null}
                </View>
                <SaveBtn on={saved.has(v.word)} onPress={() => save('word', v.word, v.meaning_ko, v.example)} />
              </View>))}
          </View>
          <Text style={[st.secH, { marginTop: 22 }]}>표현 <Text style={st.secN}>{exprs.length}</Text></Text>
        </View>
      ) : (
        <View style={st.card}>
          <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
            <Text style={[st.exprT, { flex: 1 }]}>{item.e!.expression}</Text>
            <SaveBtn on={saved.has(item.e!.expression)} onPress={() => save('expression', item.e!.expression, item.e!.meaning_ko, item.e!.examples?.[0])} />
          </View>
          <Text style={st.mean}>{item.e!.meaning_ko}</Text>
          {item.e!.nuance_ko ? <Text style={st.p}>{item.e!.nuance_ko}</Text> : null}
          {item.e!.quote ? (
            <Pressable style={st.quoteBox} disabled={!(item.e!.segment_id && segStart[item.e!.segment_id] != null)}
              onPress={() => onJump(segStart[item.e!.segment_id!])}>
              <Text style={st.quote}>“{item.e!.quote}”</Text>
              {item.e!.segment_id && segStart[item.e!.segment_id] != null &&
                <View style={st.jump}><Icon name="play" size={12} color={C.accent} /><Text style={st.jumpT}>{fmt(segStart[item.e!.segment_id!])}에서 듣기</Text></View>}
            </Pressable>) : null}
          {(item.e!.examples ?? []).map((x) => <Text key={x} style={st.ex}>• {x}</Text>)}
          {(item.e!.similar ?? []).length ? <Text style={st.simH}>비슷한 표현</Text> : null}
          {(item.e!.similar ?? []).map((x) => <Text key={x.expression} style={st.ex}><Text style={{ fontFamily: F.enB, color: C.ink }}>{x.expression}</Text> — {x.example}</Text>)}
        </View>
      )} />
  );
}

const SaveBtn = ({ on, onPress }: { on: boolean; onPress: () => void }) => (
  <Pressable onPress={onPress} hitSlop={8} accessibilityLabel={on ? '단어장에 저장됨' : '단어장에 저장'}
    style={[st.save, on && { backgroundColor: C.accent }]}>
    <Icon name={on ? 'star' : 'star-outline'} size={18} color={on ? '#fff' : C.accent} />
  </Pressable>);

const st = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28 },
  centerArt: { width: 84, height: 84, borderRadius: 42, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center', marginBottom: 18 },
  h: { fontFamily: F.title, fontSize: 22, color: C.ink, textAlign: 'center' },
  p: { color: C.ink2, lineHeight: 21, fontSize: 14, marginTop: 6 },
  top: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingTop: 6 },
  topShow: { color: C.ink3, fontSize: 12 },
  topTitle: { color: C.ink, fontFamily: F.enB, fontSize: 14.5 },
  seg: { flexDirection: 'row', marginHorizontal: 22, marginTop: 12, padding: 4, backgroundColor: C.line, borderRadius: R.pill },
  segB: { flex: 1, minHeight: 40, borderRadius: R.pill, alignItems: 'center', justifyContent: 'center' },
  segOn: { backgroundColor: C.sheet },
  segT: { color: C.ink3, fontSize: 14 },
  oneBox: { flexDirection: 'row', gap: 8, backgroundColor: C.accentSoft, borderRadius: 20, padding: 14, marginBottom: 14 },
  one: { flex: 1, color: C.ink2, fontSize: 13.5, lineHeight: 20 },
  sent: { paddingVertical: 9, paddingHorizontal: 4 },
  spkSmall: { color: C.ink3, fontSize: 12, marginTop: 8, marginBottom: 2 },
  en: { color: C.ink2, fontFamily: F.en, fontSize: 16.5, lineHeight: 25 },
  ko: { color: C.ink3, fontSize: 13.5, lineHeight: 20, marginTop: 3 },
  curCard: { backgroundColor: C.sheet, borderRadius: R.card, padding: 18, marginVertical: 8, gap: 10 },
  spkRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  spkDot: { width: 26, height: 26, borderRadius: 13, backgroundColor: C.peach, alignItems: 'center', justifyContent: 'center' },
  spkDotT: { fontSize: 12, fontWeight: '700', color: C.ink },
  spk: { color: C.ink3, fontSize: 12 },
  curEn: { color: C.ink, fontFamily: F.enB, fontSize: 21, lineHeight: 29 },
  koBox: { backgroundColor: C.bg, borderRadius: 18, paddingHorizontal: 14, paddingVertical: 11 },
  curKo: { color: C.ink2, fontSize: 14.5, lineHeight: 22 },
  syncHint: { flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: C.accentSoft, marginHorizontal: 14, marginBottom: 8, borderRadius: 18, padding: 10 },
  syncT: { color: C.accent, fontWeight: '700' },
  bar: { marginHorizontal: 12, marginBottom: 14, paddingHorizontal: 18, paddingTop: 14, paddingBottom: 14, borderRadius: 32, backgroundColor: C.dark, gap: 10 },
  timeRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', height: 30 },
  time: { color: '#C9C6DC', fontSize: 12, fontVariant: ['tabular-nums'] },
  sync: { minWidth: 76, height: 30, borderRadius: 15, backgroundColor: C.dark2, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 10 },
  syncBtnT: { color: '#fff', fontSize: 12, fontWeight: '700', fontVariant: ['tabular-nums'] },
  track: { height: 6, borderRadius: 3, backgroundColor: C.track, overflow: 'hidden' },
  fill: { height: 6, borderRadius: 3, backgroundColor: C.progress },
  ctrls: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', height: 66 },
  side: { width: 58, height: 44, borderRadius: 22, backgroundColor: C.dark2, alignItems: 'center', justifyContent: 'center' },
  sideT: { color: '#fff', fontFamily: F.enB, fontSize: 14 },
  secH: { fontFamily: F.title, fontSize: 19, color: C.ink, marginBottom: 10, marginLeft: 4 },
  secN: { color: C.accent },
  card: { backgroundColor: C.sheet, borderRadius: 24, padding: 16, marginBottom: 12 },
  vrow: { flexDirection: 'row', gap: 10, paddingVertical: 10 },
  vrowLine: { borderTopWidth: 1, borderColor: C.line },
  word: { fontFamily: F.enB, color: C.ink, fontSize: 16 },
  pos: { fontFamily: F.en, color: C.ink3, fontSize: 12.5 },
  exprT: { fontFamily: F.enX, color: C.ink, fontSize: 18, lineHeight: 24 },
  mean: { color: C.ink, marginTop: 4, fontSize: 14.5, lineHeight: 21 },
  ex: { color: C.ink2, fontFamily: F.en, fontSize: 13.5, marginTop: 5, lineHeight: 19 },
  quoteBox: { backgroundColor: C.bg, borderRadius: 18, padding: 12, marginTop: 10, gap: 6 },
  quote: { color: C.ink2, fontFamily: F.en, fontSize: 14, lineHeight: 20 },
  jump: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  jumpT: { color: C.accent, fontSize: 12.5, fontWeight: '700' },
  simH: { color: C.ink3, fontSize: 12.5, marginTop: 12 },
  save: { width: 38, height: 38, borderRadius: 19, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center' },
});
