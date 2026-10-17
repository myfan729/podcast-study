import { Stack, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { setAudioModeAsync } from 'expo-audio';
import { useFonts } from 'expo-font';
import { StatusBar } from 'expo-status-bar';
import { Jua_400Regular } from '@expo-google-fonts/jua/400Regular';
import { Nunito_600SemiBold } from '@expo-google-fonts/nunito/600SemiBold';
import { Nunito_800ExtraBold } from '@expo-google-fonts/nunito/800ExtraBold';
import { Nunito_900Black } from '@expo-google-fonts/nunito/900Black';
import Ionicons from '@expo/vector-icons/Ionicons';
import 'react-native-reanimated';
import * as Linking from 'expo-linking';
import { handleAuthUrl } from '@/lib/authLink';
import { SessionProvider, useSession } from '@/lib/session';
import { C } from '@/lib/theme';

export { ErrorBoundary } from 'expo-router';
SplashScreen.preventAutoHideAsync();

function Gate({ fontsReady }: { fontsReady: boolean }) {
  const { session, loading } = useSession();
  const segments = useSegments();
  const router = useRouter();
  const url = Linking.useURL();
  useEffect(() => { handleAuthUrl(url).catch(() => {}); }, [url]);
  useEffect(() => {
    if (loading || !fontsReady) return;
    SplashScreen.hideAsync();
    const onLogin = segments[0] === 'login';
    if (!session && !onLogin) router.replace('/login');
    else if (session && onLogin) router.replace('/');
  }, [session, loading, fontsReady, segments, router]);
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: C.bg } }}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="login" />
      <Stack.Screen name="show/[id]" />
      <Stack.Screen name="episode/[id]" />
    </Stack>
  );
}

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({ Jua_400Regular, Nunito_600SemiBold, Nunito_800ExtraBold, Nunito_900Black, ...Ionicons.font });
  useEffect(() => {
    // background playback with lock-screen controls (expo-audio)
    setAudioModeAsync({ playsInSilentMode: true, shouldPlayInBackground: true, interruptionMode: 'doNotMix' }).catch(() => {});
  }, []);
  return (
    <SessionProvider>
      <StatusBar style="dark" />
      <Gate fontsReady={fontsLoaded || !!fontError} />
    </SessionProvider>
  );
}
