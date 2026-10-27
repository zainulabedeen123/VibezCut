"""Paths and settings. Override with environment variables or studio.json next to this package."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # <repo>/studio
REPO = ROOT.parent
_CFG = ROOT / "studio.json"                             # per-machine settings, not committed
_DEFAULTS = {
    # folder holding filmcraft.exe and filmcraft-cli.exe; empty = this repo's own build
    "filmcraft_home": "",
    "control_port": 9876,
    "fps": 60,
    "whisper_model": "large-v3-turbo",
    "device": "cuda",
}


def settings() -> dict:
    s = dict(_DEFAULTS)
    if _CFG.exists():
        s.update(json.loads(_CFG.read_text(encoding="utf-8")))
    if os.environ.get("FILMCRAFT_HOME"):
        s["filmcraft_home"] = os.environ["FILMCRAFT_HOME"]
    return s


def home() -> Path:
    h = settings()["filmcraft_home"]
    if h:
        return Path(h)
    for cand in (REPO / "target" / "release", REPO / "dist"):
        if (cand / "filmcraft-cli.exe").exists():
            return cand
    raise FileNotFoundError("FilmCraft binaries not found: build the repo (cargo build --release) "
                            'or set {"filmcraft_home": "..."} in studio/studio.json')


def cli() -> Path:
    return home() / "filmcraft-cli.exe"


def app() -> Path:
    return home() / "filmcraft.exe"


def control_port() -> int:
    return int(os.environ.get("FILMCRAFT_CONTROL_PORT", settings()["control_port"]))


def state_dir() -> Path:
    """Per-user folder (not shared, not in the repo) for the session control token."""
    # not %LOCALAPPDATA%: the Microsoft Store Python virtualizes that folder, so it would not
    # see the token the launcher writes there
    d = Path.home() / ".filmcraft-studio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def control_token() -> str | None:
    if os.environ.get("FILMCRAFT_CONTROL_TOKEN"):
        return os.environ["FILMCRAFT_CONTROL_TOKEN"]
    f = state_dir() / "control.token"
    return f.read_text().strip() if f.exists() else None


def workdir(video: str | Path) -> Path:
    """Working folder for one video's analysis artifacts: <video dir>/_studio/<stem>/"""
    v = Path(video)
    d = v.parent / "_studio" / v.stem
    d.mkdir(parents=True, exist_ok=True)
    return d
