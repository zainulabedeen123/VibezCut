# Installing VibezCut (editors)

## Once

1. **Claude Code**: install it and sign in (https://claude.com/claude-code).
2. **VibezCut**: download `VibezCut-win-Setup.exe` from the latest release
   (https://github.com/zainulabedeen123/VibezCut/releases/latest) and run it. Windows may show
   "Windows protected your PC" (the installer is not code-signed yet): More info > Run anyway.
   It installs to `%LocalAppData%\VibezCut` (no admin rights) with Start menu and desktop shortcuts.

That is all for editing with Claude: VibezCut ships its own private Python for the Claude tools.
On its first start it copies the Claude skills (`filmcraft-edit`, `pack-for-editor`) to
`%USERPROFILE%\.claude\skills` and registers the `filmcraft-studio` MCP server for your user
(`claude mcp get filmcraft-studio` should say Connected; restart Claude Code after the first start).
If Claude Code was installed after VibezCut, it tries again on the next start.

### Optional: transcription add-on (for cutting raw recordings)

Only the person who turns raw footage into the first cut needs this (an NVIDIA GPU is required):
**Python 3.12** from the python.org installer (tick "Add python.exe to PATH"; not the Microsoft Store
Python), then
```
py -3 -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
py -3 -m pip install faster-whisper "numpy<2" pillow "mcp>=1.16,<2"
```
and **ffmpeg** on PATH (`winget install Gyan.FFmpeg`). Restart VibezCut and Claude: when a Python with
these packages is found, VibezCut uses it instead of the bundled one.

## When you receive a project

You get a zip. Unzip it anywhere, then:
1. If the zip says the full-resolution media is not included, download the files listed in
   `handoff/HANDOFF.md` into the `media` folder next to the `.fcproj` (keep the file names).
2. Open the `.fcproj` in VibezCut, open Claude Code in the unzipped folder, and say "connect to VibezCut and
   read the handoff". Claude finds missing media, tells you what the sender noted, and can link the raw if you
   downloaded it somewhere else.
3. Edit with proxies; export always uses the full-resolution files.

## Every day

- Start VibezCut from the normal shortcut. It opens on **Home**: your projects as cards, last opened first
  (thumbnail, size, duration); click one to open it, or **New project**. The Home icon (top left) brings it back.
  Settings > General > At Startup chooses another start (open the most recent project, or an empty one).
- Every start is ready for Claude to edit live in the window
  (loopback only, with a fresh secret token per session; set `VIBEZCUT_NO_CLAUDE=1` to turn it off).
- Open Claude Code in your video's folder and say what you want ("edit this video", "change the
  title at 2:10", …).

## Updates

VibezCut checks for a new version every time it starts and downloads it in the background. When
it's ready you see **"VibezCut x.y.z is ready — Restart to update"** (your project is offered for
saving first). If you choose Later, it installs on the next start. Claude's skill and MCP server are
updated with it.

## Uninstall

Windows Settings > Apps > VibezCut > Uninstall. It also removes the Claude skill and the MCP server
registration. Your projects and media are never touched.
