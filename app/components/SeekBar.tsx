// Playback position bar with a round knob that follows the finger: tap anywhere to jump,
// or drag (the time shown follows) and the player seeks once on release.
import { useRef, useState } from 'react';
import { PanResponder, StyleSheet, View } from 'react-native';
import { C } from '@/lib/theme';

export default function SeekBar({ position, duration, onSeek, onDrag }:
  { position: number; duration: number; onSeek: (sec: number) => void; onDrag?: (sec: number | null) => void }) {
  const [w, setW] = useState(1);
  const [drag, setDrag] = useState<number | null>(null);          // 0..1 while the finger is down
  const box = useRef({ w: 1, x0: 0 });
  const cb = useRef({ onSeek, onDrag, duration }); cb.current = { onSeek, onDrag, duration };
  const frac = (pageX: number) => Math.min(1, Math.max(0, (pageX - box.current.x0) / box.current.w));
  const pan = useRef(PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderTerminationRequest: () => false,                 // don't let the list steal the drag
    onPanResponderGrant: (e) => {
      // measure where the bar is on screen from this touch: pageX - locationX = bar's left edge
      box.current.x0 = e.nativeEvent.pageX - e.nativeEvent.locationX;
      const f = frac(e.nativeEvent.pageX); setDrag(f); cb.current.onDrag?.(f * cb.current.duration);
    },
    onPanResponderMove: (e) => { const f = frac(e.nativeEvent.pageX); setDrag(f); cb.current.onDrag?.(f * cb.current.duration); },
    onPanResponderRelease: (e) => {
      const f = frac(e.nativeEvent.pageX);
      setDrag(null); cb.current.onDrag?.(null); cb.current.onSeek(f * cb.current.duration);
    },
    onPanResponderTerminate: () => { setDrag(null); cb.current.onDrag?.(null); },
  })).current;

  const p = drag ?? (duration > 0 ? Math.min(1, position / duration) : 0);
  const KNOB = drag != null ? 22 : 16;
  return (
    <View style={s.hit} {...pan.panHandlers} onLayout={(e) => { const lw = e.nativeEvent.layout.width || 1; box.current.w = lw; setW(lw); }}
      accessibilityRole="adjustable" accessibilityLabel="재생 위치"
      accessibilityValue={{ min: 0, max: Math.round(duration), now: Math.round(p * duration) }}>
      <View style={s.track}><View style={[s.fill, { width: `${p * 100}%` }]} /></View>
      <View pointerEvents="none" style={[s.knob, { width: KNOB, height: KNOB, borderRadius: KNOB / 2, left: p * w - KNOB / 2, top: (HIT - KNOB) / 2 }]} />
    </View>
  );
}

const HIT = 30;
const s = StyleSheet.create({
  hit: { height: HIT, justifyContent: 'center' },
  track: { height: 6, borderRadius: 3, backgroundColor: C.track, overflow: 'hidden' },
  fill: { height: 6, borderRadius: 3, backgroundColor: C.progress },
  knob: { position: 'absolute', backgroundColor: '#fff', borderWidth: 3, borderColor: C.progress },
});
