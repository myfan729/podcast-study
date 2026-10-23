import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { memo, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Linking, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Btn, Icon, RoundBtn } from '@/components/ui';
import AutoSync, { type SyncResult } from '@/components/AutoSync';
import Marquee from '@/components/Marquee';
import SeekBar from '@/components/SeekBar';
import ListenView from '@/components/ListenView';
import { useNowPlaying } from '@/lib/nowPlaying';
import * as api from '@/lib/api';
import { addAnchor, inAd, toAudio, toContent, type Anchor } from '@/lib/timeline';
import type { Episode, Expression, Pack, RequestResult } from '@/lib/types';
import { C, F, R, fmt, shadow } from '@/lib/theme';

type Mark = { from: number; to: number; kind: 'expr' | 'word'; idx: number };
type Sent = { a: number; b: number; s: number; text: string; ko?: string; speaker?: string; showSpk: boolean; marks: Mark[] };
type Peek = { kind: 'expr' | 'word'; idx: number } | null;
const RATES = [0.8, 1, 1.2];

export default function EpisodeScreen() {
  const { id, study } = useLocalSearchParams<{ id: string; study?: string }>();
  // opening an episode just plays it; the study mode is one tap away ("학습자료 만들기")
  const [mode, setMode] = useState<'listen' | 'study'>('listen');
  const [ep, setEp] = useState<Episode | null>(null);
  const [unlocked, setUnlocked] = useState<boolean | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    setMode('listen'); setEp(null); setUnlocked(null);
    Promise.all([api.episode(id), api.isUnlocked(id)]).then(([e, u]) => { setEp(e); setUnlocked(u); if (u && study === '1') setMode('study'); })
      .catch((x) => setErr(x.message));
  }, [id]);
  if (err) return <Center text={'문제가 생겼어요: ' + err} />;
  if (!ep || unlocked === null) return <Center spin />;
  if (mode === 'listen') return <ListenView ep={ep} unlocked={unlocked} onStudy={() => setMode('study')} />;
  return <StudyFlow id={id} />;
}

function StudyFlow({ id }: { id: string }) {
  const router = useRouter();
  const [ep, setEp] = useState<Episode | null>(null);
  const [req, setReq] = useState<RequestResult | null>(null);
  const [pack, setPack] = useState<Pack | null>(null);
  const [err, setErr] = useState('');
  const packLoaded = useRef(false);

  // 1) unlock + queue, 2) poll until ready, 3) load the pack
  useEffect(() => {
    let alive = true, timer: ReturnType<typeof setTimeout> | undefined;
    const started = Date.now();
    const tick = async () => {
      try {
        const e = await api.episode(id);
        if (!alive) return;
        setEp(e);
        if (e.status === 'ready' && e.pack_path) {
          if (!packLoaded.current) { packLoaded.current = true; setPack(await api.pack(e.pack_path)); }
          // the sync data (ad-aware timing) is built a few minutes after the pack: keep checking until it exists
          if (!e.sync_path && Date.now() - started < 20 * 60_000) timer = setTimeout(tick, 15000);
          return;
        }
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
        title={req.reason === 'quota' ? '이번 주 무료 학습자료를 다 썼어요' : '대본이 아직 안 올라왔어요'}
        text={req.reason === 'quota' ? '무료는 일주일에 2편까지예요. 프로는 무제한이에요. 듣기는 계속 무료예요.' : '방송사가 대본을 올리면 목록에 다시 나타나요. 조금 뒤에 확인해 주세요.'}>
        {req.reason === 'quota' && <Btn label="프로 알아보기" onPress={() => router.push('/pro')} style={{ alignSelf: 'stretch', marginTop: 20 }} />}
      </Center>
    );
  }
  if (!pack) {
    const failed = ep?.status === 'failed' || ep?.status === 'no_transcript';
    if (ep?.error?.includes('no transcript on the page yet')) {
      return <Center icon="time-outline" title="대본이 아직 안 올라왔어요"
        text={'이 방송사는 대본을 방송 후 몇 시간~하루 뒤에 올려요.\n올라오면 자동으로 준비해 둘게요. 나중에 다시 열어 주세요.'} />;
    }
    return failed
      ? <Center icon="alert-circle-outline" title="준비하지 못했어요" text="이 에피소드는 대본을 만들 수 없었어요. 다른 에피소드를 골라 주세요." />
      : <Center spin title="학습자료를 만들고 있어요" text={'대본·번역·표현을 만드는 중이에요.\n보통 1~3분 걸려요.\n이 화면을 나가도 계속 만들어져요.'} />;
  }
  // remount when the sync data arrives, so the player switches to the aligned copy (from the same position)
  return <Player key={ep!.sync_path ? 'synced' : 'plain'} pack={pack} ep={ep!} />;
}

function Center({ text, title, spin, icon, children }: { text?: string; title?: string; spin?: boolean; icon?: 'lock-closed' | 'document-text-outline' | 'alert-circle-outline' | 'time-outline'; children?: ReactNode }) {
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
  // with auto-sync the player waits for the downloaded copy (playing the stream first only confuses: other ads)
  const audioUrl = api.secureAudio(pack.audio_url);
  const willSync = !!ep.sync_path && Platform.OS !== 'web';
  const player = useAudioPlayer(willSync ? null : audioUrl, { updateInterval: 250 });
  const status = useAudioPlayerStatus(player);
  const [tab, setTab] = useState<'script' | 'words'>('script');
  const [ko, setKo] = useState(true);
  const [rate, setRate] = useState(1);
  const [syncMode, setSyncMode] = useState(false);
  const [anchors, setAnchors] = useState<Anchor[]>([]);
  const [follow, setFollow] = useState(true);
  const [peek, setPeek] = useState<Peek>(null);
  const [syncRef, setSyncRef] = useState<unknown>(null);
  const [auto, setAuto] = useState<'off' | 'working' | 'auto' | 'failed'>(willSync ? 'working' : 'off');
  const [bgSync, setBgSync] = useState(willSync);                 // the WebView keeps matching after playback starts
  const [resumeAt, setResumeAt] = useState<number | null>(willSync ? null : 0);
  const started = useRef(false);                                  // playing the aligned copy already (partial result)
  useEffect(() => { if (willSync) api.lastPosition(ep.id).catch(() => 0).then((p) => setResumeAt(p > 20 ? p : 0)); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const [autoMsg, setAutoMsg] = useState('');
  useEffect(() => { AsyncStorage.getItem('pref:follow').then((v) => { if (v === '0') setFollow(false); }).catch(() => {}); }, []);
  const toggleFollow = () => { const v = !follow; setFollow(v); AsyncStorage.setItem('pref:follow', v ? '1' : '0').catch(() => {}); };
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
    const out: Sent[] = pairs.map(([a, b]) => {
      const sp = spkOf[a]; const showSpk = !!sp && sp !== last; last = sp;
      return { a, b, s: cues[a].s, text: cues.slice(a, b + 1).map((c) => c.t).join(' '), ko: tr[`${a}-${b}`], speaker: sp, showSpk, marks: [] };
    });
    const free = (sn: Sent, f: number, t: number) => sn.marks.every((m) => t <= m.from || f >= m.to);
    // expressions: their quote inside their own segment (as on the website)
    (pack.study.expressions ?? []).forEach((ex, idx) => {
      const q = (ex.quote || ex.expression || '').toLowerCase().trim(); if (!q) return;
      const seg = pack.transcript.segments.find((g) => g.id === ex.segment_id);
      const cand = out.filter((sn) => !seg || (sn.b >= seg.cue_from && sn.a <= seg.cue_to));
      for (const sn of cand) {
        const at = sn.text.toLowerCase().indexOf(q);
        if (at >= 0 && free(sn, at, at + q.length)) { sn.marks.push({ from: at, to: at + q.length, kind: 'expr', idx }); return; }
      }
    });
    // words: first time each one is said
    (pack.study.vocab ?? []).forEach((v, idx) => {
      const w = (v.word || '').trim(); if (!w) return;
      const re = new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
      for (const sn of out) {
        const m = re.exec(sn.text);
        if (m && free(sn, m.index, m.index + m[0].length)) { sn.marks.push({ from: m.index, to: m.index + m[0].length, kind: 'word', idx }); return; }
      }
    });
    out.forEach((sn) => sn.marks.sort((x, y) => x.from - y.from));
    return out;
  }, [pack]);

  const np = useNowPlaying();
  useEffect(() => {
    api.markOpened(ep.id).catch(() => {});                         // the home screen stops announcing it
    np.stop();                                                      // only one thing plays: the study copy
    AsyncStorage.getItem(key).then((v) => { if (v) setAnchors(JSON.parse(v)); }).catch(() => {});
    player.setActiveForLockScreen?.(true, { title: pack.title, artist: pack.show.name, artworkUrl: pack.show.image });
    if (!willSync) api.lastPosition(ep.id).then((p) => { if (p > 20) player.seekTo(p); }).catch(() => {});
    return () => { api.saveProgress(ep.id, player.currentTime ?? 0).catch(() => {}); };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // the server's correction of the publisher's cue times (cue_fix in the sync data)
  const fix = useMemo(() => {
    const pts = ((syncRef as { cue_fix?: [number, number][] } | null)?.cue_fix ?? []).slice().sort((p, q) => p[0] - q[0]);
    return (t: number) => {
      if (!pts.length) return t;
      if (pts.length === 1 || t <= pts[0][0]) return t + pts[0][1];
      for (let i = 1; i < pts.length; i++) {
        const [c0, d0] = pts[i - 1], [c1, d1] = pts[i];
        if (t <= c1) return t + d0 + (d1 - d0) * (t - c0) / Math.max(1e-6, c1 - c0);
      }
      return t + pts[pts.length - 1][1];
    };
  }, [syncRef]);
  const c = toContent(status.currentTime ?? 0, anchors);
  const cur = useMemo(() => { let i = 0; for (let k = 0; k < sents.length; k++) { if (fix(sents[k].s) <= c + 0.15) i = k; else break; } return i; }, [c, sents, fix]);
  // Keep the current card's top edge just under the tabs. Cards above it change height when the
  // highlight moves (the old card shrinks), so we scroll to the cell's *measured* position and
  // re-align whenever that position changes after layout.
  const cellY = useRef<Record<number, number>>({});
  const curRef = useRef(0); curRef.current = cur;
  const pinned = useRef(-1);                                          // index whose card we hold at the top (-1: none)
  const alignCur = useCallback((animated: boolean) => {
    const y = cellY.current[curRef.current];
    if (y == null) listRef.current?.scrollToIndex({ index: curRef.current, viewPosition: 0, viewOffset: 10, animated });
    else listRef.current?.scrollToOffset({ offset: Math.max(0, y - 10), animated });
  }, []);
  const Cell = useMemo(() => function Cell({ index, onLayout, ...rest }: any) {
    return <View {...rest} onLayout={(e) => {
      onLayout?.(e);
      const y = e.nativeEvent.layout.y, old = cellY.current[index];
      cellY.current[index] = y;
      if (index === pinned.current && index === curRef.current && old !== y) alignCur(false);
    }} />;
  }, [alignCur]);
  useEffect(() => {
    if (!follow || tab !== 'script' || !status.playing || Date.now() - userScroll.current < 4000) return;
    pinned.current = cur; alignCur(true);
  }, [cur, tab, status.playing, follow, alignCur]);

  const onSentence = useCallback((sn: Sent) => {
    if (syncMode) {
      const next = addAnchor(anchors, fix(sn.s), Math.max(0, (player.currentTime ?? 0) - 0.4));
      setAnchors(next); AsyncStorage.setItem(key, JSON.stringify(next)).catch(() => {}); setSyncMode(false);
      return;
    }
    if (auto === 'working') return;                                 // not playable until the sync is done
    player.seekTo(toAudio(fix(sn.s), anchors)); if (!status.playing) player.play();
    const i = sents.indexOf(sn);
    if (i >= 0) { userScroll.current = 0; pinned.current = i; curRef.current = i; alignCur(true); }
  }, [syncMode, anchors, player, status.playing, key, sents, auto, fix, alignCur]);  // eslint-disable-line react-hooks/exhaustive-deps

  // automatic ad-aware sync (needs the server's reference fingerprints for this episode)
  useEffect(() => {
    if (!ep.sync_path || Platform.OS === 'web') return;              // the web build has no WebView / file system
    setAuto('working');
    api.syncData(ep.sync_path).then(setSyncRef).catch(() => { setAuto('failed'); player.replace(audioUrl); });
  }, [ep.sync_path]);
  // start playing the downloaded copy as soon as the stretch up to the resume point is aligned
  const startAligned = useCallback(async (r: SyncResult, use: Anchor[]) => {
    started.current = true;
    player.replace({ uri: r.fileUri });                            // play exactly the copy that is being aligned
    player.setActiveForLockScreen?.(true, { title: pack.title, artist: pack.show.name, artworkUrl: pack.show.image });
    setAnchors(use); setAuto('auto');
    const last = resumeAt ?? 0;
    if (last > 20) { await new Promise((res) => setTimeout(res, 600)); player.seekTo(toAudio(toContent(last, use), use)); }
  }, [player, pack, resumeAt]);
  const onAutoPartial = useCallback((r: SyncResult) => { if (!started.current) startAligned(r, r.anchors); }, [startAligned]);
  const onAutoDone = useCallback(async (r: SyncResult | null, error?: string) => {
    const ok = !!r?.ok;
    setBgSync(false);
    api.reportSync(ep.id, ok, r?.anchors ?? null, r?.report ?? null, error).catch(() => {});
    if (ok) { setAnchors(r!.anchors); AsyncStorage.setItem(key, JSON.stringify(r!.anchors)).catch(() => {}); }
    if (started.current) return;                                   // already playing; the later anchors just refine the timing
    if (ok) { startAligned(r!, r!.anchors); return; }
    player.replace(r?.fileUri ? { uri: r.fileUri } : audioUrl);
    player.setActiveForLockScreen?.(true, { title: pack.title, artist: pack.show.name, artworkUrl: pack.show.image });
    setAuto('failed');
    const last = resumeAt ?? 0;
    if (last > 20) { await new Promise((res) => setTimeout(res, 600)); player.seekTo(toAudio(toContent(last, anchors), anchors)); }
  }, [anchors, player, key, pack, ep.id, startAligned, resumeAt, audioUrl]);

  const setSpeed = () => { const r = RATES[(RATES.indexOf(rate) + 1) % RATES.length]; setRate(r); player.setPlaybackRate(r); };
  const offset = anchors.length ? Math.round(anchors[anchors.length - 1].a - anchors[anchors.length - 1].c) : 0;

  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [dragSec, setDragSec] = useState<number | null>(null);    // time under the finger while dragging the bar
  const [rootH, setRootH] = useState(0);
  const [dockTop, setDockTop] = useState(0);                      // top of the hints + player bar block
  const dur = status.duration || pack.duration_sec || 1;
  const pct = Math.min(1, (status.currentTime ?? 0) / dur);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }} onLayout={(e) => setRootH(e.nativeEvent.layout.height)}>
      {syncRef && bgSync && resumeAt !== null && audioUrl ? (
        <AutoSync episodeId={ep.id} audioUrl={audioUrl} syncRef={syncRef} readyAt={resumeAt} onStatus={setAutoMsg}
          onPartial={onAutoPartial} onDone={onAutoDone} />) : null}
      <View style={st.top}>
        <RoundBtn icon="chevron-back" label="뒤로" onPress={() => router.back()} />
        <View style={{ flex: 1, minWidth: 0, alignItems: 'center' }}>
          <Text style={st.topShow} numberOfLines={1}>{pack.show.name}</Text>
          <Marquee text={pack.title} style={st.topTitle} />
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
        <View style={st.listBox}>
        <FlatList ref={listRef} data={sents} keyExtractor={(x) => String(x.a)} contentContainerStyle={{ padding: 18, paddingBottom: 40 }}
          style={{ flex: 1 }} removeClippedSubviews={false}
          ListHeaderComponent={pack.study.one_liner_ko ? <View style={st.oneBox}><Icon name="bulb-outline" size={16} color={C.accent} /><Text style={st.one}>{pack.study.one_liner_ko}</Text></View> : undefined}
          ListFooterComponent={<Credit pack={pack} ep={ep} />}
          CellRendererComponent={Cell}
          onScrollBeginDrag={() => { userScroll.current = Date.now(); pinned.current = -1; }}
          onScrollToIndexFailed={(info) => {
            listRef.current?.scrollToOffset({ offset: Math.max(0, info.averageItemLength * info.index - 40), animated: false });
            setTimeout(() => alignCur(false), 150);
          }}
          windowSize={31}
          renderItem={({ item, index }) => <SentRow sn={item} state={index === cur ? 'cur' : index < cur ? 'past' : 'next'} ko={ko} onPress={onSentence} onMark={setPeek} />} />
        </View>
      ) : (
        <Words pack={pack} episodeId={ep.id} onJump={(sec) => player.seekTo(toAudio(fix(sec), anchors))} />
      )}
      <View onLayout={(e) => setDockTop(e.nativeEvent.layout.y)}>
      {auto === 'working' && <View style={st.syncHint}><ActivityIndicator size="small" color={C.accent} /><Text style={st.syncT}>{autoMsg || '자동 싱크 준비 중…'} 끝나면 재생할 수 있어요</Text></View>}
      {auto === 'off' && !ep.sync_path && Platform.OS !== 'web' && !syncMode && !anchors.length && <View style={st.syncHint}><ActivityIndicator size="small" color={C.accent} /><Text style={st.syncT}>싱크 데이터 준비 중 · 그동안은 문장이 조금 어긋날 수 있어요</Text></View>}
      {anchors.length > 0 && !syncMode && inAd(status.currentTime ?? 0, anchors) && <View style={st.syncHint}><Icon name="megaphone-outline" size={16} color={C.accent} /><Text style={st.syncT}>광고 중 · 끝나면 다시 따라가요</Text></View>}
      {auto === 'failed' && !syncMode && !anchors.length && <View style={st.syncHint}><Icon name="information-circle-outline" size={16} color={C.accent} /><Text style={st.syncT}>자동 싱크 실패 · 싱크를 누르고 들리는 문장을 눌러 주세요</Text></View>}
      {syncMode && <View style={st.syncHint}><Icon name="hand-left-outline" size={16} color={C.accent} /><Text style={st.syncT}>지금 들리는 문장을 눌러 주세요</Text></View>}
      <View style={[st.bar, { marginBottom: Math.max(insets.bottom, 0) + 12 }]}>
        <View style={st.timeRow}>
          <Text style={st.time}>{fmt(dragSec ?? status.currentTime)} / {fmt(status.duration)}</Text>
          <Pressable onPress={toggleFollow} style={[st.sync, { marginLeft: 'auto', marginRight: 8, flexDirection: 'row', gap: 4 }, follow && { backgroundColor: C.progress }]} hitSlop={6}
            accessibilityRole="switch" accessibilityState={{ checked: follow }} accessibilityLabel="문장 자동 따라가기">
            <Icon name={follow ? 'checkmark' : 'close'} size={13} color={follow ? C.dark : '#fff'} />
            <Text style={[st.syncBtnT, follow && { color: C.dark }]}>따라가기</Text>
          </Pressable>
          <Pressable onPress={() => setSyncMode(!syncMode)} style={[st.sync, syncMode && { backgroundColor: C.progress }]} hitSlop={6}
            accessibilityLabel="대본 싱크 맞추기">
            <Text style={[st.syncBtnT, syncMode && { color: C.dark }]}>{syncMode ? '취소' : auto === 'working' ? '맞추는 중…' : auto === 'auto' ? '자동 싱크' : offset ? `싱크 ${offset > 0 ? '+' : ''}${offset}s` : '싱크'}</Text>
          </Pressable>
        </View>
        <SeekBar position={status.currentTime ?? 0} duration={dur} onDrag={setDragSec} onSeek={(sec) => player.seekTo(sec)} />
        <View style={st.ctrls}>
          <Pressable onPress={setSpeed} style={st.side} accessibilityLabel="재생 속도"><Text style={st.sideT}>{rate.toFixed(1)}x</Text></Pressable>
          <RoundBtn icon="play-back" label="5초 뒤로" size={48} bg="transparent" color="#fff"
            onPress={() => player.seekTo(Math.max(0, (status.currentTime ?? 0) - 5))} />
          {auto === 'working'
            ? <View style={st.wait}><ActivityIndicator color={C.dark} /></View>
            : <RoundBtn icon={status.playing ? 'pause' : 'play'} label={status.playing ? '일시정지' : '재생'} size={64} bg="#fff" color={C.dark}
                onPress={() => (status.playing ? player.pause() : player.play())} />}
          <RoundBtn icon="play-forward" label="5초 앞으로" size={48} bg="transparent" color="#fff"
            onPress={() => player.seekTo((status.currentTime ?? 0) + 5)} />
          <Pressable onPress={() => setKo(!ko)} style={[st.side, ko && { backgroundColor: C.progress }]} accessibilityLabel="한국어 번역 보기"
            accessibilityState={{ checked: ko }}>
            <Text style={[st.sideT, ko && { color: C.dark }]}>한글</Text>
          </Pressable>
        </View>
      </View>
      </View>
      {/* drawn last, so it sits above the list and right on top of the hints + player bar, never under them */}
      {peek && <PeekCard pack={pack} peek={peek} episodeId={ep.id} onClose={() => setPeek(null)}
        bottom={rootH && dockTop ? rootH - dockTop + 8 : 220} />}
    </SafeAreaView>
  );
}

function Marked({ sn, style, onMark }: { sn: Sent; style: object; onMark: (p: Peek) => void }) {
  if (!sn.marks.length) return <Text style={style}>{sn.text}</Text>;
  const parts: React.ReactNode[] = []; let at = 0;
  sn.marks.forEach((m, k) => {
    if (m.from > at) parts.push(sn.text.slice(at, m.from));
    parts.push(<Text key={k} style={m.kind === 'expr' ? st.hlExpr : st.hlWord} onPress={() => onMark({ kind: m.kind, idx: m.idx })}>{sn.text.slice(m.from, m.to)}</Text>);
    at = m.to;
  });
  if (at < sn.text.length) parts.push(sn.text.slice(at));
  return <Text style={style}>{parts}</Text>;
}

const SentRow = memo(function SentRow({ sn, state, ko, onPress, onMark }: { sn: Sent; state: 'past' | 'cur' | 'next'; ko: boolean; onPress: (s: Sent) => void; onMark: (p: Peek) => void }) {
  return (
    // the current sentence keeps the same font and size as the rest (only a highlight behind it),
    // so moving the highlight never changes row heights
    <Pressable onPress={() => onPress(sn)} style={[st.sent, state === 'cur' && st.sentCur]}>
      {sn.showSpk && <Text style={st.spkSmall}>{sn.speaker}</Text>}
      <Marked sn={sn} style={[st.en, state === 'past' && { color: C.faint }, state === 'cur' && { color: C.ink }]} onMark={onMark} />
      {ko && sn.ko ? <Text style={[st.ko, state === 'past' && { color: C.faint }, state === 'cur' && { color: C.ink2 }]}>{sn.ko}</Text> : null}
    </Pressable>
  );
});

/** Whose work this is, and the way to the original — shown under every transcript. */
function Credit({ pack, ep }: { pack: Pack; ep: Episode }) {
  const url = ep.episode_url || null;
  return (
    <View style={st.credit}>
      <Text style={st.creditT}>대본·오디오의 저작권은 {pack.show.name}{pack.show.publisher ? ` (${pack.show.publisher})` : ''}에 있어요. 오디오는 원본 서버에서 그대로 재생돼요.</Text>
      {url ? <Pressable onPress={() => Linking.openURL(url)} hitSlop={8}><Text style={st.creditL}>원본 에피소드 페이지 보기 ›</Text></Pressable> : null}
    </View>
  );
}

function PeekCard({ pack, peek, episodeId, onClose, bottom }: { pack: Pack; peek: NonNullable<Peek>; episodeId: string; onClose: () => void; bottom: number }) {
  const [saved, setSaved] = useState(false);
  const ex = peek.kind === 'expr' ? pack.study.expressions?.[peek.idx] : undefined;
  const v = peek.kind === 'word' ? pack.study.vocab?.[peek.idx] : undefined;
  const text = ex?.expression ?? v?.word ?? '';
  const meaning = ex?.meaning_ko ?? v?.meaning_ko ?? '';
  const example = ex?.examples?.[0] ?? v?.example;
  const save = async () => {
    setSaved(true);
    try { await api.saveItem({ kind: ex ? 'expression' : 'word', text, meaning_ko: meaning, example, episode_id: episodeId }); } catch { /* retried on next tap */ }
  };
  return (
    <View style={[st.peek, shadow, { bottom }]}>
      <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10 }}>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={st.peekKind}>{ex ? '표현' : '단어'}</Text>
          <Text style={st.exprT}>{text}</Text>
          {v?.ipa ? <Text style={st.ipa}>{v.ipa}</Text> : null}
        </View>
        <SaveBtn on={saved} onPress={save} />
        <RoundBtn icon="close" label="닫기" size={38} bg={C.bg} onPress={onClose} />
      </View>
      <Text style={st.mean}>{meaning}</Text>
      {ex?.nuance_ko ? <Text style={st.p} numberOfLines={3}>{ex.nuance_ko}</Text> : null}
      {example ? <Text style={st.ex} numberOfLines={2}>{example}</Text> : null}
    </View>
  );
}

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
                  {v.ipa ? <Text style={st.ipa}>{v.ipa}</Text> : null}
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
  sent: { paddingVertical: 9, paddingHorizontal: 10, marginHorizontal: -6, borderRadius: 14 },
  sentCur: { backgroundColor: C.accentSoft, borderLeftWidth: 4, borderLeftColor: C.accent, paddingLeft: 6 },
  spkSmall: { color: C.ink3, fontSize: 12, marginTop: 8, marginBottom: 2 },
  en: { color: C.ink2, fontFamily: F.en, fontSize: 15, lineHeight: 23 },
  ko: { color: C.ink3, fontSize: 12.5, lineHeight: 18, marginTop: 3 },
  curCard: { backgroundColor: C.sheet, borderRadius: R.card, padding: 18, marginVertical: 8, gap: 10 },
  spkRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  spkDot: { width: 26, height: 26, borderRadius: 13, backgroundColor: C.peach, alignItems: 'center', justifyContent: 'center' },
  spkDotT: { fontSize: 12, fontWeight: '700', color: C.ink },
  spk: { color: C.ink3, fontSize: 12 },
  curEn: { color: C.ink, fontFamily: F.enB, fontSize: 18, lineHeight: 26 },
  koBox: { backgroundColor: C.bg, borderRadius: 18, paddingHorizontal: 14, paddingVertical: 11 },
  curKo: { color: C.ink2, fontSize: 13.5, lineHeight: 20 },
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
  ipa: { color: C.ink3, fontSize: 13, marginTop: 1 },        // system font: it has the IPA glyphs Nunito lacks
  pos: { fontFamily: F.en, color: C.ink3, fontSize: 12.5 },
  exprT: { fontFamily: F.enX, color: C.ink, fontSize: 18, lineHeight: 24 },
  mean: { color: C.ink, marginTop: 4, fontSize: 14.5, lineHeight: 21 },
  ex: { color: C.ink2, fontFamily: F.en, fontSize: 13.5, marginTop: 5, lineHeight: 19 },
  quoteBox: { backgroundColor: C.bg, borderRadius: 18, padding: 12, marginTop: 10, gap: 6 },
  quote: { color: C.ink2, fontFamily: F.en, fontSize: 14, lineHeight: 20 },
  jump: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  jumpT: { color: C.accent, fontSize: 12.5, fontWeight: '700' },
  simH: { color: C.ink3, fontSize: 12.5, marginTop: 12 },
  hlExpr: { backgroundColor: '#FFE9A8', color: C.ink },
  hlWord: { textDecorationLine: 'underline', textDecorationColor: C.accent, color: C.accent },
  wait: { width: 64, height: 64, borderRadius: 32, backgroundColor: '#C9C6DC', alignItems: 'center', justifyContent: 'center' },
  peek: { position: 'absolute', left: 14, right: 14, bottom: 190, backgroundColor: C.sheet, borderRadius: 24, padding: 16, gap: 4 },
  listBox: { flex: 1, overflow: 'hidden', marginTop: 6 },          // the current-sentence card (with shadow) must not draw over the tabs
  credit: { marginTop: 24, padding: 14, borderRadius: 16, backgroundColor: C.sheet, gap: 6 },
  creditT: { color: C.ink3, fontSize: 11.5, lineHeight: 16 },
  creditL: { color: C.accent, fontSize: 12, fontWeight: '700' },
  peekKind: { color: C.accent, fontSize: 12, fontWeight: '700' },
  save: { width: 38, height: 38, borderRadius: 19, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center' },
});
