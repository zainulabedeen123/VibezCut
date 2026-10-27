# Per-video workflow

## Who does what

| Step | Who | Tool |
|---|---|---|
| 1. Drop the raw recording (+ optional script) | You | a file path |
| 2. Transcribe verbatim | Claude | `studio_transcribe` |
| 3. Read the whole transcript, choose the best take of every line | Claude | `studio_read_transcript`, `studio_words` |
| 4. Save the takes, resolve frame-safe cuts | Claude | `studio_save_units`, `studio_resolve` |
| 5. Assemble, re-transcribe the full edit, fix anything flagged | Claude | `studio_assemble` |
| 6. Design graphics / music / SFX, write `edit.json` | Claude | `style.py`, `sound.py` |
| 7. Build the native FilmCraft project | Claude | `studio_build_project` |
| 8. Open, review, small tweaks, export | You | FilmCraft |
| 9. Revisions you ask for | Claude, live in your window | `fc_*` tools |
| 10. Final export | You | FilmCraft |

## Rules that keep it robust

**Cutting**
- Read the entire transcript before cutting. The script (if given) is for intent and order only;
  keep extra explanation that was said but not scripted.
- A unit is one sentence/clause from the best complete take. Prefer the cleanest delivery, not
  automatically the last attempt. Repeats inside one phrase get an `sw` start window so the cut lands
  on the last repeat; legit repetition ("then this clip, then this clip") gets `lenient`.
- Never cut inside a word. Cut points are only placed in quiet runs; ends are checked so trailing
  consonants (the "s" of "projects") survive.
- `studio_assemble` re-transcribes the whole edit with a verbatim prompt. Every issue it lists is
  checked and either fixed (re-resolve the unit, or a `removals` span) or confirmed intentional.

**Building**
- The first version is generated from `edit.json`. From then on, **the .fcproj is the master**:
  never regenerate it after you have touched it; revisions are targeted `fc_*` edits.
- Track layout: V1 Camera, V2 Backgrounds, V3 Artwork, V4-V5 Titles, V6 Accents; A1 Voice,
  A2 Music (sync lock off so dialogue trims don't fight the bed), A3 SFX as individual clips.
- Text is native FilmCraft text (Inter, house colours) so it stays retypable. Only artwork that
  FilmCraft can't draw (icon sets, glows) is imported as transparent PNG/MOV.
- The verbatim transcript is pushed into FilmCraft (Text panel) for text-based edits.

**Revising live**
- Open VibezCut normally. The window Claude works with has a **Claude** badge in its header; while a
  Claude conversation is connected the badge is orange, the window has a soft orange glow, the title
  says "● Claude" and the taskbar button has an orange dot. Other VibezCut windows say "Claude: other
  window"; click it (or Window > Connect Claude to This Window) to move Claude there.
- One conversation per project: a conversation that worked on one project won't edit another one
  you opened since; Claude asks which one you mean.
- Don't edit while Claude is applying a change; every change is one undo step (Ctrl+Z).
- Ripple trims are refused when a clip on a sync-locked track spans the cut (a title or SFX over the
  edit). Claude then trims that overlay too, or asks.
- Save in FilmCraft (or ask Claude: `fc_save`) when you're happy.

## Files per video

`<video folder>/_studio/<video name>/`: audio16k/48k.wav, db.npy, chunks.json, phrases.json,
transcript.txt, units.json, resolved.json, resolve.log, pieces.json, edit_audio.wav, verify.txt,
edit.json, music_bed.wav. The project is written next to the video.
