import { Tabs } from 'expo-router';
import type { BottomTabBarProps } from 'expo-router/tabs';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Icon, type IconName } from '@/components/ui';
import { C, shadow } from '@/lib/theme';

const TABS: Record<string, { label: string; icon: IconName; on: IconName }> = {
  index: { label: '홈', icon: 'home-outline', on: 'home' },
  discover: { label: '찾기', icon: 'search-outline', on: 'search' },
  vocab: { label: '단어장', icon: 'book-outline', on: 'book' },
  settings: { label: '나', icon: 'person-outline', on: 'person' },
};

/** Floating white pill; the active tab gets a soft violet capsule. */
function TabBar({ state, navigateToTab }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[s.wrap, { paddingBottom: Math.max(insets.bottom, 12) }]}>
      <View style={[s.bar, shadow]}>
        {state.routes.map((r, i) => {
          const t = TABS[r.name]; if (!t) return null;
          const on = state.index === i;
          return (
            <Pressable key={r.key} accessibilityRole="tab" accessibilityState={{ selected: on }} accessibilityLabel={t.label}
              onPress={() => { if (!on) navigateToTab(r.key); }} style={[s.tab, on && { backgroundColor: C.accentSoft }]}>
              <Icon name={on ? t.on : t.icon} size={21} color={on ? C.accent : C.ink3} />
              <Text style={[s.label, { color: on ? C.accent : C.ink3, fontWeight: on ? '700' : '500' }]}>{t.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export default function TabLayout() {
  return (
    <Tabs tabBar={(p) => <TabBar {...p} />} screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: C.bg } }}>
      <Tabs.Screen name="index" />
      <Tabs.Screen name="discover" />
      <Tabs.Screen name="vocab" />
      <Tabs.Screen name="settings" />
    </Tabs>
  );
}

const s = StyleSheet.create({
  wrap: { backgroundColor: C.bg, paddingHorizontal: 16, paddingTop: 6 },
  bar: { flexDirection: 'row', justifyContent: 'space-around', backgroundColor: C.sheet, borderRadius: 28, padding: 8 },
  tab: { minWidth: 66, minHeight: 50, borderRadius: 20, alignItems: 'center', justifyContent: 'center', gap: 2 },
  label: { fontSize: 11.5 },
});
