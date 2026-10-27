"""House style: dark, minimal, one accent colour. Edit here, not per video."""

WHITE = "#F5F6F8"
ACCENT = "#C8F040"      # lime
ACCENT_2 = "#6CF5C8"    # mint
GREY = "#96999F"

TEXT_DEFAULTS = {
    "font": "Inter", "style": "Bold", "size": 92, "align": "left", "color": WHITE,
    "accent": [], "accentColor": ACCENT, "shadow": True,
    "fadeIn": 0.3, "fadeOut": 0.22, "rise": 18,
}
BAR_DEFAULTS = {"w": 90, "h": 6, "color": ACCENT}

# talking-head text block: lower-left, lines stacked from y=690
BLOCK = {"x": 120, "top": 690, "line_height": 1.18, "bar": {"x": 165, "y": 653}}

# camera ladder (scale 1.0 = 100 %)
CAMERA = {"glide_in": [1.0, 1.08], "punch": 1.18, "out_from": 1.22, "max": 1.25}

# audio mix targets relative to the voice
MIX = {"music_db_under_voice": -18, "sfx_whoosh_gain": 2600}


def text_block(t_in, t_out, lines, size=92, track0=3, bar_track=5):
    """lines: [(text, appear_time, [accent substrings]), ...] -> (texts, bar) specs for edit.json"""
    texts, y = [], BLOCK["top"] + size * 0.85
    for k, (txt, ta, acc) in enumerate(lines):
        texts.append({"track": track0 + k, "t0": ta, "t1": t_out, "text": txt, "x": BLOCK["x"], "y": round(y, 1),
                      "size": size, "align": "left", "accent": list(acc)})
        y += size * BLOCK["line_height"]
    bar = {"track": bar_track, "t0": t_in + 0.05, "t1": t_out, **BLOCK["bar"]}
    return texts, bar
