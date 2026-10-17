import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps, ReactNode } from 'react';
import { Image, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import { C, F, R, tileColor } from '@/lib/theme';

export type IconName = ComponentProps<typeof Ionicons>['name'];
export const Icon = ({ name, size = 20, color = C.ink }: { name: IconName; size?: number; color?: string }) =>
  <Ionicons name={name} size={size} color={color} />;

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
      <View style={{ width: size + 8, height: size + 8, borderRadius: (size + 8) * 0.35, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name="ear" size={size * 0.72} color="#fff" />
      </View>
      <Text style={{ fontFamily: F.title, fontSize: size, color: C.ink }}>잉팟</Text>
    </View>
  );
}

/** Big Jua page title used at the top of each tab. */
export function PageTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <View style={s.titleRow}>
      {typeof children === 'string' ? <Text style={s.title}>{children}</Text> : children}
      {right}
    </View>
  );
}

export function RoundBtn({ icon, onPress, label, size = 44, bg = C.sheet, color = C.ink }:
  { icon: IconName; onPress?: () => void; label: string; size?: number; bg?: string; color?: string }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} hitSlop={4}
      style={({ pressed }) => [{ width: size, height: size, borderRadius: size / 2, backgroundColor: bg, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.7 : 1 }]}>
      <Icon name={icon} size={size * 0.45} color={color} />
    </Pressable>
  );
}

export function Btn({ label, onPress, kind = 'primary', disabled, style }:
  { label: string; onPress?: () => void; kind?: 'primary' | 'soft' | 'plain'; disabled?: boolean; style?: StyleProp<ViewStyle> }) {
  const bg = kind === 'primary' ? C.accent : kind === 'soft' ? C.accentSoft : C.sheet;
  const fg = kind === 'primary' ? C.onAccent : kind === 'soft' ? C.accent : C.ink2;
  return (
    <Pressable accessibilityRole="button" onPress={onPress} disabled={disabled}
      style={({ pressed }) => [s.btn, { backgroundColor: bg, opacity: disabled ? 0.45 : pressed ? 0.8 : 1 }, style]}>
      <Text style={[s.btnT, { color: fg }]}>{label}</Text>
    </Pressable>
  );
}

export function Chip({ label, on, onPress }: { label: string; on?: boolean; onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} style={[s.chip, on && { backgroundColor: C.dark }]}>
      <Text style={[s.chipT, on && { color: '#fff', fontWeight: '700' }]}>{label}</Text>
    </Pressable>
  );
}

/** Square artwork, or a pastel tile when the show has no image. */
export function Art({ uri, id, size, radius = 18 }: { uri?: string | null; id: string; size: number | `${number}%`; radius?: number }) {
  const st = { width: size, height: size, borderRadius: radius, backgroundColor: tileColor(id) } as const;
  return uri ? <Image source={{ uri }} style={st} /> : <View style={[st, { alignItems: 'center', justifyContent: 'center' }]}><Icon name="mic" size={22} color={C.ink2} /></View>;
}

const s = StyleSheet.create({
  titleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 22, paddingTop: 12, paddingBottom: 10 },
  title: { fontFamily: F.title, fontSize: 28, color: C.ink },
  btn: { minHeight: 52, borderRadius: R.btn, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 22 },
  btnT: { fontSize: 15, fontWeight: '700' },
  chip: { minHeight: 38, paddingHorizontal: 15, borderRadius: R.pill, backgroundColor: C.sheet, justifyContent: 'center' },
  chipT: { color: C.ink2, fontSize: 13.5 },
});
