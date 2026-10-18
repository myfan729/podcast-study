import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, FlatList, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Chip, Icon, PageTitle } from '@/components/ui';
import * as api from '@/lib/api';
import type { SavedItem } from '@/lib/types';
import { C, F } from '@/lib/theme';

/** Saved words and expressions: a plain list, tap to see the example, trash button to remove. */
export default function VocabScreen() {
  const [items, setItems] = useState<SavedItem[]>([]);
  const [filter, setFilter] = useState<'all' | 'word' | 'expression'>('all');
  const [open, setOpen] = useState<string | null>(null);
  const load = useCallback(() => { api.myItems().then(setItems).catch(() => {}); }, []);
  useFocusEffect(load);
  const shown = items.filter((x) => filter === 'all' || x.kind === filter);
  const words = items.filter((x) => x.kind === 'word').length;

  const remove = (it: SavedItem) => {
    const run = async () => {
      setItems((xs) => xs.filter((x) => x.id !== it.id));            // gone right away; reload restores it on failure
      try { await api.deleteItem(it.id); } catch { load(); }
    };
    if (Platform.OS === 'web') { if (globalThis.confirm?.(`'${it.text}'을(를) 지울까요?`)) run(); return; }
    Alert.alert('단어장에서 지울까요?', it.text, [{ text: '취소', style: 'cancel' }, { text: '지우기', style: 'destructive', onPress: run }]);
  };

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1 }}>
      <FlatList contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 24 }} data={shown} keyExtractor={(x) => x.id}
        ListHeaderComponent={<View>
          <View style={{ marginHorizontal: -16 }}><PageTitle>단어장</PageTitle></View>
          {items.length > 0 && <Text style={s.count}>단어 {words}개 · 표현 {items.length - words}개</Text>}
          <View style={s.filters}>
            <Chip label="전체" on={filter === 'all'} onPress={() => setFilter('all')} />
            <Chip label="단어" on={filter === 'word'} onPress={() => setFilter('word')} />
            <Chip label="표현" on={filter === 'expression'} onPress={() => setFilter('expression')} />
          </View>
        </View>}
        ListEmptyComponent={<Text style={s.none}>에피소드의 단어·표현에서 ☆를 누르면 여기 모여요.</Text>}
        renderItem={({ item }) => {
          const isOpen = open === item.id;
          return (
            <Pressable style={s.row} onPress={() => setOpen(isOpen ? null : item.id)} accessibilityRole="button"
              accessibilityState={{ expanded: isOpen }}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                  <View style={[s.kind, item.kind !== 'word' && { backgroundColor: C.peach }]}><Text style={s.kindT}>{item.kind === 'word' ? '단어' : '표현'}</Text></View>
                  <Text style={s.word} numberOfLines={isOpen ? undefined : 1}>{item.text}</Text>
                </View>
                {item.meaning_ko ? <Text style={s.mean} numberOfLines={isOpen ? undefined : 2}>{item.meaning_ko}</Text> : null}
                {isOpen && item.example ? <View style={s.exBox}><Text style={s.ex}>{item.example}</Text></View> : null}
              </View>
              <Pressable onPress={() => remove(item)} hitSlop={8} style={s.del} accessibilityRole="button" accessibilityLabel={`${item.text} 지우기`}>
                <Icon name="trash-outline" size={19} color={C.ink3} />
              </Pressable>
            </Pressable>);
        }} />
    </SafeAreaView>
  );
}
const s = StyleSheet.create({
  count: { color: C.ink3, fontSize: 13, marginHorizontal: 6, marginTop: -2 },
  filters: { flexDirection: 'row', gap: 8, marginTop: 14, marginBottom: 12, marginHorizontal: 6 },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, backgroundColor: C.sheet, borderRadius: 20, padding: 16, marginBottom: 8 },
  word: { fontFamily: F.enB, color: C.ink, fontSize: 16, flexShrink: 1 },
  mean: { color: C.ink2, marginTop: 6, fontSize: 13.5, lineHeight: 19 },
  exBox: { backgroundColor: C.bg, borderRadius: 14, padding: 12, marginTop: 10 },
  ex: { fontFamily: F.en, color: C.ink2, fontSize: 14, lineHeight: 21 },
  kind: { backgroundColor: C.lilac, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  kindT: { fontSize: 11, color: C.ink2, fontWeight: '700' },
  del: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: C.bg },
  none: { color: C.ink3, textAlign: 'center', marginTop: 30, lineHeight: 20 },
});
