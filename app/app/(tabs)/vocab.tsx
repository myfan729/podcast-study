import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Btn, Chip, Icon, PageTitle } from '@/components/ui';
import * as api from '@/lib/api';
import type { SavedItem } from '@/lib/types';
import { C, F, R, shadow } from '@/lib/theme';

const GRADES = [
  { l: '몰라요', g: 0, bg: C.warnBg, fg: C.warn },
  { l: '헷갈려요', g: 1, bg: C.sheet, fg: C.ink2 },
  { l: '알아요', g: 2, bg: C.accent, fg: '#fff' },
] as const;

export default function VocabScreen() {
  const [items, setItems] = useState<SavedItem[]>([]);
  const [mode, setMode] = useState<'list' | 'review'>('list');
  const [filter, setFilter] = useState<'all' | 'word' | 'expression'>('all');
  const [flip, setFlip] = useState(false);
  const [done, setDone] = useState(0);
  const load = useCallback(() => { api.myItems().then(setItems).catch(() => {}); }, []);
  useFocusEffect(load);
  const due = items.filter((x) => new Date(x.due_at).getTime() <= Date.now());
  const learned = items.filter((x) => x.reps >= 2).length;
  const shown = items.filter((x) => filter === 'all' || x.kind === filter);

  if (mode === 'review') {
    const it = due[0];
    const total = done + due.length;
    if (!it) return (
      <SafeAreaView edges={['top']} style={s.center}>
        <View style={s.doneArt}><Icon name="sparkles" size={34} color={C.accent} /></View>
        <Text style={s.doneH}>오늘 복습 끝!</Text>
        <Text style={s.doneP}>{done}개를 복습했어요. 내일 또 만나요.</Text>
        <Btn label="단어장으로" onPress={() => { setMode('list'); setDone(0); }} style={{ alignSelf: 'stretch', marginTop: 22 }} />
      </SafeAreaView>);
    const grade = async (g: 0 | 1 | 2) => { setFlip(false); setDone(done + 1); await api.review(it, g); load(); };
    return (
      <SafeAreaView edges={['top']} style={{ flex: 1 }}>
        <PageTitle right={<Pressable onPress={() => setMode('list')} hitSlop={8}><Text style={s.quit}>그만하기</Text></Pressable>}>복습</PageTitle>
        <View style={s.progress}><View style={[s.progressFill, { width: `${Math.round((100 * done) / Math.max(1, total))}%` }]} /></View>
        <View style={{ padding: 22, flex: 1 }}>
          <Pressable style={[s.card, shadow]} onPress={() => setFlip(true)} accessibilityLabel="뜻 보기">
            <Text style={s.cardMeta}>{done + 1} / {total} · {it.kind === 'word' ? '단어' : '표현'}</Text>
            <Text style={s.front}>{it.text}</Text>
            {flip ? <>
              {it.meaning_ko ? <Text style={s.back}>{it.meaning_ko}</Text> : null}
              {it.example ? <View style={s.exBox}><Text style={s.ex}>{it.example}</Text></View> : null}
            </> : <View style={s.tap}><Icon name="hand-left-outline" size={16} color={C.accent} /><Text style={s.tapT}>눌러서 뜻 보기</Text></View>}
          </Pressable>
          {flip && <View style={s.grades}>
            {GRADES.map((x) => (
              <Pressable key={x.l} style={[s.g, { backgroundColor: x.bg }]} onPress={() => grade(x.g)}>
                <Text style={[s.gT, { color: x.fg }]}>{x.l}</Text>
              </Pressable>))}
          </View>}
        </View>
      </SafeAreaView>
    );
  }
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <FlatList contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 24 }} data={shown} keyExtractor={(x) => x.id}
        ListHeaderComponent={<View>
          <View style={{ marginHorizontal: -16 }}><PageTitle>단어장</PageTitle></View>
          <View style={[s.hero, shadow]}>
            <Text style={s.heroMeta}>오늘 복습할 카드</Text>
            <Text style={s.heroN}>{due.length}<Text style={s.heroUnit}> 개</Text></Text>
            <Btn label={due.length ? '복습 시작' : '오늘은 다 했어요'} disabled={!due.length} onPress={() => { setDone(0); setMode('review'); }} style={{ marginTop: 14 }} />
          </View>
          {items.length > 0 && <View style={s.stat}>
            <Text style={s.statN}>{learned}</Text>
            <Text style={s.statT}>저장한 {items.length}개 중 두 번 넘게{'\n'}복습을 통과한 단어·표현</Text>
          </View>}
          <View style={s.filters}>
            <Chip label="전체" on={filter === 'all'} onPress={() => setFilter('all')} />
            <Chip label="단어" on={filter === 'word'} onPress={() => setFilter('word')} />
            <Chip label="표현" on={filter === 'expression'} onPress={() => setFilter('expression')} />
          </View>
        </View>}
        ListEmptyComponent={<Text style={s.none}>에피소드의 단어·표현에서 ☆를 누르면 여기 모여요.</Text>}
        renderItem={({ item }) => (
          <Pressable style={s.row} onLongPress={() => Alert.alert('삭제할까요?', item.text, [{ text: '취소' }, { text: '삭제', style: 'destructive', onPress: async () => { await api.deleteItem(item.id); load(); } }])}>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={s.word}>{item.text}</Text>
              {item.meaning_ko ? <Text style={s.mean} numberOfLines={2}>{item.meaning_ko}</Text> : null}
            </View>
            <View style={[s.kind, item.kind !== 'word' && { backgroundColor: C.peach }]}><Text style={s.kindT}>{item.kind === 'word' ? '단어' : '표현'}</Text></View>
          </Pressable>)} />
    </SafeAreaView>
  );
}
const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28 },
  doneArt: { width: 80, height: 80, borderRadius: 40, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center', marginBottom: 16 },
  doneH: { fontFamily: F.title, fontSize: 26, color: C.ink },
  doneP: { color: C.ink2, marginTop: 8 },
  quit: { color: C.ink3, fontSize: 14 },
  progress: { height: 6, borderRadius: 3, backgroundColor: C.line, marginHorizontal: 22 },
  progressFill: { height: 6, borderRadius: 3, backgroundColor: C.accent },
  card: { minHeight: 300, backgroundColor: C.sheet, borderRadius: 32, padding: 26, alignItems: 'center', justifyContent: 'center', gap: 12 },
  cardMeta: { color: C.ink3, fontSize: 12.5 },
  front: { fontFamily: F.enX, fontSize: 34, color: C.ink, textAlign: 'center' },
  back: { fontSize: 16, color: C.ink2, textAlign: 'center', lineHeight: 24 },
  exBox: { backgroundColor: C.bg, borderRadius: 18, padding: 14, alignSelf: 'stretch' },
  ex: { fontFamily: F.en, color: C.ink2, fontSize: 14, lineHeight: 21 },
  tap: { flexDirection: 'row', gap: 6, alignItems: 'center', marginTop: 6 },
  tapT: { color: C.accent, fontWeight: '700' },
  grades: { flexDirection: 'row', gap: 10, marginTop: 18 },
  g: { flex: 1, minHeight: 56, borderRadius: R.btn, alignItems: 'center', justifyContent: 'center' },
  gT: { fontWeight: '700', fontSize: 15 },
  hero: { backgroundColor: C.sheet, borderRadius: 32, padding: 22, marginHorizontal: 6 },
  heroMeta: { color: C.ink3, fontSize: 13 },
  heroN: { fontFamily: F.enX, fontSize: 44, color: C.ink, marginTop: 2 },
  heroUnit: { fontSize: 18, fontFamily: F.title, color: C.ink2 },
  stat: { flexDirection: 'row', alignItems: 'center', gap: 14, backgroundColor: C.mint, borderRadius: 24, padding: 16, marginTop: 12, marginHorizontal: 6 },
  statN: { fontFamily: F.enX, fontSize: 30, color: C.mintInk },
  statT: { color: C.mintInk, fontSize: 13, lineHeight: 19 },
  filters: { flexDirection: 'row', gap: 8, marginTop: 22, marginBottom: 12, marginHorizontal: 6 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: C.sheet, borderRadius: 20, padding: 16, marginBottom: 8 },
  word: { fontFamily: F.enB, color: C.ink, fontSize: 16 },
  mean: { color: C.ink2, marginTop: 4, fontSize: 13.5 },
  kind: { backgroundColor: C.lilac, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  kindT: { fontSize: 11.5, color: C.ink2, fontWeight: '700' },
  none: { color: C.ink3, textAlign: 'center', marginTop: 30, lineHeight: 20 },
});
