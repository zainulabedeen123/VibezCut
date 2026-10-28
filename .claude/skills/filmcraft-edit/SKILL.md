---
name: filmcraft-edit
description: Edit a raw talking-head / screen-share recording into a native FilmCraft project, and revise it live in the open FilmCraft window. Use when the user gives a video to edit, asks for cuts, graphics, music or changes to a FilmCraft project.
---

# FilmCraft Studio edit

Tools come from the `filmcraft-studio` MCP server (`studio_*` pipeline, `fc_*` FilmCraft).
Full rules: `docs/vibezcut/WORKFLOW.md` in the VibezCut repo. House style: `studio/studio/style.py`.

## New video
1. `studio_transcribe(video, terms="<product names>")`.
2. Read ALL of `studio_read_transcript` (page through it) before choosing anything. Use the script
   only for intent/order; keep unscripted explanation.
3. Pick the best complete take per sentence -> units `{text, k1, k2, sw?, ew?, fixS?, lenient?}`.
   For a repeat inside one phrase, set `sw` to the window holding the last repeat
   (`studio_words` shows word times and quiet runs). Skip fillers, false starts, chatter.
4. `studio_save_units`, then `studio_resolve`. Fix every BAD unit (adjust windows/text) and re-run with `only`.
5. `studio_assemble`. Check every listed issue; fix with re-resolved units or `removals`, repeat until clean.
6. Write `edit.json` (schema in `studio/studio/build.py`): camera moves, text blocks
   (`style.text_block`), stills, music bed (`sound.music_bed` + `sound.gain_under_voice`, -18 dB),
   individual `sfx` events. Keep it professional: no cartoon styling unless asked.
7. `studio_build_project`, then look at a few frames (`fc_frame` with the project path as target).
8. Open it in VibezCut with `fc_open(path)` (or tell the user to open the .fcproj).

## Handoff packs (sending a project to an editor, or receiving one)
- **Before an export or a pack** run `fc_preflight()`. VibezCut 0.2.10+ downscales a still over 16.8 MP when it loads
  it (the layout does not change); older versions need ~2 GB for a 16000 px PNG logo and abort on export. If the
  user is on an older version, replace such an image with a smaller copy (`ffmpeg -i big.png -vf scale=3840:-2
  small.png`, then Replace Footage). Exports use the hardware encoder and GPU compositing by default (Auto, with
  fallback); `hardwareEncoding: "off", gpuRendering: "off"` gives byte-identical output on every machine.
- **Sending**: the user asks to pack/send it. The project must be saved. `fc_pack(out_dir, notes=..., extras=[script,
  cut report, units.json…], download_urls={file: link})` writes `<out_dir>/<name>.zip` (media is streamed into it: one
  copy on disk; `keep_folder=True` also leaves the folder; it refuses early if the drive lacks space): the project with
  relative media paths, proxies, and `handoff/` (HANDOFF.md, manifest.json). Default `include_media=False`: the big
  full-resolution files stay out; tell the user which ones the editor must download into `media/`. Long footage:
  `wait=False` then `fc_pack_status(job)`. Put in `notes` what the editor needs: sponsor, what is done, what is next.
- **Receiving** (a project somebody else cut): FIRST call `fc_handoff()`. It returns HANDOFF.md, the changelog and
  which media is missing. Missing media: the files go in the `media` folder next to the project (then reopen), or
  `fc_relink(folder)` with the folder they were downloaded to. Do not re-transcribe the raw: the word-level
  transcript is already inside the project. At the end of a session call `fc_handoff(log="what you did / what is left")`.
- Proxies are for editing only; export always uses the full-resolution files, so the raw must be linked before export.
- **Client drafts**: for a quick review copy use `fc_command("file.exportMedia", {"preset": "Quick Preview 720p (fast draft)",
  "path": ...})` (720p, 30 fps, hardware encoder, GPU compositing: much faster than the final export). The final
  export uses a full-resolution preset such as `Match Source – Adaptive High Bitrate` or `YouTube 2160p 4K Ultra HD`.

## Revisions (project already delivered)
- Never regenerate from edit.json once the user has the project: the .fcproj is the master.
- Prefer live: `fc_status()`. Every normal VibezCut start works with Claude; the window Claude works
  with shows a Claude badge in its header (glowing orange while this conversation is connected). If
  unreachable, ask the user to open VibezCut, or edit the file headless (target = path) while it is closed.
  With several windows open: Window > Connect Claude to This Window moves Claude to that window.
- One conversation = one project. The first live call ties this conversation to the open project;
  later live edits are refused with "Project mismatch" when the user has opened another one. Then ask
  the user: `fc_open("<this conversation's project>")` goes back to it, `fc_use_open_project()` switches
  this conversation to the open one. Never work around the check.
- `fc_open` refuses when the open project has unsaved changes: ask the user, then
  `fc_open(path, save_current=True)` saves it first.
- `fc_set_text` is one undo step (text and timeline label together).
- Typical: `fc_find_text` -> `fc_set_text`/`fc_style_text`; `fc_tighten_cut`; `fc_remove_range`;
  `fc_gain`; `fc_scale_keys`; check with `fc_frame`; `fc_undo` if wrong; `fc_save`.
- Anything else: `fc_command` with a FilmCraft command id (`filmcraft-cli commands` lists them).
