"""Resolve chosen takes ("units") to frame-safe cut points.

A unit is one sentence/clause I picked from the transcript:
    {"text": "..." | ["variant", ...], "k1": first phrase, "k2": last phrase,
     "sw": [t0, t1]?  start search window (inner start: the last of several repeats),
     "ew": [t0, t1]?  end search window, "fixS": t?  forced start, "lenient": bool?}

For each unit:
 1. candidate cut points = deep quiet runs (< -62 dB) in the windows (fallback < -56 dB)
 2. every (start, end) candidate is transcribed with a verbatim prompt and judged:
    ratio vs intended text, first/last words present, no stutter at the edges
    -> latest passing start (skips earlier repeats), earliest passing end
 3. the end is trimmed to the earliest point that still passes, + margin
 4. MMS forced alignment (leading wildcard) gives the true onset of the first word and the
    end of the last; the start is moved to the quiet run just before that onset when the
    aligned start still passes the judge (never trusted blindly)
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import numpy as np

from . import audio, config, transcribe

SR = 16000
STARTPAD, ENDPAD = 0.08, 0.10
FILL = {"uh", "um", "uhh", "umm", "hmm", "mm", "ah", "er", "erm"}
OKREP = {"really", "very", "bye"}


# ----------------------------------------------------------------------------- text judging
def norm(t):
    t = t.lower().replace("-", " ").replace(".", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", t)).strip()


def tok(t):
    return norm(t).split()


def teq(a, b, r=0.85):
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= r


def teq_edge(a, b):
    if a == b:
        return True
    return min(len(a), len(b)) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.88


def stutter(tt, end=False):
    for k in (1, 2, 3, 4, 5):
        if len(tt) >= 2 * k:
            a, b = (tt[-k:], tt[-2 * k:-k]) if end else (tt[:k], tt[k:2 * k])
            if all(teq(x, y, 0.8) for x, y in zip(a, b)) and not (k == 1 and a[0] in OKREP):
                return True
    return False


def internal_dups(tt):
    out = []
    for k in (2, 3, 4):
        for i in range(len(tt) - 2 * k + 1):
            if all(teq(tt[i + j], tt[i + k + j], 0.8) for j in range(k)):
                out.append(" ".join(tt[i:i + k]))
    return out


def judge(texts, t, lenient=False):
    tt = tok(t)
    if not tt or tt[0] in FILL or tt[-1] in FILL:
        return 0.0
    if not lenient and (stutter(tt) or stutter(tt, end=True)):
        return 0.0
    best = 0.0
    for x in texts:
        xt = tok(x)
        r = difflib.SequenceMatcher(None, norm(x).replace(" ", ""), norm(t).replace(" ", "")).ratio()
        if not (teq_edge(xt[0], tt[0]) and teq_edge(xt[-1], tt[-1])):
            r = min(r, 0.5)
        n = min(3, len(xt), len(tt))
        if n >= 3 and sum(teq(xt[j], tt[j], 0.8) for j in range(n)) < 2:
            r = min(r, 0.5)
        if min(2, len(xt), len(tt)) >= 2 and not any(teq(xt[-j], tt[-j], 0.8) for j in (1, 2)):
            r = min(r, 0.5)
        best = max(best, r)
    return best


# ----------------------------------------------------------------------------- resolver
class Resolver:
    def __init__(self, video):
        # torch must load its cuDNN before ctranslate2 (faster-whisper) does, or the
        # forced aligner fails with "Could not load symbol cudnnGetLibConfig"
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
        self.video = video
        p = audio.extract(video)
        self.a = audio.load16(p["audio16k"])
        self.db = np.load(p["db"])
        self.ph = [(x["s"], x["e"]) for x in transcribe.phrases(video)]
        self.prompt = transcribe.prompt_for(video)
        self.deep = audio.runs(self.db, -62)
        self.shal = audio.runs(self.db, -56)
        self.cache = {}
        self._mms = None

    # transcription of a candidate segment
    def tx(self, S, E):
        key = (round(S, 3), round(E, 3))
        if key not in self.cache:
            self.cache[key] = transcribe.asr(self.a[int(S * SR):int(E * SR)], self.prompt)
        return self.cache[key]

    @staticmethod
    def _cands(R, w0, w1, kind):
        def f(a, b):
            if kind == "s":
                return (a + b) / 2 if b - a < STARTPAD + 0.02 else b - STARTPAD
            return (a + b) / 2 if b - a < ENDPAD + 0.02 else a + ENDPAD
        return sorted({round(f(a, b), 3) for a, b in R if w0 <= f(a, b) <= w1})

    def search(self, u):
        k1, k2 = u["k1"], u["k2"]
        s1, e1 = self.ph[k1]
        sw = u.get("sw") or (s1 - 0.4, max(s1 + 0.05, min(e1 - 0.5, s1 + 8)))
        ew = u.get("ew") or (self.ph[k2][1] - 0.05, self.ph[k2][1] + 0.7)
        texts, len_ = u["text"] if isinstance(u["text"], list) else [u["text"]], u.get("lenient", False)
        best, found = (-1, None, None, ""), None
        for R in (self.deep, self.shal):
            SC = [u["fixS"]] if u.get("fixS") else (self._cands(R, *sw, "s") or [round(s1 - 0.07, 3)])
            EC = self._cands(R, *ew, "e") or [round(self.ph[k2][1] + 0.1, 3)]
            for E in EC[:6]:
                passes = []
                for S in SC:
                    if E - S < 0.3:
                        continue
                    t = self.tx(S, E)
                    r = judge(texts, t, len_)
                    if r > best[0]:
                        best = (r, S, E, t)
                    if r >= 0.9:
                        passes.append((r, S, E, t))
                if passes:
                    found = max(passes, key=lambda p: p[1])
                    break
            if found:
                break
        r, S, E, t = found or best
        if S is None:
            return None
        Et = E
        if found:  # earliest end that still passes, plus margin
            e = max(self.ph[k2][1] - 0.05, S + 0.3)
            while e < E - 0.02:
                if judge(texts, self.tx(S, e), len_) >= 0.9:
                    Et = min(E, e + 0.10)
                    break
                e += 0.03
        return {"S": S, "E": Et, "E0": E, "r": round(r, 3), "ok": bool(found), "t": t}

    # forced alignment
    def align(self, R0, R1, text):
        import torch
        import torchaudio.functional as F
        from torchaudio.pipelines import MMS_FA as bundle
        if self._mms is None:
            self._mms = (bundle.get_model().to("cuda").eval(), bundle.get_dict())
        model, D = self._mms
        x = torch.from_numpy(self.a[int(R0 * SR):int(R1 * SR)]).to("cuda")[None]
        with torch.inference_mode():
            em, _ = model(x)
            em = torch.log_softmax(em, dim=-1)
        em = torch.cat([em, torch.zeros(1, em.size(1), 1, device="cuda")], dim=2)
        ws = words_for_align(text)
        toks, lens = [len(D)], []
        for w in ws:
            cs = [D[c] for c in w if c in D]
            lens.append(len(cs))
            toks += cs
        ali, sc = F.forced_align(em, torch.tensor([toks], dtype=torch.int32, device="cuda"), blank=0)
        spans = F.merge_tokens(ali[0], sc[0])
        ratio = (R1 - R0) / em.size(1)
        out, k = [], 1
        for w, L in zip(ws, lens):
            sp = spans[k:k + L]
            k += L
            if sp:
                out.append((w, R0 + sp[0].start * ratio, R0 + sp[-1].end * ratio))
        return out

    def start_cut_for(self, onset):
        best = None
        for a, b in self.deep:
            if onset - 0.5 <= b <= onset + 0.06 and (best is None or b > best[1]):
                best = (a, b)
        if best:
            a, b = best
            return (a + b) / 2 if b - a < 0.11 else b - 0.09
        return onset - 0.10

    def end_cut_for(self, t1):
        for a, b in self.deep:
            if t1 - 0.05 <= a <= t1 + 0.45:
                return (a + b) / 2 if b - a < 0.12 else a + 0.10
        return t1 + 0.18

    def resolve(self, u):
        res = self.search(u)
        if res is None:
            return {"ok": False, "error": "no candidate cut points"}
        texts = u["text"] if isinstance(u["text"], list) else [u["text"]]
        k1 = u["k1"]
        R0 = (u["fixS"] - 0.1) if u.get("fixS") else max(0.0, self.ph[k1][0] - 0.5)
        try:
            al = self.align(R0, res["E0"] + 0.1, res["t"])
        except Exception as e:  # alignment is a refinement; the judged cut stands without it
            al = []
            res["align_error"] = str(e)
        S, E = res["S"], res["E"]
        if al:
            onset, last = al[0][1], al[-1][2]
            Sa = self.start_cut_for(onset)
            if abs(Sa - S) > 0.02 and not u.get("fixS"):
                # trust the aligned start only if it also passes the judge
                if judge(texts, self.tx(Sa, res["E0"]), u.get("lenient", False)) >= 0.9:
                    S = Sa
            E = min(max(E, last + 0.10), last + 0.30)
            res.update(onset=onset, last=last)
        res.update(S=S, E=E)
        res["dups"] = internal_dups(tok(res["t"]))
        return res


def words_for_align(t):
    ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    TENS = "x x twenty thirty forty fifty sixty seventy eighty ninety".split()

    def num(n):
        if n < 20:
            return ONES[n]
        if n < 100:
            return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
        if n < 1000:
            return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + num(n % 100))
        return " ".join(ONES[int(c)] for c in str(n))
    t = t.lower().replace("-", " ")
    t = re.sub(r"(\d+)\.(\d+)", lambda m: num(int(m.group(1))) + " point " + " ".join(num(int(c)) for c in m.group(2)), t)
    t = re.sub(r"\d+", lambda m: num(int(m.group(0))), t)
    t = re.sub(r"[^a-z' ]", " ", t)
    return [w.strip("'") for w in t.split() if w.strip("'")]


def resolve_all(video, units_path=None, only=None, log=print):
    wd = config.workdir(video)
    units = json.loads(Path(units_path or wd / "units.json").read_text(encoding="utf-8"))
    out_p = wd / "resolved.json"
    prev = json.loads(out_p.read_text(encoding="utf-8")) if out_p.exists() else {}
    R = Resolver(video)
    for i, u in enumerate(units):
        if only is not None and i not in only:
            continue
        r = R.resolve(u)
        r["i"] = i
        prev[str(i)] = r
        flag = "OK " if r.get("ok") else "BAD"
        log(f"{flag} {i:3d} [{r.get('S', 0):8.2f}-{r.get('E', 0):8.2f}] {'DUP ' + str(r['dups']) if r.get('dups') else ''}| {r.get('t', '')[:110]}")
    out_p.write_text(json.dumps(prev, indent=1), encoding="utf-8")
    bad = [k for k, v in prev.items() if not v.get("ok")]
    return {"resolved": len(prev), "bad": bad, "path": str(out_p)}
