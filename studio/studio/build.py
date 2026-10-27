"""Build a native FilmCraft project from an edit description (edit.json).

edit.json (all times in timeline seconds unless noted):
{
  "name": "My Video - Edit v1",
  "video": "D:/raw/take.mp4",            # the recording (V1 + A1)
  "fps": 60, "width": 1920, "height": 1080,
  "pieces": "pieces.json",               # [[src_start, src_end, unit], ...]  (source seconds)
  "camera": [[t0, t1, z0, z1], ...],     # scale moves on V1 (1.0 = 100 %), eased out
  "audio":  [{"path": "music.wav", "track": "A2", "at": 0, "gainDb": 0}],
  "sfx":    [{"name": "whoosh", "at": 1.6, "gainDb": 0}],   # library: whoosh, whoosh_soft, tick, sub_hit, riser_1s
  "stills": [{"path": "bg.png", "track": "V2", "t0": 1.6, "t1": 4.2, "fadeIn": 0.25, "fadeOut": 0.2,
              "scale": [100, 104], "rise": 0}],
  "clips":  [{"path": "pass.mp4", "track": "V2", "at": 61.25}],
  "texts":  [{"track": 3, "t0": 1.5, "t1": 4.2, "text": "Stop fighting with", "x": 960, "y": 395,
              "size": 104, "align": "center", "color": "#F5F6F8", "accent": ["fighting"], "style": "Bold"}],
  "bars":   [{"track": 5, "t0": 4.35, "t1": 6.75, "x": 165, "y": 653, "w": 90, "h": 6}],
  "transcript": true                       # push the verbatim transcript into FilmCraft's Text panel
}
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config, fc, sound, style

TICKS = fc.TICKS


class Builder:
    def __init__(self, client, fps=60):
        self.c, self.fps = client, fps
        self.ft = TICKS // fps
        self.log = []

    def tk(self, s):
        return int(round(s * self.fps)) * self.ft

    def run(self, cmd, params):
        r = self.c.run(cmd, params)
        self.log.append((cmd, params, r))
        return r

    # ---- primitives (also used for live revisions)
    def key(self, clip, effect, param, value, t):
        return self.run("effects.setParam", {"clip": clip, "effect": effect, "param": param, "value": value,
                                             "time": self.tk(t), "keyframe": True})

    def fade(self, clip, t0, t1, fi=0.25, fo=0.2, rise=0, y=540, x=960):
        if fi:
            self.key(clip, "opacity", "opacity", 0, t0)
            self.key(clip, "opacity", "opacity", 100, t0 + fi)
        if fo:
            self.key(clip, "opacity", "opacity", 100, t1 - fo)
            self.key(clip, "opacity", "opacity", 0, t1 - 1 / self.fps)
        if rise:
            self.key(clip, "motion", "position", [x, y + rise], t0)
            self.key(clip, "motion", "position", [x, y], t0 + 0.45)

    def camera(self, v1, moves):
        """Eased scale moves: a few sampled keyframes per move approximate ease-out."""
        n = 0
        for t0, t1, z0, z1 in moves:
            for clip, a, b in v1:
                lo, hi = max(t0, a), min(t1, b - 1 / self.fps)
                if hi <= lo:
                    continue
                for f in ([0, 0.12, 0.3, 0.55, 1.0] if z0 != z1 else [0, 1.0]):
                    tt = lo + (hi - lo) * f
                    p = (tt - t0) / (t1 - t0)
                    self.key(clip, "motion", "scale", round((z0 + (z1 - z0) * (1 - (1 - p) ** 3)) * 100, 2), tt)
                    n += 1
        return n

    def text(self, spec):
        s = {**style.TEXT_DEFAULTS, **spec}
        r = self.run("graphics.newText", {"text": s["text"], "position": [s["x"], s["y"]], "size": s["size"],
                                          "font": s["font"], "fontStyle": s["style"], "seconds": s["t1"] - s["t0"],
                                          "track": s["track"], "time": self.tk(s["t0"])})
        clip = r["clip"]
        self.run("graphics.set", {"clip": clip, "layer": 0, "props": {"align": s["align"], "fill_color": s["color"], "shadow": s["shadow"]}})
        for a in s.get("accent", []):
            i = s["text"].find(a)
            if i >= 0:
                self.run("graphics.setCharStyle", {"clip": clip, "layer": 0, "start": i, "end": i + len(a), "style": {"color": s["accentColor"]}})
        self.fade(clip, s["t0"], s["t1"], s["fadeIn"], s["fadeOut"], rise=s["rise"])
        return clip

    def bar(self, spec):
        s = {**style.BAR_DEFAULTS, **spec}
        r = self.run("graphics.newRectangle", {"position": [s["x"], s["y"]], "size": [s["w"], s["h"]],
                                               "seconds": s["t1"] - s["t0"], "track": s["track"], "time": self.tk(s["t0"])})
        clip = r["clip"]
        self.run("graphics.set", {"clip": clip, "layer": 0, "props": {"fill_color": s["color"]}})
        self.fade(clip, s["t0"], s["t1"], 0.4, 0.22)
        return clip

    def still(self, item, spec):
        r = self.run("timeline.place", {"item": item, "track": spec["track"], "time": self.tk(spec["t0"]),
                                        "duration": self.tk(spec["t1"]) - self.tk(spec["t0"]), "audio": False})
        clip = r["clips"][0]
        if spec.get("scale"):
            self.key(clip, "motion", "scale", spec["scale"][0], spec["t0"])
            self.key(clip, "motion", "scale", spec["scale"][1], spec["t1"] - 1 / self.fps)
        self.fade(clip, spec["t0"], spec["t1"], spec.get("fadeIn", 0.25), spec.get("fadeOut", 0.2), spec.get("rise", 0))
        return clip


def build_project(edit_path, out_path=None, log=print):
    edit_path = Path(edit_path)
    E = json.loads(edit_path.read_text(encoding="utf-8"))
    base = edit_path.parent
    rel = lambda p: str((base / p).resolve()) if not Path(p).is_absolute() else p
    fps = E.get("fps", 60)
    out_path = out_path or E.get("out") or str(Path(E["video"]).with_name(E.get("name", "Edit") + ".fcproj"))
    c = fc.Headless()
    try:
        b = Builder(c, fps)
        b.run("file.newProject", {"name": E.get("name", "Edit")})
        imported = {}

        def item(p):
            p = rel(p)
            if p not in imported:
                imported[p] = b.run("file.import", {"paths": [p]})["items"][0]
            return imported[p]

        src = item(E["video"])
        tracks = E.get("tracks", {"video": 6, "audio": 3})
        b.run("file.newSequence", {"name": E.get("name", "Edit"), "width": E.get("width", 1920), "height": E.get("height", 1080),
                                   "fps": fps, "sampleRate": 48000, "video": tracks["video"], "audio": tracks["audio"]})
        pieces = json.loads(Path(rel(E.get("pieces", "pieces.json"))).read_text(encoding="utf-8"))
        pos, v1 = 0, []
        for s, e, _ in pieces:
            nf = int(round((e - s) * fps))
            r = b.run("timeline.place", {"item": src, "track": "V1", "audioTrack": "A1", "time": pos * b.ft,
                                         "sourceIn": b.tk(s), "duration": nf * b.ft})
            v1.append((r["clips"][0], pos / fps, (pos + nf) / fps))
            pos += nf
        log(f"cut: {len(v1)} clips, {pos / fps:.2f} s")
        if E.get("camera"):
            log(f"camera keyframes: {b.camera(v1, E['camera'])}")
        # name tracks; beds that span cuts must not block ripple edits of the dialogue
        names = {"V1": "Camera", "V2": "Backgrounds", "V3": "Artwork", "V4": "Titles 1", "V5": "Titles 2",
                 "V6": "Accents", "A1": "Voice", "A2": "Music", "A3": "SFX"}
        for tr, nm in names.items():
            try:
                b.run("timeline.setTrack", {"track": tr, "name": nm, **({"syncLock": False} if tr == "A2" else {})})
            except fc.FilmCraftError:
                pass
        for a in E.get("audio", []):
            r = b.run("timeline.place", {"item": item(a["path"]), "track": a["track"], "time": b.tk(a.get("at", 0)), "video": False})
            if a.get("gainDb"):
                b.run("clip.audioGain", {"clips": r["clips"], "mode": "set", "db": a["gainDb"]})
        for fx in E.get("sfx", []):  # individual sound effects from the library
            at = max(0.0, fx["at"] - sound.SFX_OFFSET.get(fx["name"], 0))
            r = b.run("timeline.place", {"item": item(sound.sfx_path(fx["name"])), "track": fx.get("track", "A3"),
                                         "time": b.tk(at), "video": False})
            if fx.get("gainDb"):
                b.run("clip.audioGain", {"clips": r["clips"], "mode": "set", "db": fx["gainDb"]})
        for s in E.get("stills", []):
            b.still(item(s["path"]), s)
        for cl in E.get("clips", []):
            b.run("timeline.place", {"item": item(cl["path"]), "track": cl["track"], "time": b.tk(cl["at"]), "audio": cl.get("audio", False)})
        for t in E.get("texts", []):
            b.text(t)
        for bar in E.get("bars", []):
            b.bar(bar)
        if E.get("transcript", True):
            push_transcript(b, src, E["video"])
        r = b.run("file.saveAs", {"path": out_path})
        errors = [x for x in b.log if isinstance(x[2], str) and "error" in x[2].lower()]
        log(f"saved {out_path} ({len(b.log)} commands)")
        return {"project": out_path, "commands": len(b.log), "clips": len(v1), "duration": round(pos / fps, 2), "errors": errors[:10]}
    finally:
        c.close()


def push_transcript(b, item, video):
    """Our verbatim transcript (word times in media time) into FilmCraft's Text panel."""
    from . import transcribe
    try:
        ch = transcribe.chunks(video)
    except FileNotFoundError:
        return
    words = [{"text": w[0], "start": int(w[1] * TICKS), "end": int(max(w[2], w[1] + 0.02) * TICKS), "speaker": 0}
             for c in ch for w in c["w"] if w[0]]
    b.run("transcript.set", {"item": item, "transcript": {"language": "en", "speakers": [{"name": "Host"}], "words": words}})
