//! VibezCut ⇄ Claude indicators: the window Claude works with shows it.
//!
//! * a soft glow in Claude's colour around the window while a Claude conversation is connected,
//! * "● Claude" in the window title (and the app adds a Claude dot on the taskbar button),
//! * a badge in the header (where FilmCraft had its Discord button): Connected, Ready, or "Claude:
//!   other window" with a click to connect Claude here (`claude.connectHere`).
//!
//! The link itself lives in the desktop app (`claude_link.rs`); it reports through
//! `filmcraft_engine::vibezcut::claude_link()`. Automation id: `header.claude`.

use egui::{Color32, Rect, Sense, Stroke, pos2, vec2};
use filmcraft_engine::vibezcut::{self, ClaudeLink};

use crate::FilmcraftApp;
use crate::theme::Tokens;

pub fn claude_color(alpha: u8) -> Color32 {
    let [r, g, b] = vibezcut::CLAUDE_RGB;
    Color32::from_rgba_unmultiplied(r, g, b, alpha)
}

/// Once per frame: the window glow, the title, a status line when the link changes.
pub fn frame(app: &mut FilmcraftApp, ctx: &egui::Context) {
    let link = vibezcut::claude_link();
    let last_id = egui::Id::new("vibezcut.claude.last");
    let last: Option<ClaudeLink> = ctx.data(|d| d.get_temp(last_id));
    if last != Some(link) {
        ctx.data_mut(|d| d.insert_temp(last_id, link));
        let title = match link {
            ClaudeLink::Connected => format!("{} {}  ● Claude", vibezcut::NAME, vibezcut::VERSION),
            _ => format!("{} {}", vibezcut::NAME, vibezcut::VERSION),
        };
        ctx.send_viewport_cmd(egui::ViewportCommand::Title(title));
        if last.is_some() {
            app.ui.status = match link {
                ClaudeLink::Connected => tl!("Connected to Claude").to_string(),
                ClaudeLink::Ready if last == Some(ClaudeLink::Connected) => tl!("Claude disconnected").to_string(),
                ClaudeLink::Ready => tl!("Claude now works with this window").to_string(),
                ClaudeLink::Standby if last != Some(ClaudeLink::Off) => tl!("Claude now works with another VibezCut window").to_string(),
                _ => std::mem::take(&mut app.ui.status),
            };
        }
    }
    // the glow fades in and out (repaints only while it animates)
    let on = ctx.animate_bool_with_time(egui::Id::new("vibezcut.claude.glow"), link == ClaudeLink::Connected, 0.35);
    if on <= 0.0 {
        return;
    }
    let r = ctx.content_rect();
    let p = ctx.layer_painter(egui::LayerId::new(egui::Order::Foreground, egui::Id::new("vibezcut.claude.glow")));
    const RINGS: usize = 9;
    for i in 0..RINGS {
        let k = 1.0 - i as f32 / RINGS as f32;
        let alpha = (on * 150.0 * k * k) as u8;
        p.rect_stroke(r.shrink(0.5 + i as f32), 0.0, Stroke::new(1.0, claude_color(alpha)), egui::StrokeKind::Inside);
    }
}

/// The header badge, right-aligned at `right`. Returns its rect (`None`: no link in this build).
pub fn header_badge(app: &mut FilmcraftApp, ui: &mut egui::Ui, right: f32, center_y: f32) -> Option<Rect> {
    let link = vibezcut::claude_link();
    if link == ClaudeLink::Off {
        return None;
    }
    let t = app.tokens;
    let (label, tip) = match link {
        ClaudeLink::Connected => {
            let n = vibezcut::claude_conversations();
            let tip = if n > 1 {
                tlf!("Connected to Claude ({n} conversations). Claude can edit this window; every change is a normal undo step.", n = n)
            } else {
                tl!("Connected to Claude. Claude can edit this window; every change is a normal undo step.").to_string()
            };
            (tl!("Claude").to_string(), tip)
        }
        ClaudeLink::Ready => (tl!("Claude").to_string(), tl!("Ready for Claude: a Claude conversation that uses VibezCut connects to this window.").to_string()),
        _ => (tl!("Claude: other window").to_string(), tl!("Claude works with another VibezCut window. Click to connect Claude to this window.").to_string()),
    };
    let p = ui.painter().clone();
    let g = p.layout_no_wrap(label, Tokens::ui(12.0), Color32::WHITE);
    let w = g.size().x + 30.0;
    let r = Rect::from_min_size(pos2(right - w, center_y - 12.0), vec2(w, 24.0));
    let resp = ui.interact(r, egui::Id::new("hdr-claude"), Sense::click()).on_hover_text(tip);
    app.auto.add("header.claude", r, "Claude");
    let dot = pos2(r.min.x + 13.0, r.center().y);
    let text_color = match link {
        ClaudeLink::Connected => {
            p.rect_filled(r, 12.0, claude_color(if resp.hovered() { 255 } else { 235 }));
            p.circle_filled(dot, 4.0, Color32::WHITE);
            Color32::WHITE
        }
        ClaudeLink::Ready => {
            p.rect_stroke(r, 12.0, Stroke::new(1.0, claude_color(if resp.hovered() { 255 } else { 170 })), egui::StrokeKind::Inside);
            p.circle_stroke(dot, 3.5, Stroke::new(1.5, claude_color(220)));
            t.text
        }
        _ => {
            p.rect_stroke(r, 12.0, Stroke::new(1.0, if resp.hovered() { t.text_dim } else { t.text_dim.gamma_multiply(0.5) }), egui::StrokeKind::Inside);
            p.circle_stroke(dot, 3.5, Stroke::new(1.5, t.text_dim));
            t.text_dim
        }
    };
    p.galley_with_override_text_color(pos2(r.min.x + 23.0, r.center().y - g.size().y / 2.0), g, text_color);
    if resp.clicked() && link == ClaudeLink::Standby {
        let _ = crate::menus::invoke(app, ui.ctx(), "claude.connectHere", serde_json::json!({}));
    }
    Some(r)
}
