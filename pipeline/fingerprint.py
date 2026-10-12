"""Audio fingerprint shared with docs/assets/sync.js — keep both implementations identical.

Input: mono PCM at 8 kHz. Frames of 2048 samples (256 ms), hop 512 (64 ms), Hann window.
16 log-spaced bands between 300 and 3000 Hz → log energies → 15 sign bits per frame
(Haitsma–Kalker style): bit[m] = (ΔL[n][m] − ΔL[n−1][m]) > 0 where ΔL[n][m] = L[n][m] − L[n][m+1].
Two frames match when the Hamming distance over a window of frames is low (bit error rate < ~0.3).
"""
from __future__ import annotations

import base64
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np

SR = 8000
N_FFT = 2048
HOP = 512
N_BANDS = 16
F_MIN, F_MAX = 300.0, 3000.0
HOP_SEC = HOP / SR


def band_edges() -> list[int]:
    """FFT bin index of each band edge (17 edges → 16 bands)."""
    edges = [F_MIN * (F_MAX / F_MIN) ** (i / N_BANDS) for i in range(N_BANDS + 1)]
    return [int(math.floor(f * N_FFT / SR)) for f in edges]


BAND_BINS = band_edges()


def decode_pcm(path: str | Path, sr: int = SR) -> np.ndarray:
    """Decode any audio file to float32 mono PCM at `sr` with ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found")
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def band_log_energies(pcm: np.ndarray) -> np.ndarray:
    """(n_frames, 16) log band energies."""
    if len(pcm) < N_FFT:
        pcm = np.pad(pcm, (0, N_FFT - len(pcm)))
    n_frames = 1 + (len(pcm) - N_FFT) // HOP
    window = np.hanning(N_FFT).astype(np.float32)
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    frames = pcm[idx] * window
    spec = np.fft.rfft(frames, axis=1)
    power = (spec.real ** 2 + spec.imag ** 2)
    out = np.empty((n_frames, N_BANDS), dtype=np.float64)
    for b in range(N_BANDS):
        lo, hi = BAND_BINS[b], BAND_BINS[b + 1]
        out[:, b] = np.log(power[:, lo:hi].sum(axis=1) + 1e-9)
    return out


def bits_from_energies(le: np.ndarray) -> np.ndarray:
    """uint16 fingerprint per frame (frame 0 has no predecessor → bits computed against itself = 0)."""
    d = le[:, :-1] - le[:, 1:]                     # (n, 15)
    dd = np.zeros_like(d)
    dd[1:] = d[1:] - d[:-1]
    bits = (dd > 0).astype(np.uint16)
    weights = (1 << np.arange(15, dtype=np.uint16))
    return (bits * weights).sum(axis=1).astype(np.uint16)


def fingerprint(pcm: np.ndarray) -> np.ndarray:
    return bits_from_energies(band_log_energies(pcm))


POPCOUNT = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.uint8)


def ber(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 1.0
    return float(POPCOUNT[np.bitwise_xor(a[:n], b[:n])].sum()) / (15.0 * n)


def best_offset(ref: np.ndarray, probe: np.ndarray, lo: int, hi: int) -> tuple[int, float, float]:
    """Slide `ref` over `probe` for offsets in [lo, hi]; return (offset, ber, second_best_ber)."""
    best, best_o, second = 1.0, lo, 1.0
    n = len(ref)
    for o in range(max(lo, 0), min(hi, len(probe) - n) + 1):
        e = ber(ref, probe[o:o + n])
        if e < best:
            if abs(o - best_o) > 3:
                second = best
            best, best_o = e, o
        elif e < second and abs(o - best_o) > 3:
            second = e
    return best_o, best, second


def encode(fp: np.ndarray) -> str:
    return base64.b64encode(fp.astype("<u2").tobytes()).decode("ascii")


def decode(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype="<u2")
