//! VibezCut branding: the product name, version and data folder shown to people, kept in one
//! place. VibezCut is built on FilmCraft; internal ids, file formats and interchange tags keep
//! their FilmCraft names so projects and exchange files stay compatible.

/// The product name shown in windows, menus and dialogs.
pub const NAME: &str = "VibezCut";
/// VibezCut's own release version (set by the release build from the git tag).
pub const VERSION: &str = match option_env!("VIBEZCUT_VERSION") {
    Some(v) => v,
    None => "0.1.0-dev",
};
/// The FilmCraft release this build is based on.
pub const BASED_ON: &str = concat!("FilmCraft ", env!("CARGO_PKG_VERSION"));
/// Folder name for settings, auto-save and logs (separate from an installed FilmCraft).
pub const DATA_DIR: &str = "VibezCut";
/// VibezCut's repository.
pub const REPOSITORY: &str = "https://github.com/zainulabedeen123/VibezCut";

// ------------------------------------------------------------------ updates
//
// The desktop app checks GitHub Releases in the background (Velopack, Windows). When a newer
// version has been downloaded it records it here; the UI shows a notice with "Restart to update",
// which runs the hook the app registered (it hands over to the updater, then the app quits through
// its normal path so unsaved changes are still offered for saving).

use std::sync::{Mutex, OnceLock, PoisonError};

static UPDATE_READY: Mutex<Option<String>> = Mutex::new(None);
static UPDATE_DISMISSED: Mutex<bool> = Mutex::new(false);
type Hook = Box<dyn Fn() -> bool + Send + Sync>;
static RESTART_HOOK: OnceLock<Hook> = OnceLock::new();

/// A downloaded update, version `version`, is ready to install.
pub fn set_update_ready(version: String) {
    *UPDATE_READY.lock().unwrap_or_else(PoisonError::into_inner) = Some(version);
}

/// The version of a downloaded update waiting to be installed, unless the user dismissed the notice.
pub fn update_ready() -> Option<String> {
    if *UPDATE_DISMISSED.lock().unwrap_or_else(PoisonError::into_inner) {
        return None;
    }
    UPDATE_READY.lock().unwrap_or_else(PoisonError::into_inner).clone()
}

/// Hide the notice for this session (the update still installs on the next start).
pub fn dismiss_update_notice() {
    *UPDATE_DISMISSED.lock().unwrap_or_else(PoisonError::into_inner) = true;
}

/// Registered once by the desktop app: prepares the updater to install when the app exits.
pub fn set_restart_hook(hook: Hook) {
    let _ = RESTART_HOOK.set(hook);
}

/// Prepare the update to be installed when the app exits (then restarted). `false` when there is no
/// hook (no updater in this build) or the updater could not be started.
pub fn prepare_restart_to_update() -> bool {
    RESTART_HOOK.get().is_some_and(|h| h())
}
