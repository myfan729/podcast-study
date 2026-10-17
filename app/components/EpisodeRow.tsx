import { Link } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { Episode } from '@/lib/types';
import { C, F, dateKo, mins } from '@/lib/theme';
import { Art } from './ui';

const BADGE: Record<string, { t: string; bg: string; fg: string }> = {
  ready: { t: '바로 듣기', bg: C.mint, fg: C.mintInk },
  queued: { t: '준비 중', bg: C.accentSoft, fg: C.accent },
  processing: { t: '준비 중', bg: C.accentSoft, fg: C.accent },
  failed: { t: '오류', bg: C.warnBg, fg: C.warn },
  no_transcript: { t: '대본 없음', bg: C.line, fg: C.ink3 },
};

export default function EpisodeRow({ ep, showTitle }: { ep: Episode; showTitle?: boolean }) {
  const b = BADGE[ep.status];
  return (
    <Link href={{ pathname: '/episode/[id]', params: { id: ep.id } }} asChild>
      <Pressable style={s.row}>
        {showTitle ? <Art uri={ep.shows?.image_url} id={ep.show_id} size={56} radius={16} /> : null}
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={s.meta} numberOfLines={1}>{showTitle && ep.shows ? ep.shows.title + ' · ' : ''}{dateKo(ep.published_at)} · {mins(ep.duration_sec)}</Text>
          <Text style={s.title} numberOfLines={2}>{ep.title}</Text>
          {ep.one_liner_ko ? <Text style={s.one} numberOfLines={2}>{ep.one_liner_ko}</Text> : null}
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
  one: { color: C.ink2, fontSize: 13.5, marginTop: 5, lineHeight: 19 },
  badge: { alignSelf: 'flex-start', marginTop: 8, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  badgeT: { fontSize: 11.5, fontWeight: '700' },
});
