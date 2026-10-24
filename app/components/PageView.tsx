// The publisher's own page, inside the app (a small browser) — for shows whose transcript lives on a
// web page. The episode keeps playing underneath (the app-wide player), with controls at the bottom.
import { useState } from 'react';
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Icon, RoundBtn } from '@/components/ui';
import { useNowPlaying } from '@/lib/nowPlaying';
import type { Episode } from '@/lib/types';
import { C, F, R, fmt } from '@/lib/theme';

export default function PageView({ ep, url, onClose, onStudy, studyLabel }: { ep: Episode; url: string; onClose: () => void; onStudy?: () => void; studyLabel?: string }) {
  const insets = useSafeAreaInsets();
  const np = useNowPlaying();
  const mine = np.ep?.id === ep.id;
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const st = np.status;
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <View style={s.top}>
        <RoundBtn icon="chevron-back" label="닫기" onPress={onClose} />
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={s.topShow} numberOfLines={1}>{ep.shows?.title} · 방송사 페이지</Text>
          <Text style={s.topTitle} numberOfLines={1}>{ep.title}</Text>
        </View>
        <RoundBtn icon="open-outline" label="브라우저에서 열기" size={40} onPress={() => Linking.openURL(url).catch(() => {})} />
      </View>
      {onStudy ? (
        <Pressable style={s.up} onPress={onStudy} accessibilityRole="button">
          <Icon name="sparkles" size={16} color={C.accent} />
          <Text style={s.upT} numberOfLines={1}>{studyLabel ?? '학습 모드로 보기'} · 문장 따라가기 · 단어·표현</Text>
          <Icon name="chevron-forward" size={16} color={C.accent} />
        </Pressable>) : null}
      <View style={s.web}>
        {failed ? (
          <View style={s.center}><Text style={s.p}>페이지를 열지 못했어요.</Text>
            <Pressable onPress={() => Linking.openURL(url).catch(() => {})}><Text style={[s.p, { color: C.accent, marginTop: 8 }]}>브라우저에서 열기 ›</Text></Pressable></View>
        ) : (
          <WebView source={{ uri: url }} style={{ flex: 1, backgroundColor: '#fff' }}
            onLoadEnd={() => setLoading(false)} onError={() => { setFailed(true); setLoading(false); }}
            allowsInlineMediaPlayback={false} mediaPlaybackRequiresUserAction setSupportMultipleWindows={false} />
        )}
        {loading && !failed ? <View style={s.loading}><ActivityIndicator color={C.accent} /></View> : null}
      </View>
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
  top: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingTop: 6, paddingBottom: 8 },
  topShow: { color: C.ink3, fontSize: 12 },
  topTitle: { color: C.ink, fontFamily: F.enB, fontSize: 14.5 },
  up: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: C.accentSoft, borderRadius: R.pill, paddingHorizontal: 14, paddingVertical: 10, marginHorizontal: 14, marginBottom: 8 },
  upT: { flex: 1, color: C.ink, fontWeight: '700', fontSize: 13.5 },
  web: { flex: 1, marginHorizontal: 10, marginBottom: 8, borderRadius: 18, overflow: 'hidden', backgroundColor: '#fff' },
  loading: { position: 'absolute', top: 20, left: 0, right: 0, alignItems: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  p: { color: C.ink2, fontSize: 14, textAlign: 'center' },
  bar: { marginHorizontal: 12, paddingHorizontal: 18, paddingVertical: 8, borderRadius: 28, backgroundColor: C.dark, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  time: { color: '#C9C6DC', fontSize: 12, fontVariant: ['tabular-nums'] },
});
