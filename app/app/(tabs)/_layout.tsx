import { Tabs } from 'expo-router';
import { Text } from 'react-native';
import { C } from '@/lib/theme';

const icon = (glyph: string) => ({ color }: { color: unknown }) => <Text style={{ color: color as string, fontSize: 18 }}>{glyph}</Text>;

export default function TabLayout() {
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: C.accent, headerStyle: { backgroundColor: C.bg }, headerTintColor: C.ink,
      sceneStyle: { backgroundColor: C.bg } }}>
      <Tabs.Screen name="index" options={{ title: '홈', tabBarIcon: icon('⌂') }} />
      <Tabs.Screen name="discover" options={{ title: '찾기', tabBarIcon: icon('⌕') }} />
      <Tabs.Screen name="vocab" options={{ title: '단어장', tabBarIcon: icon('✎') }} />
      <Tabs.Screen name="settings" options={{ title: '설정', tabBarIcon: icon('⚙') }} />
    </Tabs>
  );
}
