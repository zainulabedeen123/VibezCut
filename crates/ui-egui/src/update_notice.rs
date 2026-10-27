//! VibezCut update card, bottom-right: shown when a downloaded update is ready ("Restart to
//! update" / "Later"), and while a check the user asked for (Help ▸ Check for Updates) reports
//! progress: checking, up to date, downloading, failed, or not available for this copy.
//!
//! Automation ids: `update.restart`, `update.later`, `update.close`.

use crate::FilmcraftApp;
use filmcraft_engine::vibezcut::{self, UpdateState};
use serde_json::json;

pub fn show(app: &mut FilmcraftApp, ctx: &egui::Context) {
    let Some(state) = vibezcut::visible_update_state() else {
        return;
    };
    let t = app.tokens;
    egui::Area::new(egui::Id::new("vibezcut.update_notice"))
        .anchor(egui::Align2::RIGHT_BOTTOM, egui::vec2(-16.0, -40.0))
        .order(egui::Order::Foreground)
        .show(ctx, |ui| {
            egui::Frame::popup(ui.style()).inner_margin(egui::Margin::same(12)).show(ui, |ui| {
                ui.set_width(300.0);
                let (title, body) = match &state {
                    UpdateState::Ready(v) => (
                        tlf!("{name} {version} is ready", name = vibezcut::NAME, version = v),
                        tl!("Restart to install it. Your project is offered for saving first.").to_string(),
                    ),
                    UpdateState::Checking => (
                        tl!("Checking for updates…").to_string(),
                        tlf!("You have {name} {version}.", name = vibezcut::NAME, version = vibezcut::VERSION),
                    ),
                    UpdateState::Downloading(v) => (
                        tlf!("Downloading {name} {version}…", name = vibezcut::NAME, version = v),
                        tl!("You can keep working; this card tells you when it's ready.").to_string(),
                    ),
                    UpdateState::UpToDate => (
                        tl!("You're up to date").to_string(),
                        tlf!("{name} {version} is the latest version.", name = vibezcut::NAME, version = vibezcut::VERSION),
                    ),
                    UpdateState::Failed(e) => (tl!("Couldn't check for updates").to_string(), e.clone()),
                    UpdateState::Unavailable(e) => (tl!("Updates aren't available here").to_string(), e.clone()),
                    UpdateState::Idle => return,
                };
                ui.label(egui::RichText::new(title).strong());
                ui.label(egui::RichText::new(body).small().color(t.text_dim));
                ui.add_space(6.0);
                ui.horizontal(|ui| match state {
                    UpdateState::Ready(_) => {
                        let restart = ui.button(tl!("Restart to update"));
                        app.auto.add("update.restart", restart.rect, "Restart to update");
                        if restart.clicked() {
                            if vibezcut::prepare_restart_to_update() {
                                let _ = crate::menus::invoke(app, ctx, "app.quit", json!({}));
                            }
                            vibezcut::dismiss_update_notice();
                        }
                        let later = ui.button(tl!("Later"));
                        app.auto.add("update.later", later.rect, "Later");
                        if later.clicked() {
                            vibezcut::dismiss_update_notice();
                        }
                    }
                    UpdateState::Checking | UpdateState::Downloading(_) => {
                        ui.spinner();
                        ctx.request_repaint_after(std::time::Duration::from_millis(250));
                        let hide = ui.button(tl!("Hide"));
                        app.auto.add("update.close", hide.rect, "Hide");
                        if hide.clicked() {
                            vibezcut::dismiss_update_notice();
                        }
                    }
                    _ => {
                        let ok = ui.button(tl!("OK"));
                        app.auto.add("update.close", ok.rect, "OK");
                        if ok.clicked() {
                            vibezcut::dismiss_update_notice();
                        }
                    }
                });
            });
        });
}
