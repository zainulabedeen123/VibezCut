"""FilmCraft Studio MCP server: the editing workflow as tools.

Pipeline tools (raw recording -> FilmCraft project) run locally on the GPU.
Revision tools act on the running FilmCraft window (live) or on a project file (headless),
using ordinary FilmCraft commands, so every change is undoable in FilmCraft.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

from . import assemble, build, config, fc, ops, takes, transcribe

mcp = FastMCP("filmcraft-studio")
_conn: dict = {}


def _client(target: str = "live"):
    """``live`` = the open FilmCraft window; otherwise a .fcproj path opened headless."""
    key = target
    c = _conn.get(key)
    if c is None:
        c = fc.Live() if target == "live" else fc.Headless(target)
        _conn[key] = c
    return c


def _drop(target):
    c = _conn.pop(target, None)
    if c:
        c.close()


def _safe(fn):
    try:
        return fn()
    except fc.FilmCraftError as e:
        return {"error": str(e)}


# ============================================================================ pipeline
@mcp.tool()
def studio_transcribe(video: str, terms: str = "") -> dict:
    """Extract audio and transcribe a raw recording verbatim (stutters kept). Writes
    chunks.json / phrases.json / transcript.txt in <video dir>/_studio/<name>/. ``terms`` adds
    product names to the prompt (e.g. the product or brand names said in the video). Takes a few minutes per hour."""
    return transcribe.run(video, terms)


@mcp.tool()
def studio_read_transcript(video: str, start: int = 0, count: int = 400) -> str:
    """Phrase list of the recording: index, start s, end s, text. Phrases are separated by
    >=0.12 s of quiet, so every phrase boundary is a safe cut. Page with start/count."""
    lines = (config.workdir(video) / "transcript.txt").read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start:start + count]) + f"\n[{min(len(lines), start + count)}/{len(lines)}]"


@mcp.tool()
def studio_words(video: str, t0: float, t1: float) -> str:
    """Word-level timestamps (verbatim, from the long-context pass) between t0 and t1 seconds,
    plus the quiet runs there. Use it to place an inner start on the last of several repeats."""
    from . import audio
    import numpy as np
    ws = [f"{w[0]}({w[1]:.2f})" for c in transcribe.chunks(video) for w in c["w"] if t0 - 0.3 <= w[1] <= t1]
    db = np.load(audio.extract(video)["db"])
    q = [f"{a:.2f}-{b:.2f}" for a, b in audio.runs(db, -56) if a < t1 and b > t0]
    return "words: " + " ".join(ws) + "\nquiet: " + ", ".join(q)


@mcp.tool()
def studio_save_units(video: str, units: list) -> dict:
    """Save the chosen takes. Each unit: {"text": str | [variants], "k1": first phrase,
    "k2": last phrase, "sw": [t0,t1]? (start window, for repeats inside a phrase),
    "ew": [t0,t1]?, "fixS": t?, "lenient": bool? (allow legit repeats like 'then this clip, then this clip')}."""
    p = config.workdir(video) / "units.json"
    p.write_text(json.dumps(units, indent=1), encoding="utf-8")
    return {"saved": len(units), "path": str(p)}


@mcp.tool()
def studio_resolve(video: str, only: list[int] | None = None) -> dict:
    """Find frame-safe cut points for every unit (judged by transcription + forced alignment).
    ``only`` re-resolves just those unit indexes. Returns BAD units to fix. Log: resolve.log."""
    lines = []
    r = takes.resolve_all(video, only=set(only) if only else None, log=lines.append)
    (config.workdir(video) / "resolve.log").write_text("\n".join(lines), encoding="utf-8")
    r["log_tail"] = [l for l in lines if l.startswith("BAD") or "DUP" in l][:40]
    return r


@mcp.tool()
def studio_assemble(video: str, removals: list[list[float]] | None = None) -> dict:
    """Build timeline pieces from the resolved units, render the edited dialogue and verify it:
    the whole edit is re-transcribed and immediate repeats / restarts are listed with times.
    ``removals`` = [[src_t0, src_t1], ...] source-time spans to cut out inside a unit (a stutter)."""
    p = assemble.build_pieces(video, removals or [])
    v = assemble.verify(video)
    return {**p, "verify": v["path"], "issues": v["issues"][:60], "edited_duration": v["duration"]}


@mcp.tool()
def studio_build_project(edit_json: str, out: str = "") -> dict:
    """Create the FilmCraft project from an edit.json (see studio/build.py for the schema):
    cuts with linked audio, camera keyframes, stems, stills, clips, native text, accent bars,
    and the verbatim transcript in FilmCraft's Text panel. FilmCraft does not need to be open."""
    return build.build_project(edit_json, out or None)


# ============================================================================ FilmCraft (live / file)
@mcp.tool()
def fc_status(target: str = "live") -> dict:
    """Sequence summary (tracks, clip counts, duration). target = "live" or a .fcproj path."""
    return _safe(lambda: ops.summary(_client(target)))


@mcp.tool()
def fc_open(path: str) -> dict:
    """Open a project in the running FilmCraft window."""
    return _safe(lambda: _client("live").run("file.open", {"path": path}))


@mcp.tool()
def fc_clips_at(seconds: float, kind: str = "video", target: str = "live"):
    """Clips under the playhead position ``seconds`` (kind: video | audio)."""
    return _safe(lambda: ops.clips_at(_client(target), seconds, kind))


@mcp.tool()
def fc_find_text(query: str, target: str = "live"):
    """Find text graphics whose text contains ``query``."""
    return _safe(lambda: ops.find_text(_client(target), query))


@mcp.tool()
def fc_set_text(clip: int, text: str, target: str = "live") -> dict:
    """Retype a text graphic (keeps its style and animation)."""
    return _safe(lambda: ops.set_text(_client(target), clip, text))


@mcp.tool()
def fc_style_text(clip: int, props: dict, target: str = "live") -> dict:
    """Restyle a text graphic. props: font, font_style, size, fill_color, align, tracking,
    leading, shadow, stroke, stroke_width, position [x,y], opacity…"""
    return _safe(lambda: ops.style_text(_client(target), clip, props))


@mcp.tool()
def fc_accent(clip: int, text: str, substring: str, color: str = "#C8F040", target: str = "live") -> dict:
    """Colour part of a text graphic (``text`` = the graphic's current text)."""
    return _safe(lambda: ops.accent(_client(target), clip, text, substring, color))


@mcp.tool()
def fc_move_clip(clip: int, start_seconds: float, track: str = "", target: str = "live") -> dict:
    """Move a clip to a new start time (and optionally another track)."""
    return _safe(lambda: ops.move_clip(_client(target), clip, start_seconds, track or None))


@mcp.tool()
def fc_trim(clip: int, edge: str, frames: int, ripple: bool = True, target: str = "live") -> dict:
    """Trim a clip edge ("in" | "out") by frames (+ extend, - shorten); ripple keeps sync."""
    return _safe(lambda: ops.trim(_client(target), clip, edge, frames, ripple))


@mcp.tool()
def fc_tighten_cut(seconds: float, frames_out: int = 0, frames_in: int = 0, target: str = "live") -> dict:
    """Adjust the V1 edit nearest ``seconds``: frames_out on the outgoing clip's end,
    frames_in on the incoming clip's start (negative removes frames, e.g. a pause or a breath)."""
    return _safe(lambda: ops.tighten_cut(_client(target), seconds, frames_out, frames_in))


@mcp.tool()
def fc_remove_range(start_seconds: float, end_seconds: float, target: str = "live") -> dict:
    """Ripple-delete a timeline range (e.g. a repeated sentence) on the targeted tracks."""
    return _safe(lambda: ops.remove_range(_client(target), start_seconds, end_seconds))


@mcp.tool()
def fc_gain(clips: list[int], db: float, relative: bool = False, target: str = "live") -> dict:
    """Set (or adjust, relative=True) audio clip gain in dB, e.g. the music bed."""
    return _safe(lambda: ops.clip_gain(_client(target), clips, db, relative))


@mcp.tool()
def fc_scale_keys(clip: int, keys: list[list[float]], target: str = "live"):
    """Scale keyframes on a video clip: [[seconds, percent], ...] (timeline seconds)."""
    return _safe(lambda: ops.scale_keys(_client(target), clip, [tuple(k) for k in keys]))


@mcp.tool()
def fc_undo(steps: int = 1, target: str = "live"):
    """Undo the last FilmCraft steps."""
    return _safe(lambda: ops.undo(_client(target), steps))


@mcp.tool()
def fc_save(path: str = "", target: str = "live") -> dict:
    """Save the project (to ``path`` when given). Headless targets must be saved to persist."""
    r = _safe(lambda: ops.save(_client(target), path or None))
    return r


@mcp.tool()
def fc_close(target: str) -> str:
    """Close a headless session (after fc_save)."""
    _drop(target)
    return "closed"


@mcp.tool()
def fc_frame(seconds: float, target: str = "live"):
    """Look at the program frame at ``seconds`` (live: Program monitor screenshot)."""
    p = Path(tempfile.gettempdir()) / f"fc_frame_{seconds:.2f}.png"
    _client(target).render_frame(seconds, p)  # errors surface as MCP tool errors
    return Image(path=str(p))


@mcp.tool()
def fc_command(command: str, params: dict | None = None, target: str = "live") -> dict:
    """Any FilmCraft command by id (escape hatch; see filmcraft-cli commands)."""
    return _safe(lambda: _client(target).run(command, params or {}))


@mcp.tool()
def fc_inspect(target: str = "live") -> dict:
    """Full active-sequence JSON (tracks, clips, effects, keyframes). Large."""
    return _safe(lambda: _client(target).sequence())


def main():
    mcp.run()


if __name__ == "__main__":
    main()
