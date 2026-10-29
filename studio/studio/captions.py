"""Caption templates: viral / clean subtitle styles applied to the open project as native, editable
text clips on a "Captions" video track.

The words come from the recording's verbatim transcript (word times in the source), mapped onto the
timeline through the project's own clips of that recording, so captions follow the cut as it is now
(including the user's manual edits). Each caption group is one text clip (or one clip per word when
the template highlights the spoken word); every word stays editable text in VibezCut.

Templates are JSON files in studio/assets/caption_templates/ (see that folder's README).
"""
from __future__ import annotations

import json
import os
import re
import struct
from functools import lru_cache
from pathlib import Path

from . import fc, transcribe

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "assets" / "caption_templates"
TRACK_NAME = "Captions"
JOIN_PREFIX = (".", ",", "%", "-", "'", "\u2019", "!", "?", ":", ";")


# ----------------------------------------------------------------------------- templates
def template_names() -> list[str]:
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.json"))


def load_template(name: str) -> dict:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    for p in TEMPLATES_DIR.glob("*.json"):
        t = json.loads(p.read_text(encoding="utf-8"))
        if p.stem.lower() == key or t.get("name", "").lower() == name.strip().lower():
            t.setdefault("id", p.stem)
            return t
    raise fc.FilmCraftError(f"no caption template '{name}'. Templates: {', '.join(template_names())}")


def list_templates() -> list[dict]:
    out = []
    for n in template_names():
        t = load_template(n)
        out.append({"id": n, "name": t.get("name", n), "for": t.get("for", ""), "description": t.get("description", ""),
                    "font": f"{t['font']} {t.get('style', 'Bold')}"})
    return out


# ----------------------------------------------------------------------------- fonts (measuring)
def _font_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("VIBEZCUT_FONTS_DIR"):
        dirs.append(Path(os.environ["VIBEZCUT_FONTS_DIR"]))
    here = Path(__file__).resolve()
    dirs += [here.parents[2] / "fonts", here.parents[3] / "fonts"]          # install: <app>/fonts
    dirs.append(here.parents[2] / "assets" / "fonts")                         # repo checkout: Inter
    win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    dirs.append(win)
    if os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
    return [d for d in dirs if d.is_dir()]


def _names(path: Path):
    """(typographic family, style) from a TTF/OTF name table (ids 16/17, else 1/2)."""
    try:
        b = path.read_bytes()
        if b[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            return None
        n = struct.unpack(">H", b[4:6])[0]
        tables = {}
        for i in range(n):
            tag, _, off, ln = struct.unpack(">4sIII", b[12 + i * 16:28 + i * 16])
            tables[tag] = (off, ln)
        off, ln = tables[b"name"]
        t = b[off:off + ln]
        cnt, store = struct.unpack(">HH", t[2:6])
        got = {}
        for i in range(cnt):
            p, e, _l, nid, L, o = struct.unpack(">HHHHHH", t[6 + i * 12:18 + i * 12])
            if p == 3 and e in (1, 10) and nid in (1, 2, 16, 17) and nid not in got:
                got[nid] = t[store + o:store + o + L].decode("utf-16-be", "ignore")
        return got.get(16, got.get(1)), got.get(17, got.get(2))
    except (OSError, KeyError, struct.error):
        return None


@lru_cache(maxsize=1)
def _font_index() -> dict:
    idx = {}
    for d in _font_dirs():
        for p in list(d.rglob("*.ttf")) + list(d.rglob("*.otf")):
            nm = _names(p)
            if nm and nm[0]:
                idx.setdefault((nm[0].lower(), (nm[1] or "Regular").lower()), p)
    return idx


@lru_cache(maxsize=64)
def _pil_font(family: str, style: str, size: int):
    from PIL import ImageFont
    idx = _font_index()
    p = idx.get((family.lower(), style.lower())) or idx.get((family.lower(), "regular")) \
        or next((v for (f, _s), v in idx.items() if f == family.lower()), None) or idx.get(("inter", "bold"))
    if p is None:
        return ImageFont.load_default()
    return ImageFont.truetype(str(p), size)


def text_width(text: str, family: str, style: str, size: float, tracking: float = 0) -> float:
    f = _pil_font(family, style, max(1, int(round(size))))
    try:
        w = f.getlength(text)
    except AttributeError:
        w = f.getsize(text)[0]
    return w + tracking / 1000.0 * size * max(0, len(text) - 1)


# ----------------------------------------------------------------------------- words on the timeline
def edit_words(c, video: str, corrections: dict | None = None) -> list[dict]:
    """The recording's words that are in the cut, at their timeline times: [{w, t0, t1}]."""
    seq = c.sequence()
    T = fc.TICKS
    name = Path(video).name.lower()
    spans = []  # (timeline start s, source in s, duration s)
    for tr in seq.get("video", []):
        for it in tr.get("items", []):
            if (it.get("name") or "").lower() == name:
                spans.append((it["start"] / T, it.get("sourceIn", 0) / T, it.get("duration", 0) / T))
        if spans:
            break  # the first video track that holds the recording (the camera)
    if not spans:
        raise fc.FilmCraftError(f"no clips of {Path(video).name} on the timeline of the open project")
    raw = [w for ch in transcribe.chunks(video) for w in ch["w"] if w[0].strip()]
    words = []
    for w in raw:
        txt, s0, s1 = w[0].strip(), float(w[1]), float(w[2])
        mid = (s0 + s1) / 2
        for ts, si, du in spans:
            if si <= mid < si + du:
                words.append({"w": txt, "t0": ts + max(0.0, s0 - si), "t1": ts + min(du, s1 - si)})
                break
    words.sort(key=lambda x: x["t0"])
    # tokens the recogniser splits off ($0 + .5, pay + -as + -you + -go, don + 't)
    merged = []
    for w in words:
        if merged and w["w"].startswith(JOIN_PREFIX) and w["t0"] - merged[-1]["t1"] < 0.25:
            merged[-1]["w"] += w["w"]
            merged[-1]["t1"] = max(merged[-1]["t1"], w["t1"])
        else:
            merged.append(dict(w))
    fixes = {k.lower(): v for k, v in (corrections or {}).items()}
    for w in merged:
        core = re.sub(r"^[^\w$#@]+|[^\w%]+$", "", w["w"])
        if core.lower() in fixes:
            w["w"] = w["w"].replace(core, fixes[core.lower()])
    return merged


def group_words(words: list[dict], t: dict) -> list[list[dict]]:
    max_w, max_c = t.get("max_words", 3), t.get("max_chars", 18)
    gap, punct = t.get("break_gap", 0.45), t.get("break_on_punct", True)
    groups, cur = [], []
    for w in words:
        if cur:
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if len(cur) >= max_w or chars > max_c or w["t0"] - cur[-1]["t1"] > gap or (punct and re.search(r"[.!?]$", cur[-1]["w"])):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def _fmt(word: str, t: dict) -> str:
    if t.get("strip_punct", True):
        word = re.sub(r"(?<![\d$])[.,!?;:]+$|^[\"“”]+|[\"“”]+$", "", word)
    case = t.get("case", "none")
    return word.upper() if case == "upper" else word.lower() if case == "lower" else word


# ----------------------------------------------------------------------------- building
class _Builder:
    def __init__(self, c, seq, t):
        self.c, self.t = c, t
        st = seq.get("settings", {})
        self.W, self.H = st.get("width", 1920), st.get("height", 1080)
        fr = st.get("frame_rate", {"num": 30, "den": 1})
        self.fps = fr["num"] / fr["den"]
        self.ft = fc.TICKS * fr["den"] / fr["num"]
        self.k = min(self.W, self.H) / 1080.0
        self.n = 0

    def tk(self, s):
        return int(round(round(s * self.fps) * self.ft))

    def span(self, t0, t1):
        """Start tick and length in seconds of a whole number of frames, so clips that meet
        exactly never overlap on the track."""
        f0, f1 = round(t0 * self.fps), round(t1 * self.fps)
        return int(round(f0 * self.ft)), max(1, f1 - f0) / self.fps

    def run(self, cmd, p):
        self.n += 1
        return self.c.run(cmd, p)

    def key(self, clip, effect, param, value, s):
        self.run("effects.setParam", {"clip": clip, "effect": effect, "param": param, "value": value, "time": self.tk(s), "keyframe": True})

    def style_props(self, color):
        t, k = self.t, self.k
        p = {"fill_color": color, "tracking": t.get("tracking", 0), "align": "left"}
        if t.get("stroke"):
            p.update(stroke=True, stroke_color=t["stroke"]["color"], stroke_width=t["stroke"]["width"] * k)
        if t.get("shadow"):
            s = t["shadow"]
            p.update(shadow=True, shadow_color=s.get("color", "#000000"), shadow_opacity=s.get("opacity", 60),
                     shadow_distance=s.get("distance", 6) * k, shadow_blur=s.get("blur", 12) * k, shadow_angle=s.get("angle", 135))
        else:
            p["shadow"] = False
        return p

    def layout(self, words: list[str]):
        """Lines of (text, font size, x left, baseline y, [word (start, end) char ranges])."""
        t, k = self.t, self.k
        fam, sty, trk = t["font"], t.get("style", "Bold"), t.get("tracking", 0)
        size = t["size"] * k
        per_line = t.get("words_per_line", 99)
        max_w = self.W * t.get("max_width", 0.86)
        lines, cur = [], []
        first = t.get("first_line_words", 0)
        for w in words:
            trial = " ".join(cur + [w])
            cap = first if first and not lines else per_line
            if cur and (len(cur) >= cap or text_width(trial, fam, sty, size, trk) > max_w):
                lines.append(cur)
                cur = []
            cur.append(w)
        if cur:
            lines.append(cur)
        out = []
        step = size * t.get("line_height", 1.05)
        total = step * len(lines)
        cy = self.H * t.get("y", 0.72)
        top = cy - total / 2
        for i, ws in enumerate(lines):
            text = " ".join(ws)
            sz = size
            wid = text_width(text, fam, sty, sz, trk)
            if wid > max_w:  # one long word: shrink to fit
                sz = size * max_w / wid
                wid = max_w
            small = self.small_last_applies(ws, i == len(lines) - 1)
            if small:  # the raised last word is narrower than at full size
                head = " ".join(ws[:-1])
                wid = text_width(head, fam, sty, sz, trk) + sz * 0.06 + text_width(ws[-1], fam, sty, sz * t.get("small_scale", 0.42), 0)
            x = self.W / 2 - wid / 2 if t.get("align", "center") == "center" else self.W * t.get("x", 0.08)
            base = top + i * step + step * 0.80
            ranges, pos = [], 0
            for w in ws:
                ranges.append((pos, pos + len(w)))
                pos += len(w) + 1
            out.append({"text": text, "size": sz, "x": x, "y": base, "w": wid, "ranges": ranges, "small": small})
        return out, cy

    def small_last_applies(self, line_words, is_last):
        """The small raised last word (editorial style): only for a short word after others."""
        return bool(self.t.get("small_last_word") and is_last and len(line_words) > 1
                    and len(line_words[-1]) <= self.t.get("small_max_chars", 7))

    def clip_for(self, t0, t1, lines, active=None, small_last=False):
        """One graphic clip: a highlight box (optional), then one text layer per line."""
        t = self.t
        base, hi = t.get("color", "#FFFFFF"), t.get("highlight_color", "#FFE14D")
        track = self.track
        fam, sty = t["font"], t.get("style", "Bold")
        clip, layer = None, 0
        box = t.get("highlight") == "box" and active is not None
        if box:
            li, wi = active
            L = lines[li]
            a, b = L["ranges"][wi]
            x0 = L["x"] + text_width(L["text"][:a], fam, sty, L["size"], t.get("tracking", 0))
            ww = text_width(L["text"][a:b], fam, sty, L["size"], t.get("tracking", 0))
            pad = L["size"] * 0.18
            r = self.run("graphics.newRectangle", {"position": [x0 + ww / 2, L["y"] - L["size"] * 0.34], "size": [ww + 2 * pad, L["size"] * 1.08],
                                                   "seconds": self.span(t0, t1)[1], "track": track, "time": self.span(t0, t1)[0]})
            clip = r["clip"]
            self.run("graphics.set", {"clip": clip, "layer": 0, "props": {"fill_color": t.get("box_color", "#22C3C6"), "corner_radius": L["size"] * 0.22}})
            layer = 1
        for li, L in enumerate(lines):
            text = L["text"]
            size = L["size"]
            if small_last and L.get("small"):
                a, _ = L["ranges"][-1]
                text = L["text"][:a].rstrip()
            p = {"text": text, "position": [L["x"], L["y"]], "size": size, "font": fam, "fontStyle": sty}
            if clip is None:
                at, secs = self.span(t0, t1)
                r = self.run("graphics.newText", {**p, "seconds": secs, "track": track, "time": at})
                clip = r["clip"]
            else:
                self.run("graphics.newText", {**p, "clip": clip})
            self.run("graphics.set", {"clip": clip, "layer": layer, "props": self.style_props(base)})
            hl = t.get("highlight")
            if hl in ("word", "box") and active is not None and active[0] == li:
                a, b = L["ranges"][active[1]]
                col = t.get("box_text_color", base) if hl == "box" else hi
                self.run("graphics.setCharStyle", {"clip": clip, "layer": layer, "start": a, "end": b, "style": {"color": col}})
            if t.get("highlight") == "last_line" and li == len(lines) - 1:
                self.run("graphics.setCharStyle", {"clip": clip, "layer": layer, "start": 0, "end": len(text), "style": {"color": hi}})
            for kw in self.keywords:
                for m in re.finditer(re.escape(kw), text, flags=re.IGNORECASE):
                    self.run("graphics.setCharStyle", {"clip": clip, "layer": layer, "start": m.start(), "end": m.end(), "style": {"color": t.get("keyword_color", hi)}})
            layer += 1
            if small_last and L.get("small"):
                a, b = L["ranges"][-1]
                small = L["text"][a:b]
                ss = size * t.get("small_scale", 0.42)
                head = L["text"][:a].rstrip()
                x = L["x"] + text_width(head, fam, sty, size, t.get("tracking", 0)) + size * 0.06
                self.run("graphics.newText", {"clip": clip, "text": small, "position": [x, L["y"] - size * 0.30], "size": ss, "font": fam, "fontStyle": sty})
                self.run("graphics.set", {"clip": clip, "layer": layer, "props": {**self.style_props(base), "tracking": 0}})
                layer += 1
        return clip

    def animate(self, clip, t0, t1, cy, first=True, last=True):
        a = self.t.get("animation", "none")
        cx = self.W / 2
        if first and a in ("pop", "pop_rotate", "scale_fade"):
            self.run("effects.setParam", {"clip": clip, "effect": "motion", "param": "anchor", "value": [cx, cy]})
            self.run("effects.setParam", {"clip": clip, "effect": "motion", "param": "position", "value": [cx, cy]})
            if a == "scale_fade":
                self.key(clip, "motion", "scale", 92, t0)
                self.key(clip, "motion", "scale", 100, t0 + 0.18)
            else:
                self.key(clip, "motion", "scale", 70, t0)
                self.key(clip, "motion", "scale", 108, t0 + 0.08)
                self.key(clip, "motion", "scale", 100, t0 + 0.15)
            if a == "pop_rotate":
                self.key(clip, "motion", "rotation", -4, t0)
                self.key(clip, "motion", "rotation", 0, t0 + 0.15)
        if first and a in ("fade", "slide", "scale_fade"):
            self.key(clip, "opacity", "opacity", 0, t0)
            self.key(clip, "opacity", "opacity", 100, t0 + 0.12)
        if first and a == "slide":
            self.key(clip, "motion", "position", [cx, self.H / 2 + 26 * self.k], t0)
            self.key(clip, "motion", "position", [cx, self.H / 2], t0 + 0.14)
        if last and a in ("fade", "scale_fade") and t1 - t0 > 0.3:
            self.key(clip, "opacity", "opacity", 100, t1 - 0.1)
            self.key(clip, "opacity", "opacity", 0, t1 - 1 / self.fps)


def captions_track(c, seq, replace: bool) -> int:
    """Index of the "Captions" video track (made on top if missing); its clips cleared when replacing."""
    tracks = seq.get("video", [])
    for i, tr in enumerate(tracks):
        if (tr.get("name") or "") == TRACK_NAME:
            ids = [it["clip"] for it in tr.get("items", [])]
            if ids and replace:
                c.run("edit.clear", {"clips": ids})
            return i
    c.run("sequence.addTracks", {"video": 1, "audio": 0, "videoAfter": "last"})
    n = len(c.sequence().get("video", []))
    c.run("timeline.setTrack", {"track": f"V{n}", "name": TRACK_NAME})
    return n - 1


def apply(c, video: str, template: str, corrections: dict | None = None, keywords: list | None = None,
          replace: bool = True, start: float | None = None, end: float | None = None) -> dict:
    t = load_template(template)
    words = edit_words(c, video, corrections)
    if start is not None or end is not None:
        lo, hi = start or 0.0, end if end is not None else 1e12
        words = [w for w in words if lo <= w["t0"] < hi]
    if not words:
        raise fc.FilmCraftError("no words to caption in that range")
    seq = c.sequence()
    b = _Builder(c, seq, t)
    b.keywords = [k for k in (keywords or []) if k]
    b.track = captions_track(c, seq, replace)
    groups = group_words(words, t)
    lead, tail, fill = t.get("lead", 0.04), t.get("tail", 0.12), t.get("fill_gap", 0.35)
    clips = 0
    fps = b.fps
    prev_end = 0  # frame where the last caption clip ends: clips never overlap on the track
    for gi, g in enumerate(groups):
      try:
        g0 = max(0.0, g[0]["t0"] - lead)
        g1 = g[-1]["t1"] + tail
        nxt = groups[gi + 1][0]["t0"] - lead if gi + 1 < len(groups) else None
        if nxt is not None:
            g1 = nxt if nxt - g1 < fill else min(g1, nxt)
        f0, f1 = max(prev_end, round(g0 * fps)), round(g1 * fps)
        if f1 - f0 < 2:
            continue
        texts = [_fmt(w["w"], t) for w in g]
        lines, cy = b.layout(texts)
        # word index -> (line, word in line)
        where = [(li, wi) for li, L in enumerate(lines) for wi in range(len(L["ranges"]))]
        small_last = t.get("small_last_word", False)
        mode = t.get("highlight", "none")
        steps = mode in ("word", "box") or t.get("highlight_mode") == "reveal"
        if steps:
            # one clip per word: frame boundaries that only move forward
            bounds = [f0]
            for w in g[1:]:
                bounds.append(min(f1, max(bounds[-1] + 1, round(w["t0"] * fps))))
            bounds.append(f1)
            for wi in range(len(g)):
                a, z = bounds[wi], bounds[wi + 1]
                if z - a < 1:
                    continue
                s0, s1 = a / fps, z / fps
                last = wi == len(g) - 1 or bounds[wi + 1] >= f1
                if mode in ("word", "box"):
                    clip = b.clip_for(s0, s1, lines, active=where[wi] if wi < len(where) else None, small_last=small_last)
                    b.animate(clip, s0, s1, cy, first=wi == 0, last=last)
                else:
                    shown = [dict(L) for L in lines[:where[wi][0] + 1]]
                    clip = b.clip_for(s0, s1, shown, small_last=small_last)
                    b.animate(clip, s0, s1, cy, first=True, last=last)
                clips += 1
        else:
            clip = b.clip_for(f0 / fps, f1 / fps, lines, small_last=small_last)
            b.animate(clip, f0 / fps, f1 / fps, cy)
            clips += 1
        prev_end = f1
      except fc.FilmCraftError as e:
        raise fc.FilmCraftError(f"caption {gi + 1} ('{' '.join(w['w'] for w in g)}' at {g[0]['t0']:.2f}s): {e}") from e
    return {"template": t.get("name", template), "words": len(words), "groups": len(groups), "clips": clips,
            "track": TRACK_NAME, "commands": b.n}
