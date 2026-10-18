// Push notifications: ask permission, register this install's Expo push token, open the episode a
// notification is about. The server sends them (pipeline/push.py), honouring the switches in profiles.
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
import { Platform } from 'react-native';
import { supabase } from './supabase';

// in the foreground the home screen already shows it: no banner on top of the app
Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: false, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false }),
});

export async function registerPush(): Promise<'ok' | 'denied' | 'unavailable'> {
  if (Platform.OS === 'web' || !Device.isDevice) return 'unavailable';
  try {
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', { name: '잉팟 알림', importance: Notifications.AndroidImportance.DEFAULT });
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') return 'denied';
    const projectId = (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas?.projectId;
    const token = (await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined)).data;
    const { data } = await supabase.auth.getUser();
    if (!data.user || !token) return 'unavailable';
    await supabase.from('push_tokens').upsert({ token, user_id: data.user.id, platform: Platform.OS, updated_at: new Date().toISOString() });
    return 'ok';
  } catch {
    return 'unavailable';                                         // e.g. a build without Firebase set up
  }
}

/** Where a tapped notification should go: { episode, study? } → the episode screen. */
export function notificationTarget(n: Notifications.Notification | undefined) {
  const d = (n?.request.content.data ?? {}) as { episode?: string; study?: string };
  return d.episode ? { id: d.episode, ...(d.study ? { study: d.study } : {}) } : null;
}
export { Notifications };
