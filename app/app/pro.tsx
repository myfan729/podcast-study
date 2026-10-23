// 프로 안내 + 구독 화면. Prices come from Google Play (via RevenueCat), so they're always the real, local ones.
import { useRouter } from 'expo-router';
import Constants from 'expo-constants';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { PurchasesPackage } from 'react-native-purchases';
import { Icon, RoundBtn } from '@/components/ui';
import * as api from '@/lib/api';
import { FREE_PER_WEEK, TERMS_URL } from '@/lib/config';
import { buy, currentOffering, manageUrl, purchasesAvailable, restore } from '@/lib/purchases';
import { C, F, R } from '@/lib/theme';

const PERKS: [string, string][] = [
  ['infinite', '학습자료 무제한 — 대본 싱크·번역·단어·표현을 원하는 만큼'],
  ['headset', '듣기와 백그라운드 재생은 지금처럼 무제한'],
  ['sparkles', '앞으로 나오는 프로 기능 모두 포함'],
];

export default function Pro() {
  const router = useRouter();
  const [pkgs, setPkgs] = useState<PurchasesPackage[] | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pro, setPro] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    api.freeLeft().then((p) => setPro(p.pro)).catch(() => {});
    if (!purchasesAvailable()) { setPkgs([]); return; }
    currentOffering().then((o) => {
      const list = o?.availablePackages ?? [];
      setPkgs(list);
      const yearly = list.find((p) => p.packageType === 'ANNUAL');
      setPick((yearly ?? list[0])?.identifier ?? null);
    }).catch((e) => { setErr(String(e?.message ?? e)); setPkgs([]); });
  }, []);

  const done = (ok: boolean) => {
    if (ok) { setPro(true); Alert.alert('프로가 됐어요', '이제 학습자료를 무제한으로 만들 수 있어요.', [{ text: '좋아요', onPress: () => router.back() }]); }
  };
  const purchase = async () => {
    const p = pkgs?.find((x) => x.identifier === pick); if (!p) return;
    setBusy(true);
    try { done(await buy(p)); } catch (e: any) { if (!e?.userCancelled) Alert.alert('결제하지 못했어요', String(e?.message ?? e)); } finally { setBusy(false); }
  };
  const doRestore = async () => {
    setBusy(true);
    try { const ok = await restore(); ok ? done(true) : Alert.alert('복원할 구독이 없어요', '이 계정으로 산 구독이 없어요.'); }
    catch (e: any) { Alert.alert('복원하지 못했어요', String(e?.message ?? e)); } finally { setBusy(false); }
  };
  const pkgName = Constants.expoConfig?.android?.package ?? '';

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <View style={{ paddingHorizontal: 16, paddingTop: 6 }}><RoundBtn icon="close" label="닫기" onPress={() => router.back()} /></View>
      <ScrollView contentContainerStyle={s.wrap}>
        <View style={s.badge}><Icon name="diamond" size={30} color="#fff" /></View>
        <Text style={s.h}>잉팟 프로</Text>
        <Text style={s.sub}>무료는 학습자료 일주일에 {FREE_PER_WEEK}편까지예요.{'\n'}프로는 제한 없이 공부할 수 있어요.</Text>

        <View style={s.card}>
          {PERKS.map(([icon, t]) => (
            <View key={t} style={s.perk}><Icon name={icon as any} size={18} color={C.accent} /><Text style={s.perkT}>{t}</Text></View>))}
        </View>

        {pro ? (
          <View style={s.card}>
            <Text style={s.perkT}>지금 프로를 쓰고 있어요.</Text>
            <Pressable onPress={() => Linking.openURL(manageUrl(pkgName))}><Text style={s.link}>구독 관리 (Google Play)</Text></Pressable>
          </View>
        ) : pkgs === null ? <ActivityIndicator color={C.accent} style={{ marginTop: 24 }} /> : pkgs.length === 0 ? (
          <Text style={s.note}>{err || '구독은 곧 열려요. 조금만 기다려 주세요.'}</Text>
        ) : (
          <>
            {pkgs.map((p) => {
              const on = p.identifier === pick, yearly = p.packageType === 'ANNUAL';
              const trial = p.product.introPrice?.price === 0 || (p.product as any).defaultOption?.freePhase;
              return (
                <Pressable key={p.identifier} onPress={() => setPick(p.identifier)} style={[s.plan, on && s.planOn]} accessibilityRole="radio" accessibilityState={{ checked: on }}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.planT}>{yearly ? '연간' : '월간'} {yearly ? <Text style={s.save}>  약 33% 할인</Text> : null}</Text>
                    <Text style={s.planP}>{p.product.priceString} / {yearly ? '년' : '월'}{trial ? ' · 7일 무료 체험' : ''}</Text>
                  </View>
                  <Icon name={on ? 'radio-button-on' : 'radio-button-off'} size={22} color={on ? C.accent : C.faint} />
                </Pressable>);
            })}
            <Pressable style={[s.btn, busy && { opacity: 0.6 }]} onPress={purchase} disabled={busy || !pick} accessibilityRole="button">
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.btnT}>구독 시작하기</Text>}
            </Pressable>
            <Text style={s.fine}>구독은 Google Play 계정으로 결제되고, 해지하지 않으면 같은 주기로 자동 갱신돼요. 해지는 Google Play의 구독 관리에서 언제든 할 수 있고, 남은 기간까지 프로를 쓸 수 있어요.</Text>
          </>
        )}
        <View style={s.row}>
          <Pressable onPress={doRestore} hitSlop={8}><Text style={s.link}>구매 복원</Text></Pressable>
          <Text style={s.dot}>·</Text>
          <Pressable onPress={() => Linking.openURL(TERMS_URL)} hitSlop={8}><Text style={s.link}>이용약관</Text></Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  wrap: { padding: 22, paddingTop: 4, gap: 14 },
  badge: { width: 64, height: 64, borderRadius: 22, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center', alignSelf: 'center' },
  h: { fontFamily: F.title, fontSize: 30, color: C.ink, textAlign: 'center' },
  sub: { color: C.ink2, textAlign: 'center', lineHeight: 21 },
  card: { backgroundColor: C.sheet, borderRadius: R.card, padding: 18, gap: 12 },
  perk: { flexDirection: 'row', gap: 10, alignItems: 'center' },
  perkT: { color: C.ink, fontSize: 14.5, flex: 1, lineHeight: 20 },
  plan: { flexDirection: 'row', alignItems: 'center', backgroundColor: C.sheet, borderRadius: 20, padding: 16, borderWidth: 2, borderColor: 'transparent' },
  planOn: { borderColor: C.accent },
  planT: { color: C.ink, fontWeight: '700', fontSize: 16 },
  save: { color: C.accent, fontSize: 13 },
  planP: { color: C.ink2, marginTop: 3 },
  btn: { backgroundColor: C.accent, borderRadius: R.pill, minHeight: 56, alignItems: 'center', justifyContent: 'center' },
  btnT: { color: '#fff', fontWeight: '700', fontSize: 16.5 },
  fine: { color: C.ink3, fontSize: 12, lineHeight: 18 },
  note: { color: C.ink2, textAlign: 'center', marginTop: 10 },
  row: { flexDirection: 'row', justifyContent: 'center', gap: 10, marginTop: 4 },
  link: { color: C.ink3, fontSize: 13, textDecorationLine: 'underline' },
  dot: { color: C.ink3 },
});
