"""Turn resolved units into timeline pieces, render the edited dialogue, and verify it.

pieces.json: [[src_start, src_end, unit], ...] on the 1/fps grid, in timeline order.
Pauses longer than 0.45 s inside a unit are tightened; adjacent units that overlap are split
halfway between the last word of one and the first word of the next.
"""
from __future__ import annotations

import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

from . import audio, config, takes, transcribe


def build_pieces(video, removals=(), fps=None):
    fps = fps or config.settings()["fps"]
    wd = config.workdir(video)
    res = json.loads((wd / "resolved.json").read_text(encoding="utf-8"))
    units = [res[k] for k in sorted(res, key=int) if res[k].get("S") is not None]
    db = np.load(audio.extract(video)["db"])
    blobs = audio.activity(db, -55, 0.12, 0.0)
    for a, b in zip(units, units[1:]):
        if b["S"] < a["E"]:
            mid = (a.get("last", a["E"]) + b.get("onset", b["S"])) / 2
            a["E"], b["S"] = min(a["E"], mid), max(b["S"], mid)
    pieces = []
    for u in units:
        s, e = u["S"], u["E"]
        inside = [p for p in blobs if p[1] > s and p[0] < e]
        cur = s
        for a, b in zip(inside, inside[1:]):
            if b[0] - a[1] > 0.45:
                ce, cs = a[1] + 0.13, b[0] - 0.09
                if ce > cur and cs > ce:
                    pieces.append([cur, ce, u["i"]])
                    cur = cs
        pieces.append([cur, e, u["i"]])
    out = []
    for s, e, i in pieces:
        for a, b in removals:  # explicit stutter removals inside a unit
            if s < a and e > b:
                out.append([s, a, i])
                s = b
        out.append([s, e, i])
    q = lambda t: round(t * fps) / fps
    out = [[q(s), q(e), i] for s, e, i in out if q(e) - q(s) >= 1 / fps]
    (wd / "pieces.json").write_text(json.dumps(out), encoding="utf-8")
    return {"pieces": len(out), "duration": round(sum(e - s for s, e, _ in out), 2), "path": str(wd / "pieces.json")}


def render_dialogue(video):
    """edit_audio.wav: the cut dialogue at 48 kHz with 12/18 ms fades on every edit."""
    wd = config.workdir(video)
    pieces = json.loads((wd / "pieces.json").read_text(encoding="utf-8"))
    w = wave.open(audio.extract(video)["audio48k"])
    sr = w.getframerate()
    A = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, 2).astype(np.float32)
    fi, fo = int(0.012 * sr), int(0.018 * sr)
    out = []
    for s, e, _ in pieces:
        seg = A[int(round(s * sr)):int(round(e * sr))].copy()
        seg[:fi] *= np.linspace(0, 1, fi)[:, None]
        seg[-fo:] *= np.linspace(1, 0, fo)[:, None]
        out.append(seg)
    Y = np.concatenate(out)
    p = wd / "edit_audio.wav"
    o = wave.open(str(p), "wb")
    o.setnchannels(2), o.setsampwidth(2), o.setframerate(sr)
    o.writeframes(np.clip(Y, -32768, 32767).astype(np.int16).tobytes())
    o.close()
    return str(p)


def verify(video):
    """Re-transcribe the whole edited dialogue in long windows (stutters are not merged there)
    and list immediate repeats. Writes verify.txt with timeline times."""
    wd = config.workdir(video)
    p = render_dialogue(video)
    a16 = wd / "edit16k.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p, "-ar", "16000", "-ac", "1", str(a16)], check=True)
    a = audio.load16(a16)
    segs, _ = transcribe.model().transcribe(a, language="en", word_timestamps=True, vad_filter=False,
                                            condition_on_previous_text=False, beam_size=5, temperature=0,
                                            initial_prompt=transcribe.VERBATIM)
    lines, words = [], []
    for s in segs:
        lines.append(f"{s.start:7.1f}  {s.text.strip()}")
        words += [(re.sub(r"[^a-z0-9']", "", w.word.lower()), w.start) for w in s.words]
    words = [w for w in words if w[0]]
    issues = []
    for i in range(len(words) - 1):
        if words[i][0] == words[i + 1][0] and words[i][0] not in takes.OKREP:
            issues.append(f"{words[i][1]:7.1f}  repeated word: " + " ".join(x[0] for x in words[max(0, i - 4):i + 6]))
    for i in range(len(words) - 3):
        if words[i][0] == words[i + 2][0] and words[i + 1][0] == words[i + 3][0]:
            issues.append(f"{words[i][1]:7.1f}  repeated pair: " + " ".join(x[0] for x in words[max(0, i - 3):i + 7]))
    for i in range(len(words) - 2):
        if words[i][0] == words[i + 2][0] and words[i][0] not in {"the", "a", "to", "and", "of", "in", "i", "is", "it", "you"}:
            issues.append(f"{words[i][1]:7.1f}  restart?: " + " ".join(x[0] for x in words[max(0, i - 3):i + 6]))
    (wd / "verify.txt").write_text("\n".join(lines) + "\n\nISSUES\n" + "\n".join(issues), encoding="utf-8")
    return {"duration": round(len(a) / 16000, 2), "issues": issues, "path": str(wd / "verify.txt")}
