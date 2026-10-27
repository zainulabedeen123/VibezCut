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
8. Tell the user to open the .fcproj (or `fc_open` if FilmCraft runs with control).

## Revisions (project already delivered)
- Never regenerate from edit.json once the user has the project: the .fcproj is the master.
- Prefer live: `fc_status()`; if unreachable, ask the user to start FilmCraft with
  `Start VibezCut (Claude control).bat`, or edit the file headless (target = path) while it is closed.
- Typical: `fc_find_text` -> `fc_set_text`/`fc_style_text`; `fc_tighten_cut`; `fc_remove_range`;
  `fc_gain`; `fc_scale_keys`; check with `fc_frame`; `fc_undo` if wrong; `fc_save`.
- Anything else: `fc_command` with a FilmCraft command id (`filmcraft-cli commands` lists them).
