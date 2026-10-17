import { Link } from 'expo-router';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import type { Episode } from '@/lib/types';
import { C, dateKo, fmt } from '@/lib/theme';

const BADGE: Record<string, string> = { ready: '준비됨', queued: '준비 중', processing: '준비 중', failed: '오류', no_transcript: '대본 없음' };

export default function EpisodeRow({ ep, showTitle }: { ep: Episode; showTitle?: boolean }) {
  return (
    <Link href={{ pathname: '/episode/[id]', params: { id: ep.id } }} asChild>
      <Pressable style={s.row}>
        {showTitle && ep.shows?.image_url ? <Image source={{ uri: ep.shows.image_url }} style={s.img} /> : null}
        <View style={{ flex: 1 }}>
          <Text style={s.meta}>{showTitle && ep.shows ? ep.shows.title + ' · ' : ''}{dateKo(ep.published_at)} · {fmt(ep.duration_sec)}
            {BADGE[ep.status] ? `  ·  ${BADGE[ep.status]}` : ''}</Text>
          <Text style={s.title} numberOfLines={2}>{ep.title}</Text>
          {ep.one_liner_ko ? <Text style={s.one} numberOfLines={2}>{ep.one_liner_ko}</Text> : null}
        </View>
      </Pressable>
    </Link>
  );
}
const s = StyleSheet.create({
  row: { flexDirection: 'row', gap: 12, padding: 14, backgroundColor: C.sheet, borderRadius: 14, marginBottom: 10, borderWidth: 1, borderColor: C.line },
  img: { width: 52, height: 52, borderRadius: 10 },
  meta: { color: C.ink3, fontSize: 12.5, marginBottom: 4 },
  title: { color: C.ink, fontSize: 15.5, fontWeight: '600', lineHeight: 21 },
  one: { color: C.ink2, fontSize: 13.5, marginTop: 4, lineHeight: 19 },
});
