# VibezCut Studio

The editing workflow built into VibezCut:

- an **analysis pipeline** that turns a raw talking-head / screen-share recording into a clean cut
  (verbatim transcription, take selection, frame-safe cut points, verification),
- a **project builder** that writes a native, fully editable project (cuts, camera keyframes,
  native text graphics, music and individual SFX clips, the transcript in the Text panel),
- an **MCP server** (`filmcraft-studio`) so Claude can run the pipeline and revise the edit live in
  the open editor window, with every change a normal undoable step.

```
VibezCut/
├─ Start VibezCut (Claude control).bat    launch the editor with the control channel (fresh token)
├─ .mcp.json                              registers filmcraft-studio (and the upstream dev servers)
├─ .claude/skills/filmcraft-edit/         the editing skill for Claude
├─ docs/vibezcut/                         STUDIO.md (this file), WORKFLOW.md
├─ .github/upstream-workflows/            FilmCraft's own CI, parked (not run in this repo)
├─ apps/, crates/, …                      the editor (FilmCraft 0.13.0 source, MIT/Apache-2.0)
└─ studio/
   ├─ run_server.py                       MCP entry point
   ├─ studio.json                         per-machine settings (not committed)
   ├─ assets/sfx/                         synthesized SFX library (whoosh, tick, sub_hit, riser…)
   └─ studio/
      ├─ config.py      settings, editor binaries, per-video work folder
      ├─ fc.py          editor client: Headless (filmcraft-cli mcp) and Live (control channel)
      ├─ audio.py       audio extraction, loudness envelope, quiet runs, activity segmentation
      ├─ transcribe.py  verbatim Whisper (large-v3-turbo, GPU): chunks + phrases
      ├─ takes.py       chosen takes -> cut points (ASR judge + MMS forced alignment)
      ├─ assemble.py    pieces, dialogue render, whole-edit verification (repeats/restarts)
      ├─ build.py       edit.json -> native .fcproj
      ├─ style.py       house style (fonts, colours, text-block layout, camera ladder, mix)
      ├─ sound.py       SFX library, ambient music bed, level matching to the voice
      ├─ ops.py         revision operations (find/retype text, trim a cut, remove a range, gain…)
      └─ server.py      the MCP tools
```

## Setup (until the installer exists)

1. Editor binaries: either build this repo (`cargo build --release -p filmcraft -p filmcraft-cli`,
   Rust 1.95+) or point `studio/studio.json` at a FilmCraft 0.13.0 portable folder:
   `{"filmcraft_home": "C:\\path\\to\\filmcraft-0.13.0-windows-x64-portable"}`.
2. Python 3.12 with `faster-whisper`, `torch` + `torchaudio` (CUDA), `numpy`, `pillow`, `mcp`; `ffmpeg` on PATH.
3. Register the MCP server for every folder (use the full python.exe path on Windows; a bare
   `python` fails Claude Code's connection check):
   `claude mcp add --scope user filmcraft-studio -- "<python.exe>" "<repo>/studio/run_server.py"`.

## Live editing

On Windows every normal start of VibezCut can work with Claude (`apps/filmcraft/src/claude_link.rs`):

- One window at a time holds 127.0.0.1:9876 with a fresh 64-hex token, written to
  `%USERPROFILE%\.filmcraft-studio\control.token` (the MCP server reads it there, again after a refusal).
  When that window closes the next one takes over; Window > Connect Claude to This Window (or the header
  badge) writes a claim file and the holder hands over.
- A conversation keeps one connection open (`fc.keep_attached`: `vibezcut.attach`, then `vibezcut.ping`
  every 4 s). While one is open the window shows it: orange header badge, window glow, "● Claude" in
  the title, a Claude dot on the taskbar button (`crates/ui-egui/src/claude_indicator.rs`,
  `crates/platform/src/taskbar_overlay.rs`). It ends with the conversation's MCP server process.
- One conversation = one project (`server._check_project`): live edits are refused with "Project mismatch"
  when another project is open; `fc_open` / `fc_use_open_project` switch deliberately.
- `VIBEZCUT_NO_CLAUDE=1` turns it off. `Start VibezCut (Claude control).bat` (explicit `--control 9876`)
  still works, without the indicators.

## Builds and releases

- Local: `pwsh packaging/vibezcut/package.ps1 -Version 0.1.0` builds `VibezCut.exe` and
  `vibezcut-cli.exe` (static CRT) and writes `dist/vibezcut/VibezCut-<version>-windows-x64.zip`
  (+ `.sha256`): editor, CLI, launcher, `studio/`, docs, the Claude skill and the licenses.
- CI: `.github/workflows/vibezcut-release.yml`. Push a tag (`git tag vibezcut-v0.1.0 && git push origin vibezcut-v0.1.0`; plain `v*` tags are FilmCraft's)
  and GitHub Actions builds on Windows, smoke-tests the CLI and publishes a GitHub Release with the zip.
  "Run workflow" by hand gives a build artifact without a release.
- Installer and auto-update (Velopack): CI also runs `vpk pack` and `vpk upload github`, so every
  release carries `VibezCut-win-Setup.exe`, the full/delta `.nupkg` packages and the
  `releases.win.json` feed. Installed copies (`%LocalAppData%\VibezCut\current`) check the GitHub
  Releases at start (`apps/filmcraft/src/updater.rs`), download in the background and show
  "Restart to update" (`crates/ui-egui/src/update_notice.rs`); an update not applied by a restart is
  applied on the next start. After an install or update the app copies the Claude skill and
  re-registers the MCP server from its own folder. Editors: see [INSTALL.md](INSTALL.md).
- Branding lives in `crates/engine/src/vibezcut.rs` (name, version, data folder) and
  `assets/app-icon/vibezcut*`. Internal ids, the `.fcproj` format and interchange tags keep their
  FilmCraft names so projects stay compatible. Settings and auto-save go to `%APPDATA%\VibezCut`.

## Upstream

`upstream` = storytold/filmcraft (push disabled). Our `main` started at their `v0.13.0` release.
Merge their later releases deliberately (`git fetch upstream --tags && git merge v0.x.y`), keeping our
changes in separate modules where possible so merges stay small.

See [WORKFLOW.md](WORKFLOW.md) for the per-video workflow.
