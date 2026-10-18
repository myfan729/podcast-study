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
import * as Updates from 'expo-updates';
import { handleAuthUrl } from '@/lib/authLink';
import { SessionProvider, useSession } from '@/lib/session';
import { NowPlayingProvider } from '@/lib/nowPlaying';
import { Notifications, notificationTarget, registerPush } from '@/lib/push';
import { C } from '@/lib/theme';
import { PRIVACY_VERSION, TERMS_VERSION } from '@/lib/config';

export { ErrorBoundary } from 'expo-router';
SplashScreen.preventAutoHideAsync();

function Gate({ fontsReady }: { fontsReady: boolean }) {
  const { session, loading, profile, profileLoading } = useSession();
  const segments = useSegments();
  const router = useRouter();
  const url = Linking.useURL();
  useEffect(() => { handleAuthUrl(url).catch(() => {}); }, [url]);
  useEffect(() => {
    if (loading || !fontsReady || (session && profileLoading)) return;
    SplashScreen.hideAsync();
    const at = segments[0] as string | undefined;
    // signed in → sign-up record with the current terms → the app
    const agreed = !!profile && profile.terms_version === TERMS_VERSION && profile.privacy_version === PRIVACY_VERSION;
    if (!session) { if (at !== 'login') router.replace('/login'); }
    else if (!agreed) { if (at !== 'signup') router.replace('/signup'); }
    else if (at === 'login' || at === 'signup') router.replace('/');
  }, [session, loading, fontsReady, segments, router, profile, profileLoading]);

  // push notifications: register once signed up; a tapped notification opens its episode
  const ready = !!session && !!profile;
  useEffect(() => { if (ready) registerPush(); }, [ready]);
  useEffect(() => {
    if (!ready) return;
    const go = (n?: Notifications.Notification) => {
      const t = notificationTarget(n);
      if (t) router.push({ pathname: '/episode/[id]', params: t });
    };
    Notifications.getLastNotificationResponseAsync().then((r) => go(r?.notification)).catch(() => {});
    const sub = Notifications.addNotificationResponseReceivedListener((r) => go(r.notification));
    return () => sub.remove();
  }, [ready, router]);
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: C.bg } }}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="login" />
      <Stack.Screen name="signup" />
      <Stack.Screen name="show/[id]" />
      <Stack.Screen name="episode/[id]" />
    </Stack>
  );
}

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({ Jua_400Regular, Nunito_600SemiBold, Nunito_800ExtraBold, Nunito_900Black, ...Ionicons.font });
  useEffect(() => {
    // pick up a newer over-the-air update right away instead of on the next launch
    if (__DEV__ || !Updates.isEnabled) return;
    (async () => {
      try {
        const r = await Updates.checkForUpdateAsync();
        if (r.isAvailable) { await Updates.fetchUpdateAsync(); await Updates.reloadAsync(); }
      } catch { /* offline: keep the current version */ }
    })();
  }, []);
  useEffect(() => {
    // background playback with lock-screen controls (expo-audio)
    setAudioModeAsync({ playsInSilentMode: true, shouldPlayInBackground: true, interruptionMode: 'doNotMix' }).catch(() => {});
  }, []);
  return (
    <SessionProvider>
      <StatusBar style="dark" />
      <NowPlayingProvider><Gate fontsReady={fontsLoaded || !!fontError} /></NowPlayingProvider>
    </SessionProvider>
  );
}
