# Caption templates

One JSON file per template; `studio_captions(video, template)` applies one to the open project (see `studio/studio/captions.py`).
Sizes are for a 1080-pixel short side and scale with the sequence.

| key | meaning |
|---|---|
| font, style | font family and style (the fonts bundled with VibezCut, see `packaging/vibezcut/fonts-lock.json`) |
| size, line_height, tracking | text size in px at 1080p, line spacing, letter spacing (1/1000 em) |
| case | `upper`, `lower` or `none`; `strip_punct` (default true) drops trailing . , ! ? |
| max_words, max_chars, words_per_line, first_line_words, break_gap, break_on_punct | how words are grouped into captions and lines (first_line_words: words on the first line only) |
| color, stroke {color, width}, shadow {color, opacity, distance, blur, angle} | the look |
| highlight | `none`, `word` (spoken word in highlight_color), `box` (box_color box behind the spoken word), `last_line` |
| highlight_mode | `reveal`: lines appear one by one (with `last_line`) |
| small_last_word, small_scale, small_max_chars | the group's last word small and raised after the line |
| animation | `pop`, `pop_rotate`, `scale_fade`, `fade`, `slide`, `none` |
| y, align, x, max_width | vertical centre (fraction of the height), `center` or `left` (x fraction), widest line |
