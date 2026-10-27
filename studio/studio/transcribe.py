"""Verbatim transcription for take selection.

Two passes over the raw recording:
* chunks  - speech separated by >=0.35 s pauses, word timestamps (good for reading the flow)
* phrases - finer units split at >=0.12 s gaps; every phrase is a safe cut boundary

A disfluency-style prompt keeps Whisper from silently merging repeated attempts
("so so I can, I can...") so stutters and restarts stay visible.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from . import audio, config

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
VERBATIM = ("Umm, so so I can just, like, like upload the the image, uh, so so you can, "
            "you can see it, it is, it is.")
SR = 16000
_model = None


def model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        s = config.settings()
        _model = WhisperModel(s["whisper_model"], device=s["device"], compute_type="float16" if s["device"] == "cuda" else "int8")
    return _model


def asr(x: np.ndarray, prompt: str = VERBATIM, words: bool = False, beam: int = 5):
    x = np.concatenate([np.zeros(int(0.25 * SR), np.float32), x, np.zeros(int(0.25 * SR), np.float32)])
    segs, _ = model().transcribe(x, language="en", beam_size=beam, temperature=0, condition_on_previous_text=False,
                                 vad_filter=False, no_speech_threshold=0.95, initial_prompt=prompt, word_timestamps=words)
    segs = list(segs)
    text = " ".join(s.text.strip() for s in segs)
    if not words:
        return text
    ws = [(w.word.strip(), w.start - 0.25, w.end - 0.25, w.probability) for s in segs for w in s.words]
    return text, ws


def run(video: str | Path, prompt_terms: str = "") -> dict:
    """Transcribe ``video``; writes chunks.json, phrases.json and transcript.txt in the workdir."""
    wd = config.workdir(video)
    paths = audio.extract(video)
    a = audio.load16(paths["audio16k"])
    db = np.load(paths["db"])
    prompt = VERBATIM + (" " + prompt_terms if prompt_terms else "")
    (wd / "prompt.txt").write_text(prompt, encoding="utf-8")  # reused by the take resolver

    cj = wd / "chunks.json"
    if not cj.exists():
        out = []
        for k, (s, e) in enumerate(audio.activity(db, -58, 0.35, 0.15)):
            s0, e0 = max(0, s - 0.15), min(len(a) / SR, e + 0.15)
            text, ws = asr(a[int(s0 * SR):int(e0 * SR)], prompt, words=True)
            out.append({"k": k, "s": s, "e": e, "t": text, "w": [[w, round(s0 + b, 2), round(s0 + c, 2), round(p, 2)] for w, b, c, p in ws]})
        cj.write_text(json.dumps(out), encoding="utf-8")

    pj = wd / "phrases.json"
    if not pj.exists():
        out = []
        for k, (s, e) in enumerate(audio.activity(db, -55, 0.12, 0.08)):
            s0, e0 = max(0, s - 0.06), min(len(a) / SR, e + 0.06)
            out.append({"k": k, "s": s, "e": e, "t": asr(a[int(s0 * SR):int(e0 * SR)], prompt)[:240]})
        pj.write_text(json.dumps(out), encoding="utf-8")

    phrases = json.loads(pj.read_text(encoding="utf-8"))
    lines = [f"{p['k']:5d} {p['s']:8.2f} {p['e']:8.2f}  {p['t']}" for p in phrases]
    (wd / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    return {"workdir": str(wd), "chunks": str(cj), "phrases": str(pj), "transcript": str(wd / "transcript.txt"),
            "n_phrases": len(phrases), "duration": round(len(a) / SR, 2), "noise": audio.noise_floor(db)}


def prompt_for(video):
    p = config.workdir(video) / "prompt.txt"
    return p.read_text(encoding="utf-8") if p.exists() else VERBATIM


def phrases(video):
    return json.loads((config.workdir(video) / "phrases.json").read_text(encoding="utf-8"))


def chunks(video):
    return json.loads((config.workdir(video) / "chunks.json").read_text(encoding="utf-8"))
