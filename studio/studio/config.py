"""Paths and settings. Override with environment variables or studio.json next to this package."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # <repo>/studio
REPO = ROOT.parent
_CFG = ROOT / "studio.json"                             # per-machine settings, not committed
_DEFAULTS = {
    # folder holding the editor and CLI binaries (on macOS: VibezCut.app/Contents/MacOS);
    # empty = found automatically (release zip / app bundle / this repo's own build)
    "filmcraft_home": "",
    "control_port": 9876,
    "fps": 60,
    "whisper_model": "large-v3-turbo",
    "device": "auto",   # "auto" = cuda when an NVIDIA GPU is usable, else cpu (macOS); or "cuda" / "cpu"
}


def settings() -> dict:
    s = dict(_DEFAULTS)
    if _CFG.exists():
        s.update(json.loads(_CFG.read_text(encoding="utf-8")))
    if os.environ.get("FILMCRAFT_HOME"):
        s["filmcraft_home"] = os.environ["FILMCRAFT_HOME"]
    return s


# Windows names first; macOS / Linux binaries have no extension (in VibezCut.app: Contents/MacOS)
APP_NAMES = ("VibezCut.exe", "filmcraft.exe", "VibezCut", "filmcraft")
CLI_NAMES = ("vibezcut-cli.exe", "filmcraft-cli.exe", "vibezcut-cli", "filmcraft-cli")


def _first(folder: Path, names) -> Path | None:
    return next((folder / n for n in names if (folder / n).exists()), None)


def home() -> Path:
    """Folder with the editor binaries: studio.json / FILMCRAFT_HOME, else the release zip's root
    (binaries next to studio/), else this repo's own release build."""
    h = settings()["filmcraft_home"]
    if h:
        return Path(h)
    cands = (
        REPO,                                   # Windows zip: binaries next to studio/
        REPO.parent / "MacOS",                  # macOS: VibezCut.app/Contents/Resources/studio
        Path("/Applications/VibezCut.app/Contents/MacOS"),
        Path.home() / "Applications" / "VibezCut.app" / "Contents" / "MacOS",
        REPO / "target" / "x86_64-pc-windows-msvc" / "release",
        REPO / "target" / "release",
        REPO / "dist",
    )
    for cand in cands:
        if _first(cand, CLI_NAMES):
            return cand
    raise FileNotFoundError("VibezCut binaries not found: build the repo (cargo build --release) "
                            'or set {"filmcraft_home": "..."} in studio/studio.json')


def cli() -> Path:
    return _first(home(), CLI_NAMES) or home() / CLI_NAMES[0]


def app() -> Path:
    return _first(home(), APP_NAMES) or home() / APP_NAMES[0]


_DEVICE: str | None = None


def device() -> str:
    """The compute device for Whisper and forced alignment: "cuda" or "cpu". "auto" (and "cuda" on a
    machine without a usable NVIDIA GPU, e.g. a Mac) resolve to "cpu"."""
    global _DEVICE
    if _DEVICE is None:
        want = str(settings().get("device", "auto")).lower()
        _DEVICE = "cpu" if want == "cpu" else ("cuda" if _cuda_available() else "cpu")
    return _DEVICE


def _cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        pass
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


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
