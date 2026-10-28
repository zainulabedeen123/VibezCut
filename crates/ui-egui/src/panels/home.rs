//! Home (VibezCut): the projects screen VibezCut opens on. The recent projects as cards, newest
//! first (thumbnail, name, media size and duration); a click opens one. A wide "New project" bar
//! and "Open project…" sit above the grid.
//!
//! Thumbnails and durations come from a background thread that opens each project in its own
//! headless session (no settings path, so the user's recent list and preferences are never
//! written) and renders one small frame. They are cached in `<data dir>/home-thumbs/` by project
//! path and modification time, so a re-saved project gets a fresh card.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::sync::{Mutex, OnceLock, PoisonError};

use egui::{Align2, Color32, Rect, Sense, Stroke, StrokeKind, pos2, vec2};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::FilmcraftApp;
use crate::theme::Tokens;

/// The most projects Home lists.
pub const MAX_PROJECTS: usize = 50;
const CARD_W: f32 = 228.0;
const THUMB_H: f32 = CARD_W * 9.0 / 16.0;
const CARD_H: f32 = THUMB_H + 50.0;
const GAP: f32 = 18.0;
const MARGIN: f32 = 28.0;
/// Width of a cached thumbnail, in pixels.
const THUMB_W: u32 = 400;
/// Bump when the cache format or the picked frame changes.
const CACHE_VERSION: u32 = 1;

/// What a card shows besides the picture.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Meta {
    pub version: u32,
    /// Modification time of the project file (seconds since the Unix epoch).
    pub mtime: u64,
    /// The project file plus the media files it uses that exist on this computer.
    pub bytes: u64,
    /// Duration of the active sequence.
    pub seconds: f64,
}

struct Done {
    path: String,
    meta: Option<Meta>,
    rgba: Option<(u32, u32, Vec<u8>)>,
}

#[derive(Default)]
struct HomeState {
    meta: HashMap<String, Meta>,
    tex: HashMap<String, egui::TextureHandle>,
    requested: HashSet<String>,
    tx: Option<Sender<String>>,
    rx: Option<Receiver<Done>>,
    scroll: f32,
}

fn state() -> &'static Mutex<HomeState> {
    static S: OnceLock<Mutex<HomeState>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(HomeState::default()))
}

/// "1.4 GB", "258 MB", "69 KB".
pub fn format_size(bytes: u64) -> String {
    let b = bytes as f64;
    if b >= 1e9 {
        format!("{:.1} GB", b / 1e9)
    } else if b >= 1e6 {
        format!("{:.0} MB", b / 1e6)
    } else {
        format!("{:.0} KB", (b / 1e3).max(1.0))
    }
}

/// "10:25", "1:02:07".
pub fn format_duration(seconds: f64) -> String {
    let s = if seconds.is_finite() { seconds.max(0.0).round() as u64 } else { 0 };
    let (h, m, sec) = (s / 3600, (s / 60) % 60, s % 60);
    if h > 0 { format!("{h}:{m:02}:{sec:02}") } else { format!("{m:02}:{sec:02}") }
}

fn stamp(path: &Path) -> Option<(u64, u64)> {
    let md = std::fs::metadata(path).ok()?;
    let mtime = md.modified().ok()?.duration_since(std::time::UNIX_EPOCH).ok()?.as_secs();
    Some((mtime, md.len()))
}

/// Cache file stem for a project path (FNV-1a of the lower-cased path).
pub fn cache_key(path: &str) -> String {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in path.to_lowercase().bytes() {
        h ^= u64::from(b);
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    format!("{h:016x}")
}

fn cache_dir() -> Option<PathBuf> {
    let d = filmcraft_engine::autosave::default_data_dir()?.join("home-thumbs");
    std::fs::create_dir_all(&d).ok()?;
    Some(d)
}

/// The media files a saved project uses (`project.items.*.kind.Media.media.File.path`), resolved
/// against the project's folder.
fn media_paths(doc: &serde_json::Value, base: &Path) -> Vec<PathBuf> {
    let Some(items) = doc.pointer("/project/items").and_then(|v| v.as_object()) else { return Vec::new() };
    items
        .values()
        .filter_map(|it| it.pointer("/kind/Media/media/File/path").and_then(|p| p.as_str()))
        .map(|p| if Path::new(p).is_absolute() { PathBuf::from(p) } else { base.join(p) })
        .collect()
}

/// Card data for one project: from the cache when it is current, else by opening the project
/// headless and rendering one small frame (written to the cache).
fn make(path: &str) -> Done {
    let none = Done { path: path.to_string(), meta: None, rgba: None };
    let p = Path::new(path);
    let Some((mtime, len)) = stamp(p) else { return none };
    let dir = cache_dir();
    let key = cache_key(path);
    if let Some(d) = &dir {
        let cached: Option<Meta> = std::fs::read(d.join(format!("{key}.json"))).ok().and_then(|b| serde_json::from_slice(&b).ok());
        if let Some(m) = cached.filter(|m| m.mtime == mtime && m.version == CACHE_VERSION) {
            let rgba = std::fs::read(d.join(format!("{key}.png"))).ok().and_then(|b| image::load_from_memory(&b).ok()).map(|img| {
                let img = img.to_rgba8();
                (img.width(), img.height(), img.into_raw())
            });
            return Done { path: path.to_string(), meta: Some(m), rgba };
        }
    }
    // media size, from the file itself (cheap and independent of the engine)
    let base = p.parent().unwrap_or(Path::new("."));
    let doc: Option<serde_json::Value> = std::fs::read(p).ok().and_then(|b| serde_json::from_slice(&b).ok());
    let mut seen = HashSet::new();
    let media: u64 = doc
        .as_ref()
        .map(|d| media_paths(d, base))
        .unwrap_or_default()
        .into_iter()
        .filter(|m| seen.insert(m.clone()))
        .filter_map(|m| std::fs::metadata(m).ok().map(|md| md.len()))
        .sum();
    let mut meta = Meta { version: CACHE_VERSION, mtime, bytes: len.saturating_add(media), seconds: 0.0 };
    // one frame of the active sequence, in a session of its own
    let mut s = filmcraft_engine::Session::default();
    let mut rgba = None;
    if s.execute("file.open", json!({"path": path})).is_ok()
        && let Some((dur, w)) = s.active_sequence().map(|q| (q.duration(), q.settings.width))
    {
        meta.seconds = dur.seconds();
        let at = if meta.seconds.is_finite() { (meta.seconds * 0.1).clamp(0.0, 5.0) } else { 0.0 };
        let t = filmcraft_time::Tick::from_seconds_f64(at);
        s.set_playhead(t);
        let scale = (THUMB_W as f32 / w.max(1) as f32).clamp(0.02, 1.0);
        if let Ok((img, _offline)) = s.try_render_program_with_offline_at(scale, t) {
            let (w, h) = (img.w as u32, img.h as u32);
            rgba = Some((w, h, img.over_black_rgba8()));
        }
    }
    if let Some(d) = &dir {
        if let Some((w, h, px)) = &rgba
            && let Some(buf) = image::RgbaImage::from_raw(*w, *h, px.clone())
        {
            let mut png = std::io::Cursor::new(Vec::new());
            if buf.write_to(&mut png, image::ImageFormat::Png).is_ok() {
                let _ = std::fs::write(d.join(format!("{key}.png")), png.into_inner());
            }
        }
        if let Ok(j) = serde_json::to_vec(&meta) {
            let _ = std::fs::write(d.join(format!("{key}.json")), j);
        }
    }
    Done { path: path.to_string(), meta: Some(meta), rgba }
}

/// Ask the background thread for a card (once per path and session of the app).
fn request(st: &mut HomeState, ctx: &egui::Context, path: &str) {
    if !st.requested.insert(path.to_string()) {
        return;
    }
    if st.tx.is_none() {
        let (req_tx, req_rx) = channel::<String>();
        let (done_tx, done_rx) = channel::<Done>();
        let ctx = ctx.clone();
        let spawned = std::thread::Builder::new().name("home-thumbs".into()).spawn(move || {
            for path in req_rx {
                // a project the engine cannot open must not take the thread (and Home) down
                let done = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| make(&path))).unwrap_or_else(|_| Done {
                    path: path.clone(),
                    meta: None,
                    rgba: None,
                });
                if done_tx.send(done).is_err() {
                    break;
                }
                ctx.request_repaint();
            }
        });
        if spawned.is_err() {
            return;
        }
        st.tx = Some(req_tx);
        st.rx = Some(done_rx);
    }
    if let Some(tx) = &st.tx {
        let _ = tx.send(path.to_string());
    }
}

fn receive(st: &mut HomeState, ctx: &egui::Context) {
    let Some(rx) = &st.rx else { return };
    let done: Vec<Done> = rx.try_iter().collect();
    for d in done {
        if let Some(m) = d.meta {
            st.meta.insert(d.path.clone(), m);
        }
        if let Some((w, h, px)) = d.rgba
            && px.len() == (w as usize) * (h as usize) * 4
        {
            let img = egui::ColorImage::from_rgba_unmultiplied([w as usize, h as usize], &px);
            st.tex.insert(d.path.clone(), ctx.load_texture(format!("home-thumb-{}", cache_key(&d.path)), img, egui::TextureOptions::LINEAR));
        }
    }
}

/// When a card's project was saved again since its picture was made: make it again.
fn refresh_if_stale(st: &mut HomeState, path: &str) {
    if let (Some(m), Some((mtime, _))) = (st.meta.get(path), stamp(Path::new(path)))
        && m.mtime != mtime
    {
        st.requested.remove(path);
        st.meta.remove(path);
    }
}

pub fn show(app: &mut FilmcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    let ctx = ui.ctx().clone();
    ui.painter().rect_filled(rect, t.radius, t.panel_bg);
    let mut guard = state().lock().unwrap_or_else(PoisonError::into_inner);
    let st = &mut *guard;
    receive(st, &ctx);

    // New project bar
    let bar = Rect::from_min_size(rect.min + vec2(MARGIN, 24.0), vec2((rect.width() - 2.0 * MARGIN).max(200.0), 86.0));
    let bresp = ui.interact(bar, egui::Id::new("home-new"), Sense::click());
    app.auto.add("home.new", bar, "New project");
    let (a, b) = if bresp.hovered() { (t.accent_hover, Color32::from_rgb(60, 205, 210)) } else { (t.accent, Color32::from_rgb(34, 195, 198)) };
    paint_gradient(ui.painter(), bar, a, b, 12.0);
    let label = ui.painter().layout_no_wrap(tl!("New project").to_string(), Tokens::semibold(20.0), Color32::WHITE);
    let lw = label.size().x + 34.0;
    let lx = bar.center().x - lw / 2.0;
    crate::icons::paint(ui.painter(), Rect::from_center_size(pos2(lx + 11.0, bar.center().y), vec2(22.0, 22.0)), crate::icons::Icon::Plus, Color32::WHITE);
    ui.painter().galley(pos2(lx + 34.0, bar.center().y - label.size().y / 2.0), label, Color32::WHITE);

    // Projects header + Open project…
    let hy = bar.max.y + 34.0;
    let paths: Vec<String> = app.session.prefs.general.recent_projects.iter().take(MAX_PROJECTS).cloned().collect();
    ui.painter().text(pos2(rect.min.x + MARGIN, hy), Align2::LEFT_CENTER, tl!("Projects"), Tokens::semibold(17.0), t.text);
    let open_g = ui.painter().layout_no_wrap(tl!("Open project…").to_string(), Tokens::ui(13.0), t.text);
    let open_r = Rect::from_min_size(pos2(rect.max.x - MARGIN - open_g.size().x - 28.0, hy - 15.0), vec2(open_g.size().x + 28.0, 30.0));
    let oresp = ui.interact(open_r, egui::Id::new("home-open"), Sense::click());
    app.auto.add("home.open", open_r, "Open project…");
    ui.painter().rect_filled(open_r, 6.0, if oresp.hovered() { t.hover } else { t.tl_header_bg });
    ui.painter().galley(pos2(open_r.min.x + 14.0, open_r.center().y - open_g.size().y / 2.0), open_g, t.text);

    // the grid (scrolls with the wheel)
    let grid = Rect::from_min_max(pos2(rect.min.x + MARGIN, hy + 26.0), pos2(rect.max.x - MARGIN, rect.max.y - 12.0));
    let cols = (((grid.width() + GAP) / (CARD_W + GAP)).floor() as usize).max(1);
    let rows = paths.len().div_ceil(cols);
    let content_h = rows as f32 * (CARD_H + GAP);
    let max_scroll = (content_h - grid.height()).max(0.0);
    if ui.rect_contains_pointer(grid) {
        st.scroll -= ui.input(|i| i.smooth_scroll_delta.y);
    }
    st.scroll = st.scroll.clamp(0.0, max_scroll);
    let painter = ui.painter().with_clip_rect(grid);
    if paths.is_empty() {
        painter.text(
            pos2(grid.min.x, grid.min.y + 30.0),
            Align2::LEFT_CENTER,
            tl!("No projects yet: create one, or open a .fcproj file."),
            Tokens::ui(13.0),
            t.text_dim,
        );
    }
    let mut open: Option<String> = None;
    for (i, path) in paths.iter().enumerate() {
        let (c, r) = (i % cols, i / cols);
        let card = Rect::from_min_size(pos2(grid.min.x + c as f32 * (CARD_W + GAP), grid.min.y + r as f32 * (CARD_H + GAP) - st.scroll), vec2(CARD_W, CARD_H));
        if card.max.y < grid.min.y || card.min.y > grid.max.y {
            continue;
        }
        let exists = Path::new(path).is_file();
        if exists {
            refresh_if_stale(st, path);
            if !st.meta.contains_key(path) {
                request(st, &ctx, path);
            }
        }
        let visible = card.intersect(grid);
        let resp = ui.interact(visible, egui::Id::new(("home-card", i)), Sense::click()).on_hover_text(path.as_str());
        let name = Path::new(path).file_stem().map_or_else(|| path.clone(), |s| s.to_string_lossy().into_owned());
        app.auto.add(&format!("home.project.{i}"), visible, &name);
        let thumb = Rect::from_min_size(card.min, vec2(CARD_W, THUMB_H));
        if let Some(tex) = st.tex.get(path) {
            let uv = cover_uv(tex.size_vec2(), thumb.size());
            painter.add(egui::epaint::RectShape::filled(thumb, 8.0, Color32::WHITE).with_texture(tex.id(), uv));
        } else {
            painter.rect_filled(thumb, 8.0, t.tl_header_bg);
            crate::icons::paint(&painter, Rect::from_center_size(thumb.center(), vec2(34.0, 34.0)), crate::icons::Icon::Film, t.text_dim);
        }
        if resp.hovered() && exists {
            painter.rect_stroke(thumb, 8.0, Stroke::new(2.0, t.accent), StrokeKind::Inside);
        }
        if !exists {
            painter.rect_filled(thumb, 8.0, Color32::from_black_alpha(150));
        }
        let name_r = Rect::from_min_size(pos2(card.min.x, thumb.max.y + 8.0), vec2(CARD_W, 18.0));
        painter.with_clip_rect(name_r.intersect(grid)).text(name_r.left_center(), Align2::LEFT_CENTER, &name, Tokens::semibold(13.0), t.text);
        let sub = if !exists {
            tl!("File not found").to_string()
        } else if let Some(m) = st.meta.get(path) {
            format!("{} | {}", format_size(m.bytes), format_duration(m.seconds))
        } else {
            "…".to_string()
        };
        painter.text(pos2(card.min.x, thumb.max.y + 30.0), Align2::LEFT_CENTER, sub, Tokens::ui(11.5), if exists { t.text_dim } else { t.danger });
        if resp.clicked() && exists {
            open = Some(path.clone());
        }
    }
    drop(guard);

    if bresp.clicked() {
        if crate::menus::invoke(app, &ctx, "file.newProject", json!({})).is_ok() {
            app.ui.mode = crate::state::Mode::Edit;
        }
    } else if oresp.clicked() {
        if crate::menus::invoke(app, &ctx, "file.open", json!({})).is_ok() {
            app.ui.mode = crate::state::Mode::Edit;
        }
    } else if let Some(path) = open
        && crate::menus::invoke(app, &ctx, "file.open", json!({"path": path})).is_ok()
    {
        app.ui.mode = crate::state::Mode::Edit;
    }
}

/// UV rectangle that makes a picture of `tex` size cover `area` (centre crop, no stretching).
fn cover_uv(tex: egui::Vec2, area: egui::Vec2) -> Rect {
    if tex.x <= 0.0 || tex.y <= 0.0 || area.x <= 0.0 || area.y <= 0.0 {
        return Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0));
    }
    let (ta, aa) = (tex.x / tex.y, area.x / area.y);
    if ta > aa {
        let w = aa / ta;
        Rect::from_min_max(pos2((1.0 - w) / 2.0, 0.0), pos2((1.0 + w) / 2.0, 1.0))
    } else {
        let h = ta / aa;
        Rect::from_min_max(pos2(0.0, (1.0 - h) / 2.0), pos2(1.0, (1.0 + h) / 2.0))
    }
}

/// A rounded bar with a left-to-right gradient (`a` → `b`).
fn paint_gradient(p: &egui::Painter, r: Rect, a: Color32, b: Color32, radius: f32) {
    p.rect_filled(r, radius, a);
    let steps = 24;
    let inner = r.shrink2(vec2(radius, 0.0));
    for k in 0..steps {
        let f = k as f32 / (steps - 1) as f32;
        let x0 = inner.min.x + inner.width() * k as f32 / steps as f32;
        let x1 = inner.min.x + inner.width() * (k + 1) as f32 / steps as f32 + 0.5;
        let c = lerp(a, b, f);
        p.rect_filled(Rect::from_min_max(pos2(x0, r.min.y), pos2(x1, r.max.y)), 0.0, c);
    }
    p.rect_filled(Rect::from_min_max(pos2(inner.max.x - 1.0, r.min.y), r.max), radius, b);
}

fn lerp(a: Color32, b: Color32, f: f32) -> Color32 {
    let m = |x: u8, y: u8| (f32::from(x) + (f32::from(y) - f32::from(x)) * f).round().clamp(0.0, 255.0) as u8;
    Color32::from_rgb(m(a.r(), b.r()), m(a.g(), b.g()), m(a.b(), b.b()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sizes_and_durations_read_like_capcut() {
        assert_eq!(format_size(1_400_000_000), "1.4 GB");
        assert_eq!(format_size(258_300_000), "258 MB");
        assert_eq!(format_size(69_000), "69 KB");
        assert_eq!(format_size(0), "1 KB");
        assert_eq!(format_duration(625.0), "10:25");
        assert_eq!(format_duration(3727.0), "1:02:07");
        assert_eq!(format_duration(f64::NAN), "00:00");
    }

    #[test]
    fn cache_key_ignores_case_and_differs_by_path() {
        assert_eq!(cache_key(r"G:\A\b.fcproj"), cache_key(r"g:\a\B.FCPROJ"));
        assert_ne!(cache_key(r"G:\A\b.fcproj"), cache_key(r"G:\A\c.fcproj"));
    }

    #[test]
    fn cover_uv_crops_without_stretching() {
        let uv = cover_uv(vec2(1920.0, 1080.0), vec2(228.0, 128.25));
        assert!((uv.width() - 1.0).abs() < 1e-3 && (uv.height() - 1.0).abs() < 1e-3);
        let tall = cover_uv(vec2(1080.0, 1920.0), vec2(160.0, 90.0));
        assert!(tall.width() > 0.99 && tall.height() < 0.5, "{tall:?}");
    }

    #[test]
    fn media_paths_resolve_relative_paths_against_the_project() {
        let doc = json!({"project": {"items": {
            "1": {"kind": {"Media": {"media": {"File": {"path": "media/a.mp4"}}}}},
            "2": {"kind": {"Media": {"media": {"File": {"path": r"C:\x\b.wav"}}}}},
            "3": {"kind": {"Sequence": {}}}
        }}});
        let mut got = media_paths(&doc, Path::new(r"D:\proj"));
        got.sort();
        assert_eq!(got.len(), 2);
        assert!(got.iter().any(|p| p.ends_with("a.mp4") && p.starts_with(r"D:\proj")));
    }

    /// On a real project: `FILMCRAFT_HOME_TEST_PROJECT=<path.fcproj> cargo test -p filmcraft-ui-egui --lib
    /// home_card_of_a_real_project -- --ignored` (writes the picture to `<temp>/home-card.png`).
    #[test]
    #[ignore = "needs a real project: FILMCRAFT_HOME_TEST_PROJECT"]
    fn home_card_of_a_real_project() {
        let Ok(path) = std::env::var("FILMCRAFT_HOME_TEST_PROJECT") else { return };
        let d = make(&path);
        let m = d.meta.expect("a card");
        let (w, h, px) = d.rgba.expect("a picture");
        println!("{} | {} | {w}x{h}", format_size(m.bytes), format_duration(m.seconds));
        assert!(m.seconds > 0.0 && w > 0 && h > 0);
        let img = image::RgbaImage::from_raw(w, h, px).expect("rgba");
        img.save(std::env::temp_dir().join("home-card.png")).expect("png");
    }

    #[test]
    fn a_missing_project_makes_an_empty_card() {
        let d = make(r"Z:\definitely\not\here.fcproj");
        assert!(d.meta.is_none() && d.rgba.is_none());
    }
}
