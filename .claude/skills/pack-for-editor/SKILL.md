---
name: pack-for-editor
description: Pack the project open in VibezCut into one zip for a remote editor (media with relative paths, handoff notes, script and cut files). Use when the user says /pack-for-editor, "pack this for the editor", "send this project to my editor" or wants a shareable zip of the project.
---

Pack the project that is open in the Claude-connected VibezCut window so a remote editor can unzip it on
another PC and carry on. Work quickly, do not ask questions unless something blocks you, and do every step
with the filmcraft-studio tools on the open project (not copies, not the CLI).

Editor notes from the user: anything they typed after `/pack-for-editor` (may be empty).

1. `fc_status()`. If VibezCut is not reachable, ask the user to open VibezCut and stop. If the open project
   has unsaved changes, save it with `fc_save()` (the pack is made from the saved file). If it was never
   saved, ask the user to save it first and stop.
2. `fc_preflight()`. Report any issue; continue unless a file is missing.
3. Find the files that explain the edit:
   - the project's own folder (from `fc_status().file`);
   - the raw recording(s): read the media paths in the .fcproj (JSON: `project.items.*.kind.Media.media.File.path`);
     for each raw, the studio work folder `<raw folder>/_studio/<raw file name without extension>/`, and from it
     `units.json`, `verify.txt` and `transcript.txt` when they exist;
   - next to the project: `edit.json`, and any `script*.txt` / `assets/script*.txt` / `assets/*.py`.
   Only include files that exist.
4. Write the notes for HANDOFF.md: start with the user's notes above (if any), then add what you know from
   this conversation or an existing `handoff/` folder next to the project: what the video is (sponsor, format,
   length), what is done (cut, graphics, audio changes) and what is next. Keep it short and factual.
5. `fc_pack(out_dir=<project folder>, name="<project name> - For Editor", include_media=True, proxy_preset="",
   notes=<notes>, extras=<files from step 3>)`. If the raw media is bigger than 3 GB use `wait=False` and follow
   it with `fc_pack_status(job)`. If the drive lacks space, say so and suggest another drive.
6. Check the zip: it opens (Python `zipfile` `testzip()` is None), the project inside has only relative media
   paths (`media/...`), and `handoff/HANDOFF.md` is there.
7. Report in a few lines: the zip path and size, what is inside, and the editor's three steps:
   unzip anywhere; open the .fcproj in VibezCut; in Claude Code say "connect to VibezCut and read the handoff".
