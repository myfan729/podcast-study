import { useEffect, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, Text, View, type StyleProp, type TextStyle } from 'react-native';

/** One line of text that slowly scrolls sideways when it doesn't fit, so the whole title can be read. */
export default function Marquee({ text, style }: { text: string; style?: StyleProp<TextStyle> }) {
  const [boxW, setBoxW] = useState(0);
  const [textW, setTextW] = useState(0);
  const x = useRef(new Animated.Value(0)).current;
  const dist = Math.max(0, textW - boxW);

  useEffect(() => {
    x.setValue(0);
    if (!dist) return;
    const ms = Math.max(2500, dist * 28);
    const loop = Animated.loop(Animated.sequence([
      Animated.delay(1500),
      Animated.timing(x, { toValue: -dist, duration: ms, easing: Easing.linear, useNativeDriver: true }),
      Animated.delay(1500),
      Animated.timing(x, { toValue: 0, duration: 500, useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [dist, x]);

  return (
    <View style={s.box} onLayout={(e) => setBoxW(e.nativeEvent.layout.width)} accessible accessibilityLabel={text}>
      {/* measured off-screen at its natural width */}
      <View style={s.measure} pointerEvents="none">
        <Text style={style} onLayout={(e) => setTextW(e.nativeEvent.layout.width)}>{text}</Text>
      </View>
      <Animated.View style={{ transform: [{ translateX: x }], alignSelf: dist ? 'flex-start' : 'center', width: dist ? textW + 1 : undefined }}>
        <Text style={style} numberOfLines={1}>{text}</Text>
      </Animated.View>
    </View>
  );
}
const s = StyleSheet.create({
  box: { overflow: 'hidden', alignSelf: 'stretch' },
  measure: { position: 'absolute', opacity: 0, flexDirection: 'row', width: 4000 },
});
