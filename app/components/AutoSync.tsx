/**
 * Automatic ad-aware sync on the phone, same method as the website (docs/assets/sync.js):
 * 1. download this listener's copy of the episode (with its own ads) to the cache,
 * 2. a hidden WebView fingerprints the audio right after each ad break and matches it against the
 *    reference fingerprints the server made from the ad-free content (episodes/<id>.sync.json),
 * 3. the player switches to the downloaded file, so what plays is exactly what was aligned.
 */
import { Directory, File, Paths } from 'expo-file-system';
import { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';
import { WebView as RNWebView, type WebViewMessageEvent } from 'react-native-webview';
import type { ComponentType } from 'react';

// react-native-webview's class typings don't line up with React 19's JSX types; the runtime is fine
const WebView = RNWebView as unknown as ComponentType<Record<string, unknown>>;
import type { Anchor } from '@/lib/timeline';
import { PODSYNC_JS } from '@/lib/podsync.generated';

export type SyncResult = { fileUri: string; anchors: Anchor[]; ok: boolean; report?: unknown };

const RUNNER = `
window.run = function (job) {
  var post = function (m) { window.ReactNativeWebView.postMessage(JSON.stringify(m)); };
  var x = new XMLHttpRequest();                       // fetch() can't read file:// in Android WebView
  x.open('GET', job.file); x.responseType = 'blob';
  x.onload = function () {
    PodSync.align(x.response, job.ref, function (s) { post({ t: 'status', s: s }); }, { slack: job.ref.fixed ? 30 : 0,
      readyAt: job.readyAt || 0, onPartial: function (a) { post({ t: 'partial', anchors: a }); } })
      .then(function (r) { post({ t: 'done', anchors: r.anchors, report: r.report }); })
      .catch(function (e) { post({ t: 'error', e: String(e && e.message || e) }); });
  };
  x.onerror = function () { post({ t: 'error', e: 'could not read the downloaded file' }); };
  x.send();
};
`;

export default function AutoSync({ episodeId, audioUrl, syncRef, readyAt, onStatus, onPartial, onDone }: {
  episodeId: string; audioUrl: string; syncRef: unknown; readyAt: number;
  onStatus: (s: string) => void; onPartial?: (r: SyncResult) => void; onDone: (r: SyncResult | null, error?: string) => void;
}) {
  const [page, setPage] = useState<{ html: string; file: string; dir: string } | null>(null);
  const web = useRef<{ injectJavaScript: (js: string) => void } | null>(null);
  const done = useRef(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const dir = new Directory(Paths.cache, 'episodes');
        if (!dir.exists) dir.create({ idempotent: true });
        const audio = new File(dir, `${episodeId}.mp3`);
        if (!audio.exists || !audio.size) {
          onStatus('오디오 내려받는 중…');
          await File.downloadFileAsync(audioUrl, audio, { idempotent: true });
        }
        const html = new File(dir, 'podsync.html');
        html.writeSync(`<!doctype html><meta charset="utf-8"><script>${PODSYNC_JS}\n${RUNNER}</script>`);
        if (alive) { onStatus('자동 싱크 준비 중…'); setPage({ html: html.uri, file: audio.uri, dir: dir.uri }); }
      } catch (e) {
        if (alive && !done.current) { done.current = true; onDone(null, String((e as Error)?.message ?? e)); }
      }
    })();
    return () => { alive = false; };
  }, [episodeId, audioUrl]);  // eslint-disable-line react-hooks/exhaustive-deps

  const onMessage = (ev: WebViewMessageEvent) => {
    let m: { t: string; s?: string; e?: string; anchors?: Anchor[]; report?: unknown };
    try { m = JSON.parse(ev.nativeEvent.data); } catch { return; }
    if (m.t === 'status' && m.s) onStatus(m.s);
    if (done.current || !page) return;
    const tidy = (xs?: Anchor[]) => (xs ?? []).map((a) => ({ c: a.c, a: a.a })).sort((p, q) => p.c - q.c);
    if (m.t === 'partial') { const anchors = tidy(m.anchors); if (anchors.length) onPartial?.({ fileUri: page.file, anchors, ok: true }); return; }
    if (m.t === 'done') {
      done.current = true;
      const anchors = tidy(m.anchors);
      onDone({ fileUri: page.file, anchors, ok: anchors.length > 0, report: m.report });
    } else if (m.t === 'error') {
      done.current = true;
      onDone({ fileUri: page.file, anchors: [], ok: false }, m.e);
    }
  };

  if (!page) return null;
  return (
    <View style={{ width: 1, height: 1, opacity: 0, position: 'absolute' }} pointerEvents="none">
      <WebView ref={web} source={{ uri: page.html }} originWhitelist={['*']} javaScriptEnabled
        allowFileAccess allowFileAccessFromFileURLs allowUniversalAccessFromFileURLs allowingReadAccessToURL={page.dir}
        onMessage={onMessage}
        onLoadEnd={() => web.current?.injectJavaScript(`window.run(${JSON.stringify({ file: page.file, ref: syncRef, readyAt })}); true;`)}
        onError={(e: { nativeEvent: { description: string } }) => { if (!done.current) { done.current = true; onDone(null, e.nativeEvent.description); } }} />
    </View>
  );
}
