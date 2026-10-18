// The episode that's playing, as a slim bar above the tabs: tap to open it, play/pause, close.
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Art, Icon, RoundBtn } from '@/components/ui';
import { useNowPlaying } from '@/lib/nowPlaying';
import { C, F } from '@/lib/theme';

export default function MiniPlayer() {
  const { ep, status, player, stop } = useNowPlaying();
  const router = useRouter();
  if (!ep) return null;
  const pct = status.duration ? Math.min(1, (status.currentTime ?? 0) / status.duration) : 0;
  return (
    <Pressable style={s.wrap} onPress={() => router.push({ pathname: '/episode/[id]', params: { id: ep.id } })}
      accessibilityRole="button" accessibilityLabel={`지금 재생 중: ${ep.title}`}>
      <Art uri={ep.image_url ?? ep.shows?.image_url} id={ep.show_id} size={40} radius={12} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={s.show} numberOfLines={1}>{ep.shows?.title}</Text>
        <Text style={s.title} numberOfLines={1}>{ep.title}</Text>
      </View>
      <RoundBtn icon={status.playing ? 'pause' : 'play'} label={status.playing ? '일시정지' : '재생'} size={40} bg="#fff" color={C.dark}
        onPress={() => (status.playing ? player.pause() : player.play())} />
      <Pressable onPress={stop} hitSlop={8} accessibilityLabel="재생 닫기" style={{ padding: 4 }}>
        <Icon name="close" size={20} color="#C9C6DC" />
      </Pressable>
      <View style={s.track}><View style={[s.fill, { width: `${pct * 100}%` }]} /></View>
    </Pressable>
  );
}

const s = StyleSheet.create({
  wrap: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: C.dark, borderRadius: 22, paddingLeft: 10, paddingRight: 10, paddingVertical: 9, marginBottom: 8, overflow: 'hidden' },
  show: { color: '#C9C6DC', fontSize: 11 },
  title: { color: '#fff', fontFamily: F.enB, fontSize: 13.5 },
  track: { position: 'absolute', left: 0, right: 0, bottom: 0, height: 3, backgroundColor: C.dark2 },
  fill: { height: 3, backgroundColor: C.progress },
});
