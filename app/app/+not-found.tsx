import { Link } from 'expo-router';
import { Text, View } from 'react-native';
import { C, F } from '@/lib/theme';

export default function NotFound() {
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20, backgroundColor: C.bg }}>
      <Text style={{ color: C.ink, fontSize: 22, fontFamily: F.title }}>찾는 화면이 없어요</Text>
      <Link href="/" style={{ marginTop: 16, color: C.accent, fontWeight: '700' }}>홈으로</Link>
    </View>
  );
}
