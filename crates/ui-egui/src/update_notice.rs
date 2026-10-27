//! "Update ready" notice (VibezCut): a small card in the bottom-right corner when the background
//! updater has downloaded a newer version. Restart hands over to the updater and quits through the
//! normal path (unsaved changes are offered for saving); Later hides it, and the update installs
//! on the next start anyway.
//!
//! Automation ids: `update.restart`, `update.later`.

use crate::FilmcraftApp;
use filmcraft_engine::vibezcut;
use serde_json::json;

pub fn show(app: &mut FilmcraftApp, ctx: &egui::Context) {
    let Some(version) = vibezcut::update_ready() else {
        return;
    };
    let t = app.tokens;
    egui::Area::new(egui::Id::new("vibezcut.update_notice"))
        .anchor(egui::Align2::RIGHT_BOTTOM, egui::vec2(-16.0, -40.0))
        .order(egui::Order::Foreground)
        .show(ctx, |ui| {
            egui::Frame::popup(ui.style()).inner_margin(egui::Margin::same(12)).show(ui, |ui| {
                ui.set_width(280.0);
                ui.label(egui::RichText::new(tlf!("{name} {version} is ready", name = vibezcut::NAME, version)).strong());
                ui.label(egui::RichText::new(tl!("Restart to install it. Your project is offered for saving first.")).small().color(t.text_dim));
                ui.add_space(6.0);
                ui.horizontal(|ui| {
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
                });
            });
        });
}
