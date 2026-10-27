# Installing VibezCut (editors)

## Once

1. **Claude Code**: install it and sign in (https://claude.com/claude-code).
2. **Python 3.12** from the python.org installer (tick "Add python.exe to PATH"). Not the Microsoft
   Store Python: it is sandboxed and cannot see VibezCut's install folder. Then the studio packages:
   ```
   py -3 -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
   py -3 -m pip install faster-whisper "numpy<2" pillow "mcp>=1.16,<2"
   ```
   (needs an NVIDIA GPU for transcription; without one, live revisions still work)
3. **ffmpeg** on PATH (`winget install Gyan.FFmpeg`).
4. **VibezCut**: download `VibezCut-win-Setup.exe` from the latest release
   (https://github.com/zainulabedeen123/VibezCut/releases/latest) and run it. Windows may show
   "Windows protected your PC" (the installer is not code-signed yet): More info > Run anyway.
   It installs to `%LocalAppData%\VibezCut` (no admin rights) with Start menu and desktop shortcuts.

On its first start VibezCut connects itself to Claude: it copies the `filmcraft-edit` skill to
`%USERPROFILE%\.claude\skills` and registers the `filmcraft-studio` MCP server for your user
(`claude mcp get filmcraft-studio` should say Connected). This needs steps 1 and 2 done first;
if they weren't, it tries again on the next start.

## When you receive a project

You get a zip. Unzip it anywhere, then:
1. If the zip says the full-resolution media is not included, download the files listed in
   `handoff/HANDOFF.md` into the `media` folder next to the `.fcproj` (keep the file names).
2. Open the `.fcproj` in VibezCut, open Claude Code in the unzipped folder, and say "connect to VibezCut and
   read the handoff". Claude finds missing media, tells you what the sender noted, and can link the raw if you
   downloaded it somewhere else.
3. Edit with proxies; export always uses the full-resolution files.

## Every day

- Start VibezCut from the normal shortcut. Every start is ready for Claude to edit live in the window
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
