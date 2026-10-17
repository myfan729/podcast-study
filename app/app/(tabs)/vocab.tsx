import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import * as api from '@/lib/api';
import type { SavedItem } from '@/lib/types';
import { C } from '@/lib/theme';

export default function VocabScreen() {
  const [items, setItems] = useState<SavedItem[]>([]);
  const [mode, setMode] = useState<'list' | 'review'>('list');
  const [flip, setFlip] = useState(false);
  const load = useCallback(() => { api.myItems().then(setItems).catch(() => {}); }, []);
  useFocusEffect(load);
  const due = items.filter((x) => new Date(x.due_at).getTime() <= Date.now());

  if (mode === 'review') {
    const it = due[0];
    if (!it) return (
      <View style={s.center}><Text style={s.h}>오늘 복습 끝! 🎉</Text>
        <Pressable style={s.btn} onPress={() => setMode('list')}><Text style={s.btnT}>목록으로</Text></Pressable></View>);
    const grade = async (g: 0 | 1 | 2 | 3) => { setFlip(false); await api.review(it, g); load(); };
    return (
      <View style={s.center}>
        <Text style={s.count}>남은 카드 {due.length}</Text>
        <Pressable style={s.card} onPress={() => setFlip(true)}>
          <Text style={s.front}>{it.text}</Text>
          {flip ? <><Text style={s.back}>{it.meaning_ko}</Text>{it.example ? <Text style={s.ex}>{it.example}</Text> : null}</>
            : <Text style={s.tap}>눌러서 뜻 보기</Text>}
        </Pressable>
        {flip && <View style={s.grades}>
          {(['다시', '어려움', '알맞음', '쉬움'] as const).map((l, g) => (
            <Pressable key={l} style={[s.g, g === 0 && { borderColor: C.warn }]} onPress={() => grade(g as 0 | 1 | 2 | 3)}><Text style={s.gT}>{l}</Text></Pressable>))}
        </View>}
      </View>
    );
  }
  return (
    <FlatList contentContainerStyle={{ padding: 14 }} data={items} keyExtractor={(x) => x.id}
      ListHeaderComponent={
        <Pressable style={[s.btn, !due.length && { opacity: 0.5 }]} disabled={!due.length} onPress={() => setMode('review')}>
          <Text style={s.btnT}>{due.length ? `오늘 복습 ${due.length}개 시작` : '오늘 복습할 카드가 없어요'}</Text>
        </Pressable>}
      ListEmptyComponent={<Text style={[s.ex, { textAlign: 'center', marginTop: 30 }]}>에피소드의 단어·표현에서 ☆를 누르면 여기 모여요.</Text>}
      renderItem={({ item }) => (
        <Pressable style={s.row} onLongPress={() => Alert.alert('삭제할까요?', item.text, [{ text: '취소' }, { text: '삭제', style: 'destructive', onPress: async () => { await api.deleteItem(item.id); load(); } }])}>
          <Text style={s.word}>{item.text} <Text style={s.kind}>{item.kind === 'word' ? '단어' : '표현'}</Text></Text>
          <Text style={s.mean}>{item.meaning_ko}</Text>
        </Pressable>)} />
  );
}
const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  h: { fontSize: 20, fontWeight: '700', color: C.ink, marginBottom: 16 },
  btn: { backgroundColor: C.accent, padding: 14, borderRadius: 12, alignItems: 'center', marginBottom: 14 },
  btnT: { color: '#fff', fontWeight: '700' },
  count: { color: C.ink3, marginBottom: 12 },
  card: { width: '100%', minHeight: 220, backgroundColor: C.sheet, borderRadius: 18, borderWidth: 1, borderColor: C.line, padding: 24, alignItems: 'center', justifyContent: 'center' },
  front: { fontSize: 24, fontWeight: '700', color: C.ink, textAlign: 'center' },
  back: { fontSize: 17, color: C.ink, marginTop: 16, textAlign: 'center' },
  tap: { color: C.ink3, marginTop: 16 },
  grades: { flexDirection: 'row', gap: 8, marginTop: 18 },
  g: { borderWidth: 1, borderColor: C.line, borderRadius: 10, paddingVertical: 10, paddingHorizontal: 14, backgroundColor: C.sheet },
  gT: { color: C.ink, fontWeight: '600' },
  row: { backgroundColor: C.sheet, borderRadius: 12, padding: 14, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  word: { fontWeight: '700', color: C.ink, fontSize: 15.5 },
  kind: { fontWeight: '400', color: C.ink3, fontSize: 12 },
  mean: { color: C.ink2, marginTop: 3 },
  ex: { color: C.ink2, marginTop: 8, textAlign: 'center' },
});
