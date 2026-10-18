import { Link } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { Episode } from '@/lib/types';
import { C, F, dateKo, mins } from '@/lib/theme';
import { Art } from './ui';

// every episode can be listened to; the badge only says where its study material stands
const BADGE: Record<string, { t: string; bg: string; fg: string }> = {
  ready: { t: '학습자료 바로 열림', bg: C.mint, fg: C.mintInk },
  queued: { t: '학습자료 만드는 중', bg: C.accentSoft, fg: C.accent },
  processing: { t: '학습자료 만드는 중', bg: C.accentSoft, fg: C.accent },
  listen: { t: '듣기만 가능', bg: C.line, fg: C.ink3 },
};

export default function EpisodeRow({ ep, showTitle }: { ep: Episode; showTitle?: boolean }) {
  const b = !ep.has_transcript || ep.status === 'no_transcript' ? BADGE.listen : BADGE[ep.status];
  return (
    <Link href={{ pathname: '/episode/[id]', params: { id: ep.id } }} asChild>
      <Pressable style={s.row}>
        {showTitle ? <Art uri={ep.shows?.image_url} id={ep.show_id} size={56} radius={16} /> : null}
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={s.meta} numberOfLines={1}>{showTitle && ep.shows ? ep.shows.title + ' · ' : ''}{dateKo(ep.published_at)} · {mins(ep.duration_sec)}</Text>
          <Text style={s.title} numberOfLines={2}>{ep.title}</Text>
          {ep.one_liner_ko || ep.intro_ko ? <Text style={s.one} numberOfLines={2}>{ep.one_liner_ko || ep.intro_ko}</Text> : null}
          {b ? <View style={[s.badge, { backgroundColor: b.bg }]}><Text style={[s.badgeT, { color: b.fg }]}>{b.t}</Text></View> : null}
        </View>
      </Pressable>
    </Link>
  );
}
const s = StyleSheet.create({
  row: { flexDirection: 'row', gap: 14, padding: 14, backgroundColor: C.sheet, borderRadius: 24, marginBottom: 10 },
  meta: { color: C.ink3, fontSize: 12.5, marginBottom: 4 },
  title: { color: C.ink, fontSize: 15.5, fontFamily: F.enB, lineHeight: 21 },
  one: { color: C.ink3, fontSize: 12.5, marginTop: 4, lineHeight: 17 },
  badge: { alignSelf: 'flex-start', marginTop: 8, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  badgeT: { fontSize: 11.5, fontWeight: '700' },
});
