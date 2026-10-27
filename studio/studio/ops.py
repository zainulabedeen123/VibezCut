"""High-level revision operations. They work on whichever connection is given (live app or
headless project file) and only issue normal FilmCraft commands, so every change is undoable
and manual edits the user made in FilmCraft are kept."""
from __future__ import annotations

from . import fc

T = fc.TICKS


def _tracks(seq, kind=None):
    for k in (["video", "audio"] if kind is None else [kind]):
        for tr in seq.get(k, []):
            yield k, tr


def summary(c):
    seq = c.sequence()
    out = {"mode": c.mode, "name": seq.get("name"), "tracks": []}
    end = 0
    for kind, tr in _tracks(seq):
        items = tr.get("items", [])
        if items:
            end = max(end, max(i["end"] for i in items))
        out["tracks"].append({"track": tr.get("name"), "id": tr.get("id"), "clips": len(items)})
    out["duration_s"] = round(end / T, 3)
    return out


def clips_at(c, seconds, kind="video"):
    seq, t = c.sequence(), int(seconds * T)
    hits = []
    for _, tr in _tracks(seq, kind):
        for it in tr.get("items", []):
            if it["start"] <= t < it["end"]:
                hits.append({"track": tr.get("name"), "clip": it["clip"], "name": it.get("name"),
                             "start_s": round(it["start"] / T, 3), "end_s": round(it["end"] / T, 3)})
    return hits


def find_text(c, query):
    """Text graphics whose current text contains ``query`` (case-insensitive). Reads the
    actual layer text (clip names can be stale after edits made in FilmCraft)."""
    q, seq, out = query.lower(), c.sequence(), []
    for idx, (_, tr) in enumerate(_tracks(seq, "video")):
        if idx == 0:  # V1 holds the camera footage
            continue
        for it in tr.get("items", []):
            try:
                g = c.run("graphics.list", {"clip": it["clip"]})
            except fc.FilmCraftError:
                continue
            for L in (g or {}).get("layers", []) if isinstance(g, dict) else []:
                if L.get("kind") == "text" and q in (L.get("text") or "").lower():
                    out.append({"track": tr.get("name"), "clip": it["clip"], "layer": L.get("layer", 0),
                                "text": L.get("text"), "start_s": round(it["start"] / T, 3), "end_s": round(it["end"] / T, 3)})
    return out


def set_text(c, clip, text, layer=0):
    # `rename`: the timeline label follows the text, in the same undo step
    return c.run("graphics.setText", {"clip": clip, "layer": layer, "text": text, "rename": True})


def style_text(c, clip, props, layer=0):
    """props: font, font_style, size, fill_color, align, tracking, leading, shadow, stroke…"""
    return c.run("graphics.set", {"clip": clip, "layer": layer, "props": props})


def accent(c, clip, text, substring, color="#C8F040", layer=0):
    i = text.find(substring)
    if i < 0:
        raise fc.FilmCraftError(f"'{substring}' not in '{text}'")
    return c.run("graphics.setCharStyle", {"clip": clip, "layer": layer, "start": i, "end": i + len(substring), "style": {"color": color}})


def move_clip(c, clip, start_s, track=None, fps=60):
    mv = {"clip": clip, "time": fc.ticks(start_s, fps)}
    if not track:  # the engine needs a track per move: default to the clip's own
        for _, tr in _tracks(c.sequence()):
            if any(i["clip"] == clip for i in tr.get("items", [])):
                track = tr["id"]
                break
        else:
            raise fc.FilmCraftError(f"no clip {clip} in this sequence")
    mv["track"] = track
    return c.run("timeline.move", {"moves": [mv], "insert": False})


def trim(c, clip, edge, frames, ripple=True):
    """Extend (+) or shorten (-) a clip edge by ``frames``. Ripple keeps everything after in sync."""
    return c.run("timeline.trim", {"clip": clip, "edge": edge, "mode": "ripple" if ripple else "regular", "deltaFrames": frames})


def tighten_cut(c, seconds, frames_out=0, frames_in=0):
    """Adjust the edit point nearest ``seconds`` on V1: frames_out trims the outgoing clip's end,
    frames_in the incoming clip's start (negative = remove frames)."""
    seq, t = c.sequence(), int(seconds * T)
    v1 = next(tr for _, tr in _tracks(seq, "video"))
    items = sorted(v1["items"], key=lambda i: i["start"])
    k = min(range(len(items) - 1), key=lambda i: abs(items[i]["end"] - t))
    res = {}
    try:
        if frames_out:
            res["out"] = trim(c, items[k]["clip"], "out", frames_out)
        if frames_in:
            res["in"] = trim(c, items[k + 1]["clip"], "in", -frames_in)
    except fc.FilmCraftError as e:
        if "sync" in str(e):
            raise fc.FilmCraftError(f"{e}. A graphic or sound on another track spans this cut, so a ripple "
                                    "trim would push it out of sync. Trim that overlay too, or adjust the cut "
                                    "with ripple=False and close the gap.") from e
        raise
    res["cut_s"] = round(items[k]["end"] / T, 3)
    return res


def remove_range(c, start_s, end_s):
    """Ripple-delete a time range on all targeted tracks (e.g. a repeated phrase)."""
    c.run("markers.markIn", {"seconds": start_s, "target": "program"})
    c.run("markers.markOut", {"seconds": end_s, "target": "program"})
    r = c.run("sequence.extract", {})
    c.run("markers.clearInOut", {"target": "program"})
    return r


def clip_gain(c, clips, db, relative=False):
    return c.run("clip.audioGain", {"clips": clips, "mode": "adjust" if relative else "set", "db": db})


def scale_keys(c, clip, keys, fps=60):
    """keys: [(seconds, scale_percent), ...] on a video clip's Motion > Scale."""
    return [c.run("effects.setParam", {"clip": clip, "effect": "motion", "param": "scale", "value": v,
                                       "time": fc.ticks(s, fps), "keyframe": True}) for s, v in keys]


def undo(c, steps=1):
    return [c.run("edit.undo", {}) for _ in range(steps)]


def save(c, path=None):
    return c.run("file.save", {"path": path} if path else {})
