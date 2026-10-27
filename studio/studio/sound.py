"""Sound design: a small synthesized SFX library (original sounds, no licensing questions)
and an ambient music-bed generator, plus level matching against the voice."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from numpy.fft import irfft, rfft, rfftfreq

SR = 48000
LIB = Path(__file__).resolve().parent.parent / "assets" / "sfx"


def _bp(x, fc, bw):
    X = rfft(x)
    X *= np.exp(-((rfftfreq(len(x), 1 / SR) - fc) / bw) ** 2)
    return irfft(X, len(x))


def _lp(x, fc):
    X = rfft(x)
    X /= np.sqrt(1 + (rfftfreq(len(x), 1 / SR) / fc) ** 4)
    return irfft(X, len(x))


def _norm(y, peak_db=-12):
    return y / (np.abs(y).max() + 1e-9) * 10 ** (peak_db / 20)


def write(path, y, stereo=True):
    y = np.clip(y, -1, 1)
    data = np.stack([y, y], 1) if stereo and y.ndim == 1 else y
    o = wave.open(str(path), "wb")
    o.setnchannels(2 if stereo else 1), o.setsampwidth(2), o.setframerate(SR)
    o.writeframes((data * 32767).astype(np.int16).tobytes())
    o.close()
    return str(path)


def build_library():
    """whoosh / whoosh_soft / tick / sub_hit / riser_1s  ->  studio/assets/sfx/*.wav"""
    LIB.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)

    def whoosh(d):
        n = int(d * SR)
        k = np.linspace(0, 1, n)
        return _bp(rng.standard_normal(n), 2200, 1800) * np.sin(np.pi * k ** 0.7) ** 3

    def tick():
        n = int(.06 * SR)
        t = np.arange(n) / SR
        return np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 90) + _bp(rng.standard_normal(n), 5000, 2000) * np.exp(-t * 120) * .4

    def sub():
        n = int(1.2 * SR)
        t = np.arange(n) / SR
        return np.sin(2 * np.pi * (38 + 40 * np.exp(-t * 12)) * t) * np.exp(-t * 3.2)

    def riser(d=1.0):
        n = int(d * SR)
        t = np.arange(n) / SR
        k = t / d
        return _bp(rng.standard_normal(n), 1500, 1200) * k ** 2.5 + np.sin(2 * np.pi * (200 + 900 * k ** 2) * t) * k ** 3 * .3

    out = {"whoosh": write(LIB / "whoosh.wav", _norm(whoosh(0.6))),
           "whoosh_soft": write(LIB / "whoosh_soft.wav", _norm(whoosh(0.5), -18)),
           "tick": write(LIB / "tick.wav", _norm(tick(), -22)),
           "sub_hit": write(LIB / "sub_hit.wav", _norm(sub(), -8)),
           "riser_1s": write(LIB / "riser_1s.wav", _norm(riser(), -14))}
    return out


# offsets: where the sound's "moment" sits inside the file (place = event time - offset)
SFX_OFFSET = {"whoosh": 0.32, "whoosh_soft": 0.30, "tick": 0.0, "sub_hit": 0.0, "riser_1s": 1.0}


def sfx_path(name):
    p = LIB / f"{name}.wav"
    if not p.exists():
        build_library()
    return str(p)


def music_bed(seconds, out, bpm=100, fade_in=0.8, fade_out=2.2, kick_from=1.6, hats_from=9.5):
    """Dark ambient pad + soft pulse + light kick/hats (Am-F-C-G), normalized to -20 dBFS RMS."""
    rng = np.random.default_rng(11)
    N = int(seconds * SR)
    t = np.arange(N) / SR
    beat, bar = 60 / bpm, 4 * 60 / bpm
    mf = lambda n: 440 * 2 ** ((n - 69) / 12)
    chords = [[45, 52, 57, 60, 64], [41, 48, 53, 57, 64], [48, 55, 60, 64, 67], [43, 50, 55, 59, 62]]
    pad = np.zeros(N)
    for b in range(int(seconds / bar) + 1):
        s = int(b * bar * SR)
        n = min(int(bar * SR * 1.25), N - s)
        if n <= 0:
            break
        tt = np.arange(n) / SR
        env = np.minimum(1, tt / 0.6) * np.minimum(1, (n / SR - tt) / 0.8)
        pad[s:s + n] += sum(np.sin(2 * np.pi * mf(m) * tt * (1 + d)) + .5 * np.sin(2 * np.pi * mf(m) * 2 * tt * (1 - d))
                            for m in chords[b % 4] for d in (-.002, .002)) * env
    pulse, kick, hat = np.zeros(N), np.zeros(N), np.zeros(N)
    for k in range(int(seconds / (beat / 2))):
        s, n = int(k * beat / 2 * SR), int(.18 * SR)
        if s + n >= N:
            break
        tt = np.arange(n) / SR
        pulse[s:s + n] += np.sin(2 * np.pi * mf(chords[int(k * beat / 2 / bar) % 4][0] + 12) * tt) * np.exp(-tt * 18) * (1 if k % 2 == 0 else .6)
        if k % 2 == 0:
            n2 = int(.3 * SR)
            if s + n2 < N:
                tt2 = np.arange(n2) / SR
                kick[s:s + n2] += np.sin(2 * np.pi * (45 + 60 * np.exp(-tt2 * 30)) * tt2) * np.exp(-tt2 * 10)
        else:
            n3 = int(.04 * SR)
            hat[s:s + n3] += _bp(rng.standard_normal(n3), 9000, 3000) * np.exp(-np.arange(n3) / SR * 120)
    n_ = lambda y: y / (np.abs(y).max() + 1e-9)
    mus = n_(_lp(pad, 1400)) * .55 + n_(_lp(pulse, 2500)) * .28 + n_(kick) * .35 * (t > kick_from) + n_(hat) * .08 * (t > hats_from)
    fade = np.ones(N)
    fade[:int(fade_in * SR)] = np.linspace(0, 1, int(fade_in * SR))
    fo = int(fade_out * SR)
    fade[-fo:] = np.linspace(1, 0, fo) ** 1.5
    mus *= fade
    mus *= 10 ** (-20 / 20) / (np.sqrt(np.mean(mus ** 2)) + 1e-9)
    return write(out, mus)


def rms_db(path, t0=None, t1=None):
    w = wave.open(str(path))
    sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels()).mean(1) / 32768
    if t0 is not None:
        a = a[int(t0 * sr):int(t1 * sr)]
    a = a[np.abs(a) > 10 ** (-50 / 20)]  # ignore silence so pauses don't skew the voice level
    return float(20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-12))


def gain_under_voice(voice_wav, bed_wav, db_under=-18, t0=None, t1=None):
    """Clip gain (dB) that puts the bed ``db_under`` below the voice."""
    return round(rms_db(voice_wav, t0, t1) + db_under - rms_db(bed_wav), 1)
