// Pro subscription through RevenueCat (Google Play Billing underneath). RevenueCat knows the purchase;
// our server asks RevenueCat (sync_my_pro) and writes the entitlement the rest of the app reads (is_pro).
import { Platform } from 'react-native';
import Purchases, { type PurchasesOffering, type PurchasesPackage } from 'react-native-purchases';
import { PRO_ENTITLEMENT, REVENUECAT_ANDROID_KEY } from './config';
import { supabase } from './supabase';

let configuredFor: string | null = null;

export const purchasesAvailable = () => Platform.OS === 'android' && !!REVENUECAT_ANDROID_KEY;

/** Configure once per signed-in user; purchases are tied to the Supabase user id, not the device. */
export async function initPurchases(userId: string) {
  if (!purchasesAvailable() || configuredFor === userId) return;
  if (!configuredFor) Purchases.configure({ apiKey: REVENUECAT_ANDROID_KEY, appUserID: userId });
  else await Purchases.logIn(userId);
  configuredFor = userId;
}

/** Ask the server to re-check with RevenueCat; returns whether the user is pro now. */
export async function syncPro(): Promise<boolean> {
  const r = await supabase.rpc('sync_my_pro');
  return !!r.data;
}

export async function currentOffering(): Promise<PurchasesOffering | null> {
  if (!purchasesAvailable()) return null;
  const o = await Purchases.getOfferings();
  return o.current ?? null;
}

/** Buy a package; returns true when the pro entitlement is active (server synced). */
export async function buy(pkg: PurchasesPackage): Promise<boolean> {
  const { customerInfo } = await Purchases.purchasePackage(pkg);
  const active = !!customerInfo.entitlements.active[PRO_ENTITLEMENT];
  return (await syncPro()) || active;
}

export async function restore(): Promise<boolean> {
  const info = await Purchases.restorePurchases();
  const active = !!info.entitlements.active[PRO_ENTITLEMENT];
  return (await syncPro()) || active;
}

/** Google Play's own subscription page (cancel, change plan, payment method). */
export function manageUrl(packageName: string) {
  return `https://play.google.com/store/account/subscriptions?package=${packageName}`;
}
