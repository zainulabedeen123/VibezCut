"""Pack a project to send to another computer, and open such a pack there.

A pack is one folder (and a zip of it) that opens on any machine:

    <name>/
      <name>.fcproj      media and proxy paths are RELATIVE (VibezCut reads them from the project's folder)
      media/             the full-resolution files (only with include_media; else the editor downloads them here)
      proxies/           small editing proxies (so an editor can start before the raw has downloaded)
      handoff/           HANDOFF.md (for people and for Claude), manifest.json, extra files (script, cut report…)

Why not File > Project Manager: it writes absolute paths (a moved copy opens offline) and always
copies the full-resolution media. The pack keeps VibezCut's own media identity (size + fingerprint)
in the project, so a relink by folder checks that a file is the right one.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import fc, ops

PACK_VERSION = 1
HANDOFF_DIR = "handoff"
_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|Volumes|mnt|media)/)")
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.1f} MB"


def _media_items(doc: dict) -> list[tuple[str, dict]]:
    out = []
    for iid, it in (doc.get("project", {}).get("items") or {}).items():
        kind = it.get("kind")
        m = kind.get("Media") if isinstance(kind, dict) else None
        if m is not None:
            out.append((iid, it))
    return out


def _file_path(ref) -> str | None:
    if isinstance(ref, dict) and isinstance(ref.get("File"), dict):
        return ref["File"].get("path")
    return None


def _resolve(path: str, base: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else base / p


class _Names:
    """Unique file names inside one folder (case-insensitive, like Windows)."""

    def __init__(self):
        self.used: set[str] = set()

    def take(self, name: str) -> str:
        stem, ext = os.path.splitext(_BAD.sub("_", name) or "file")
        cand, n = stem + ext, 1
        while cand.lower() in self.used:
            n += 1
            cand = f"{stem} {n}{ext}"
        self.used.add(cand.lower())
        return cand


_NO_PROXY = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff", ".jpg", ".jpeg", ".png", ".gif",
             ".bmp", ".tif", ".tiff", ".webp", ".psd", ".svg", ".heic"}
_BUNDLED_FONTS = {"inter", "jetbrains mono", "noto serif"}  # built into VibezCut: every install has them
_FONT_SUFFIX = re.compile(r"\s*\((TrueType|OpenType)\)\s*$", re.I)


def app_version() -> str:
    """'VibezCut 0.2.8' from the install's VERSION.txt (empty when running from a source checkout)."""
    here = Path(__file__).resolve()
    for p in (here.parents[2] / "VERSION.txt", here.parents[3] / "VERSION.txt"):
        try:
            return p.read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError):
            continue
    return ""


def fonts_used(doc: dict) -> list[str]:
    """Font families named by text layers and character styles (the project stores names, not files)."""
    out: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("font", "family"):
                    f = v.get("value", {}).get("Text") if isinstance(v, dict) and isinstance(v.get("value"), dict) else v
                    if isinstance(f, str) and f.strip():
                        out.add(f.strip())
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(doc)
    return sorted(out, key=str.lower)


def find_font_files(family: str) -> list[Path]:
    """Installed files of a font family (Windows: from the registry font list; empty elsewhere)."""
    try:
        import winreg
    except ImportError:
        return []
    found: list[Path] = []
    want = family.lower()
    sources = ((winreg.HKEY_LOCAL_MACHINE, Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"),
               (winreg.HKEY_CURRENT_USER, Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"))
    for hive, base in sources:
        try:
            with winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Fonts") as k:
                i = 0
                while True:
                    try:
                        name, data, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    fam = _FONT_SUFFIX.sub("", name).lower()
                    if fam == want or fam.startswith(want + " "):
                        fp = Path(data) if Path(data).is_absolute() else base / data
                        if fp.is_file() and fp not in found:
                            found.append(fp)
        except OSError:
            continue
    return found



_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}
BIG_IMAGE_PIXELS = 40_000_000  # ~7000 x 5600: decoded as 32-bit float RGBA it needs ~640 MB, and VibezCut keeps it whole


_PNG_SIG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of a PNG / JPEG / GIF / BMP from its header (no image library needed)."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == _PNG_SIG:
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
            if head[:2] == b"BM":
                return int.from_bytes(head[18:22], "little"), abs(int.from_bytes(head[22:26], "little", signed=True))
            if head[:2] == bytes([0xFF, 0xD8]):  # JPEG: walk the segments to the start-of-frame marker
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b[0] != 0xFF:
                        b = f.read(1)
                    m = f.read(1)
                    while m and m[0] == 0xFF:
                        m = f.read(1)
                    if not m:
                        return None
                    if m[0] in _SOF:
                        seg = f.read(7)
                        return int.from_bytes(seg[5:7], "big"), int.from_bytes(seg[3:5], "big")
                    if m[0] == 0x01 or 0xD0 <= m[0] <= 0xD9:
                        continue
                    n = int.from_bytes(f.read(2), "big")
                    f.seek(n - 2, 1)
    except OSError:
        return None
    return None


def preflight(project_path: str | Path) -> list[dict]:
    """Problems that make an export fail or crash VibezCut, found without opening the project."""
    src = Path(project_path)
    doc = json.loads(src.read_text(encoding="utf-8"))
    issues = []
    for iid, it in _media_items(doc):
        path = _file_path(it["kind"]["Media"].get("media"))
        if not path:
            continue
        p = _resolve(path, src.parent)
        if not p.exists():
            issues.append({"level": "error", "file": p.name, "problem": "file is missing"})
            continue
        if p.suffix.lower() in _IMG_EXT:
            wh = image_size(p)
            if wh and wh[0] * wh[1] > BIG_IMAGE_PIXELS:
                gb = wh[0] * wh[1] * 16 / 1e9
                issues.append({"level": "error", "file": p.name, "problem": f"image is {wh[0]}x{wh[1]} px: it needs ~{gb:.1f} GB of memory "
                               "to export and can crash VibezCut. Replace it with a smaller copy (4096 px on the long side is plenty for 4K)."})
    return issues


def _walk_strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_strings(v)
    elif isinstance(o, str):
        yield o


def inspect_project(project_path: str | Path) -> dict:
    """What a pack of this project would contain (reads the project file only; copies nothing)."""
    src = Path(project_path)
    doc = json.loads(src.read_text(encoding="utf-8"))
    base, media = src.parent, []
    for iid, it in _media_items(doc):
        m = it["kind"]["Media"]
        path = _file_path(m.get("media"))
        if not path:
            continue  # generator (colour matte, bars…): nothing to pack
        p = _resolve(path, base)
        ident = m.get("identity") or {}
        proxy = _file_path(m.get("proxy"))
        media.append({"item": int(iid) if iid.isdigit() else iid, "name": it.get("name") or p.name, "source": str(p),
                      "exists": p.exists(), "size": p.stat().st_size if p.exists() else ident.get("size"),
                      "fingerprint": ident.get("fingerprint"),
                      "proxy": str(_resolve(proxy, base)) if proxy else None})
    total = sum(x["size"] or 0 for x in media)
    return {"project": str(src), "media": media, "media_bytes": total, "media_size": _gb(total),
            "missing": [x["name"] for x in media if not x["exists"]]}


# ----------------------------------------------------------------------------- pack
def pack(project_path, out_dir, *, make_client=None, include_media=False, proxy_preset="h264_half", name="",
         notes="", extras=None, download_urls=None, make_zip=True, keep_folder=False, overwrite=False, progress=None) -> dict:
    """Build the pack (a zip, and with ``keep_folder`` also the unpacked folder). ``make_client`` returns a
    connection used to make the proxies (not needed when ``proxy_preset`` is empty and the project already
    has proxies). Without ``keep_folder`` the full-resolution media is streamed straight into the zip, so
    the disk needs room for ONE copy, not two."""
    say = progress or (lambda *_: None)
    src = Path(project_path)
    if not src.is_file():
        raise fc.FilmCraftError(f"project file not found: {src}")
    doc = json.loads(src.read_text(encoding="utf-8"))
    base = src.parent
    pname = _BAD.sub("_", name or src.stem).strip() or "Project"
    root = Path(out_dir) / pname
    if root.exists() and any(root.iterdir()):
        if not overwrite:
            raise fc.FilmCraftError(f"{root} already exists and is not empty (pass overwrite=True to replace it)")
        shutil.rmtree(root)
    for sub in ("media", "proxies", HANDOFF_DIR):
        (root / sub).mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    urls = download_urls or {}

    items = _media_items(doc)
    real = []
    for iid, it in items:
        m = it["kind"]["Media"]
        path = _file_path(m.get("media"))
        if path:
            real.append((iid, it, m, _resolve(path, base)))

    # --- is there room? (media is copied once into the zip, twice when the folder is kept too)
    stream = make_zip and not keep_folder
    media_bytes = sum(p.stat().st_size for _, _, _, p in real if p.exists())
    need_bytes = int(media_bytes * ((1 if stream else 2 if make_zip else 1) if include_media else 0)
                     + (0.3 * media_bytes if proxy_preset else 0) * (1 if stream else 2 if make_zip else 1) + 256e6)
    free = shutil.disk_usage(Path(out_dir)).free
    if free < need_bytes:
        shutil.rmtree(root, ignore_errors=True)  # the empty folders this call just made
        raise fc.FilmCraftError(f"not enough free space in {Path(out_dir).anchor or out_dir}: the pack needs about {_gb(need_bytes)} and "
                                f"{_gb(free)} is free. Pack to another drive, or leave the full-resolution media out (include_media=False).")
    streamed: dict[str, Path] = {}

    # --- proxies: reuse attached ones, make the rest next to the pack (the open project is not touched)
    proxies: dict[str, Path] = {}
    pnames = _Names()
    for iid, it, m, p in real:
        ref = _file_path(m.get("proxy"))
        if ref and _resolve(ref, base).exists():
            dst = root / "proxies" / pnames.take(Path(ref).name)
            say("proxies", f"copying {dst.name}")
            shutil.copyfile(_resolve(ref, base), dst)
            proxies[iid] = dst
    need = [int(iid) for iid, it, m, p in real
            if iid not in proxies and p.exists() and iid.isdigit() and p.suffix.lower() not in _NO_PROXY]
    if need and proxy_preset:
        if make_client is None:
            warnings.append("no connection to VibezCut: proxies were not created")
        else:
            c = make_client()
            say("proxies", f"creating {len(need)} proxy file(s) ({proxy_preset})")
            r = c.run("media.createProxies", {"items": need, "preset": proxy_preset,
                                              "destination": str(root / "proxies"), "attach": False, "wait": False})
            job = r.get("job")
            for o in r.get("outputs") or []:
                proxies[str(o["item"])] = Path(o["path"])
            for sk in r.get("skipped") or []:
                if "no video" not in str(sk):  # audio and images need no proxy
                    warnings.append(f"proxy skipped: {sk}")
            while job is not None:
                js = c.run("jobs.list", {})
                js = js if isinstance(js, list) else (js.get("jobs") if isinstance(js, dict) and "jobs" in js else [js])
                j = next((x for x in js if isinstance(x, dict) and x.get("id") == job), None)
                if j is None:
                    break
                say("proxies", f"{j.get('status', '')} {round(100 * (j.get('progress') or 0))}%")
                if j.get("finished"):
                    if j.get("error"):
                        warnings.append(f"proxy job failed: {j['error']}")
                    break
                time.sleep(2)
            for iid in list(proxies):
                if not proxies[iid].exists():
                    warnings.append(f"proxy missing after the job: {proxies[iid].name}")
                    del proxies[iid]

    # --- media files + rewritten paths
    mnames, entries, total, copied = _Names(), [], 0, 0
    for iid, it, m, p in real:
        ident = m.get("identity") or {}
        rel = "media/" + mnames.take(p.name)
        size = p.stat().st_size if p.exists() else ident.get("size")
        included = False
        if include_media:
            if p.exists() and stream:
                streamed[rel] = p  # goes into the zip straight from where it is
                included, copied = True, copied + size
            elif p.exists():
                say("media", f"copying {p.name} ({_gb(size)})")
                shutil.copyfile(p, root / rel)
                if (root / rel).stat().st_size != size:
                    raise fc.FilmCraftError(f"copy of {p.name} is incomplete")
                included, copied = True, copied + size
            else:
                warnings.append(f"{p.name} is missing on this computer, so it is not in the pack")
        total += size or 0
        m["media"] = {"File": {"path": rel}}
        prel = None
        if iid in proxies:
            prel = "proxies/" + proxies[iid].name
            m["proxy"] = {"File": {"path": prel}}
        else:
            m["proxy"] = None
        entries.append({"item": int(iid) if iid.isdigit() else iid, "name": it.get("name") or p.name, "path": rel,
                        "size": size, "fingerprint": ident.get("fingerprint"), "included": included, "proxy": prel,
                        "download_url": urls.get(p.name) or urls.get(it.get("name") or "") or None})
    if not real:
        warnings.append("the project has no media files")

    for issue in preflight(src):
        warnings.append(f"{issue['file']}: {issue['problem']}")

    # --- anything else that still points at this computer
    external = sorted({s for s in _walk_strings(doc) if _ABS.match(s)})
    if external:
        warnings.append(f"{len(external)} other absolute path(s) in the project will be offline elsewhere (fonts, LUTs…): see manifest")

    fonts = []
    for fam in fonts_used(doc):
        if fam.lower() in _BUNDLED_FONTS:
            fonts.append({"family": fam, "bundled": True, "files": []})
            continue
        files = []
        for fp in find_font_files(fam):
            (root / "fonts").mkdir(exist_ok=True)
            shutil.copyfile(fp, root / "fonts" / fp.name)
            files.append("fonts/" + fp.name)
        fonts.append({"family": fam, "bundled": False, "files": files})
        warnings.append(f"font '{fam}': " + (f"{len(files)} file(s) copied to fonts/, install them on the editor's computer"
                                             if files else "not found on this computer; without it text falls back to Inter"))

    pfile = f"{pname}.fcproj"
    (root / pfile).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    # --- handoff
    summary = {}
    try:
        if make_client is not None:
            summary = ops.summary(make_client())
    except fc.FilmCraftError:
        pass
    manifest = {"pack_version": PACK_VERSION, "created": datetime.now().isoformat(timespec="seconds"),
                "project_file": pfile, "schema_version": doc.get("schema_version"), "generator": doc.get("generator"),
                "vibezcut_version": app_version(), "fonts": fonts,
                "sequence": {k: summary.get(k) for k in ("name", "duration_s", "tracks")},
                "media": entries, "external_references": external, "warnings": warnings}
    hd = root / HANDOFF_DIR
    (hd / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    for e in extras or []:
        ep = Path(e)
        if ep.is_file():
            shutil.copyfile(ep, hd / ep.name)
        elif ep.is_dir():
            shutil.copytree(ep, hd / ep.name, dirs_exist_ok=True)
        else:
            warnings.append(f"extra not found: {e}")
    (hd / "HANDOFF.md").write_text(_handoff_md(pname, manifest, include_media, notes, [Path(e).name for e in extras or []]), encoding="utf-8")
    (hd / "manifest.json").write_text(json.dumps({**manifest, "warnings": warnings}, indent=1, ensure_ascii=False), encoding="utf-8")

    result = {"pack_dir": str(root), "project": str(root / pfile), "media_included": include_media,
              "media": [{"name": e["name"], "size": _gb(e["size"] or 0), "included": e["included"], "proxy": bool(e["proxy"])} for e in entries],
              "media_total": _gb(total), "warnings": warnings}
    if make_zip:
        say("zip", "writing the zip")
        zp = Path(out_dir) / f"{pname}.zip"
        stored = {".mp4", ".mov", ".mkv", ".mxf", ".wav", ".mp3", ".m4a", ".aac", ".webm", ".avi", ".jpg", ".jpeg", ".png", ".flac", ".ogg"}
        try:
            with zipfile.ZipFile(zp, "w", allowZip64=True) as z:
                for f in sorted(root.rglob("*")):
                    if f.is_file():
                        z.write(f, Path(pname) / f.relative_to(root),
                                compress_type=zipfile.ZIP_STORED if f.suffix.lower() in stored else zipfile.ZIP_DEFLATED)
                for rel, srcp in streamed.items():
                    say("zip", f"adding {srcp.name}")
                    z.write(srcp, Path(pname) / rel, compress_type=zipfile.ZIP_STORED if srcp.suffix.lower() in stored else zipfile.ZIP_DEFLATED)
        except BaseException:  # a half-written zip is worse than none
            zp.unlink(missing_ok=True)
            raise
        result.update(zip=str(zp), zip_size=_gb(zp.stat().st_size))
        if not keep_folder:
            shutil.rmtree(root, ignore_errors=True)  # the staging folder this call made: only the zip is the deliverable
            result.pop("pack_dir"), result.pop("project")
    if not include_media:
        result["next"] = (f"The full-resolution media ({_gb(total)}) is NOT in the pack. The editor puts these files in the "
                          "'media' folder next to the project (or runs fc_relink on the folder they downloaded to).")
    return result


def _handoff_md(name, manifest, include_media, notes, extras) -> str:
    seq = manifest.get("sequence") or {}
    dur = seq.get("duration_s")
    lines = [f"# Handoff: {name}", "",
             f"Packed {manifest['created']} · {manifest.get('vibezcut_version') or manifest.get('generator') or 'VibezCut'} · project format {manifest.get('schema_version')}", "",
             "## For Claude: read this first",
             "1. Connect to VibezCut and call `fc_handoff()`: it shows what is missing and what was done so far.",
             "2. If media is missing, put the files in the `media` folder next to the project file, or call `fc_relink(folder)` with the folder they were downloaded to.",
             "3. One editor owns this video. Do not re-transcribe the raw: the word-level transcript is already in the project (Text panel).",
             "4. Edit with the `fc_*` tools (every change is one undo step). Proxies are for editing only; export always uses the full-resolution files.",
             "5. When you finish a session, call `fc_handoff(log=\"what you did / what is left\")`.", ""]
    if notes.strip():
        lines += ["## Notes from the sender", notes.strip(), ""]
    lines += ["## Sequence", f"- {seq.get('name') or 'Main Edit'}" + (f", {int(dur // 60)}:{int(dur % 60):02d}" if dur else ""), ""]
    lines += ["## Media", "| File | Size | In this pack | Proxy | Download |", "|---|---|---|---|---|"]
    for e in manifest["media"]:
        lines.append(f"| {e['name']} | {_gb(e['size'] or 0)} | {'yes' if e['included'] else 'no: put it in `' + e['path'] + '`'} | "
                     f"{'yes' if e['proxy'] else 'no'} | {e.get('download_url') or ''} |")
    lines.append("")
    custom = [f for f in manifest.get("fonts", []) if not f["bundled"]]
    if custom:
        lines += ["## Fonts", "Text layers use these fonts. Install them before opening the project, or the text falls back to Inter:"]
        lines += [f"- {f['family']}: " + (", ".join(f"`{x}`" for x in f["files"]) if f["files"] else "NOT in this pack: ask the sender") for f in custom]
        lines.append("")
    if extras:
        lines += ["## Other files in this folder", *[f"- `{x}`" for x in extras], ""]
    if manifest["warnings"]:
        lines += ["## Warnings", *[f"- {w}" for w in manifest["warnings"]], ""]
    lines += ["## Changelog", "See `CHANGELOG.md` (each session adds a line).", ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- editor side
def handoff_dir(project_path: str | Path) -> Path:
    return Path(project_path).parent / HANDOFF_DIR


def read_handoff(c, project_path, log: str = "") -> dict:
    """Editor side: what this pack is, which media is still missing, what was done so far."""
    hd = handoff_dir(project_path)
    if log.strip():
        hd.mkdir(exist_ok=True)
        with (hd / "CHANGELOG.md").open("a", encoding="utf-8") as f:
            f.write(f"- {datetime.now():%Y-%m-%d %H:%M} {log.strip()}\n")
    md, manifest = hd / "HANDOFF.md", hd / "manifest.json"
    out = {"project": str(project_path), "handoff_found": md.exists()}
    if md.exists():
        out["handoff"] = md.read_text(encoding="utf-8")
    if manifest.exists():
        mf = json.loads(manifest.read_text(encoding="utf-8"))
        out["sequence"] = mf.get("sequence")
        out["pack_created"] = mf.get("created")
    if (hd / "CHANGELOG.md").exists():
        out["changelog"] = (hd / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()[-30:]
    if c is not None:
        out["media"] = media_status(c)
        missing = [m for m in out["media"] if m["status"] != "online"]
        out["missing"] = [m["name"] for m in missing]
        if missing:
            out["next"] = ("Some media is not linked. Put the files in the 'media' folder next to the project and reopen, "
                           "or call fc_relink(folder) with the folder they are in.")
    return out


def media_status(c) -> list[dict]:
    r = c.run("media.status", {})
    if isinstance(r, dict):
        r = r.get("items") if "items" in r else [r]
    rows, out = r, []
    for x in rows or []:
        status = x.get("status") or ("online" if x.get("online") else "missing")
        if status == "generated":
            continue
        out.append({"item": x.get("item"), "name": x.get("name") or x.get("fileName"), "status": status})
    return out


def relink(c, folder: str) -> dict:
    """Find the missing media inside ``folder`` (searches its sub-folders; every candidate is
    checked against the fingerprint stored in the project) and link it."""
    if not Path(folder).is_dir():
        raise fc.FilmCraftError(f"folder not found: {folder}")
    before = [m for m in media_status(c) if m["status"] != "online"]
    r = c.run("media.autoRelink", {"folder": folder})
    after = [m for m in media_status(c) if m["status"] != "online"]
    return {"was_missing": len(before), "still_missing": [m["name"] for m in after], "relinked": len(before) - len(after), "engine": r}
