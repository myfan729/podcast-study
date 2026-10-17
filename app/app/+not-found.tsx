import { Link, Stack } from 'expo-router';
import { Text, View } from 'react-native';
import { C } from '@/lib/theme';

export default function NotFound() {
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20 }}>
      <Stack.Screen options={{ title: '없는 화면' }} />
      <Text style={{ color: C.ink, fontSize: 18, fontWeight: '700' }}>찾는 화면이 없어요</Text>
      <Link href="/" style={{ marginTop: 16, color: C.accent }}>홈으로</Link>
    </View>
  );
}
