// One app-wide player for plain listening, so an episode keeps playing while the user browses
// (mini player above the tabs), with the screen off, or from the lock screen.
// The study mode has its own player (it plays the downloaded, synced copy) and stops this one.
import { useAudioPlayer, useAudioPlayerStatus, type AudioPlayer, type AudioStatus } from 'expo-audio';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import * as api from './api';
import type { Episode } from './types';

type NowPlaying = {
  ep: Episode | null; player: AudioPlayer; status: AudioStatus;
  load: (ep: Episode) => void; stop: () => void;
};
const Ctx = createContext<NowPlaying | null>(null);

export function NowPlayingProvider({ children }: { children: ReactNode }) {
  const player = useAudioPlayer(null, { updateInterval: 500 });
  const status = useAudioPlayerStatus(player);
  const [ep, setEp] = useState<Episode | null>(null);
  const epRef = useRef<Episode | null>(null);
  const token = useRef(0);

  const save = useCallback((finished = false) => {
    const e = epRef.current;
    if (e) api.saveProgress(e.id, player.currentTime ?? 0, finished).catch(() => {});
  }, [player]);

  const load = useCallback((e: Episode) => {
    if (epRef.current?.id === e.id) { if (!player.playing) player.play(); return; }
    save();
    epRef.current = e; setEp(e);
    const my = ++token.current;
    player.replace(api.secureAudio(e.audio_url));
    player.setActiveForLockScreen?.(true, { title: e.title, artist: e.shows?.title ?? '', artworkUrl: e.image_url ?? e.shows?.image_url ?? undefined });
    // resume where the user left off: wait for the new source to load, then seek and play
    api.lastPosition(e.id).catch(() => 0).then(async (pos) => {
      for (let i = 0; i < 60 && token.current === my && !(player.isLoaded && player.duration > 0); i++) await new Promise((r) => setTimeout(r, 250));
      if (token.current !== my) return;
      if (pos > 20) await player.seekTo(pos);
      player.play();
    });
  }, [player, save]);

  const stop = useCallback(() => {
    token.current++;
    save(); player.pause();
    player.setActiveForLockScreen?.(false);
    epRef.current = null; setEp(null);
  }, [player, save]);

  // remember the position every 15 s while playing; mark finished near the end
  const lastSaved = useRef(0);
  useEffect(() => {
    const t = status.currentTime ?? 0;
    if (!epRef.current || !status.playing || Math.abs(t - lastSaved.current) < 15) return;
    lastSaved.current = t;
    save(!!status.duration && t > status.duration - 30);
  }, [status.currentTime, status.playing, save, status.duration]);

  const value = useMemo(() => ({ ep, player, status, load, stop }), [ep, player, status, load, stop]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useNowPlaying(): NowPlaying {
  const v = useContext(Ctx);
  if (!v) throw new Error('NowPlayingProvider missing');
  return v;
}
