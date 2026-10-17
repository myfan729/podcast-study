import { Stack, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { setAudioModeAsync } from 'expo-audio';
import 'react-native-reanimated';
import { SessionProvider, useSession } from '@/lib/session';
import { C } from '@/lib/theme';

export { ErrorBoundary } from 'expo-router';
SplashScreen.preventAutoHideAsync();

function Gate() {
  const { session, loading } = useSession();
  const segments = useSegments();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    SplashScreen.hideAsync();
    const onLogin = segments[0] === 'login';
    if (!session && !onLogin) router.replace('/login');
    else if (session && onLogin) router.replace('/');
  }, [session, loading, segments, router]);
  return (
    <Stack screenOptions={{ headerTintColor: C.ink, headerStyle: { backgroundColor: C.bg }, contentStyle: { backgroundColor: C.bg } }}>
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="login" options={{ headerShown: false }} />
      <Stack.Screen name="show/[id]" options={{ title: '' }} />
      <Stack.Screen name="episode/[id]" options={{ title: '' }} />
    </Stack>
  );
}

export default function RootLayout() {
  useEffect(() => {
    // background playback with lock-screen controls (expo-audio)
    setAudioModeAsync({ playsInSilentMode: true, shouldPlayInBackground: true, interruptionMode: 'doNotMix' }).catch(() => {});
  }, []);
  return <SessionProvider><Gate /></SessionProvider>;
}
