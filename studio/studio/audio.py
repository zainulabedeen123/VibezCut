"""Audio extraction, loudness envelope, activity segmentation and quiet-run detection."""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import numpy as np

from . import config


def extract(video: str | Path) -> dict:
    """16 kHz mono (analysis) and 48 kHz stereo (final mix) WAVs + 10 ms dB envelope."""
    wd = config.workdir(video)
    a16, a48 = wd / "audio16k.wav", wd / "audio48k.wav"
    if not a16.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(a16)], check=True)
    if not a48.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(a48)], check=True)
    dbf = wd / "db.npy"
    if not dbf.exists():
        a = load16(a16)
        fr = 160
        m = len(a) // fr
        rms = np.sqrt((a[:m * fr].reshape(m, fr) ** 2).mean(1) + 1e-12)
        np.save(dbf, 20 * np.log10(rms))
    return {"audio16k": str(a16), "audio48k": str(a48), "db": str(dbf)}


def load16(path) -> np.ndarray:
    w = wave.open(str(path))
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def runs(db: np.ndarray, thr: float, minf: int = 3):
    """Contiguous stretches below ``thr`` dB, at least ``minf`` 10 ms frames long, in seconds."""
    below = db < thr
    out, k, n = [], 0, len(db)
    while k < n:
        if below[k]:
            m = k
            while m < n and below[m]:
                m += 1
            if m - k >= minf:
                out.append((k / 100, m / 100))
            k = m
        else:
            k += 1
    return out


def activity(db: np.ndarray, thr: float = -55, merge_gap: float = 0.12, min_len: float = 0.0):
    """Speech-ish blobs above ``thr``; gaps shorter than ``merge_gap`` are merged."""
    act = db > thr
    segs, i, n = [], 0, len(act)
    while i < n:
        if act[i]:
            j = i
            while j < n and act[j]:
                j += 1
            segs.append([i / 100, j / 100])
            i = j
        else:
            i += 1
    if not segs:
        return []
    mg = [segs[0]]
    for s in segs[1:]:
        if s[0] - mg[-1][1] < merge_gap:
            mg[-1][1] = s[1]
        else:
            mg.append(s)
    return [s for s in mg if s[1] - s[0] > min_len]


def noise_floor(db: np.ndarray) -> dict:
    return {f"p{p}": round(float(np.percentile(db, p)), 1) for p in (5, 25, 50, 75, 90, 99)}
