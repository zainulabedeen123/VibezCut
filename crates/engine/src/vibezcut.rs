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
// The desktop app checks GitHub Releases (Velopack, Windows) at start and on Help > Check for
// Updates. It reports progress here; the UI shows a card (`update_notice`) and, when a version
// is ready, "Restart to update", which runs the restart hook the app registered (it hands over to
// the updater, then the app quits through its normal path so unsaved changes are offered for saving).

use std::sync::{Mutex, OnceLock, PoisonError};

/// Where the update check is.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum UpdateState {
    /// Nothing to report (no check yet, or the card was closed).
    Idle,
    Checking,
    UpToDate,
    /// Downloading this version.
    Downloading(String),
    /// This version is downloaded and installs on restart.
    Ready(String),
    /// The check or the download failed (the message says why).
    Failed(String),
    /// This copy can't update itself (not installed with Setup, or no updater in this build).
    Unavailable(String),
}

struct Updates {
    state: UpdateState,
    visible: bool,
}

static UPDATES: Mutex<Updates> = Mutex::new(Updates { state: UpdateState::Idle, visible: false });
type Hook = Box<dyn Fn() -> bool + Send + Sync>;
static RESTART_HOOK: OnceLock<Hook> = OnceLock::new();
static CHECK_HOOK: OnceLock<Hook> = OnceLock::new();

/// Record the update state. A ready update always shows the card; other states show it only
/// while a check the user asked for is on screen.
pub fn set_update_state(state: UpdateState) {
    let mut u = UPDATES.lock().unwrap_or_else(PoisonError::into_inner);
    if matches!(state, UpdateState::Ready(_)) {
        u.visible = true;
    }
    u.state = state;
}

/// The state to show in the update card, if it is visible.
pub fn visible_update_state() -> Option<UpdateState> {
    let u = UPDATES.lock().unwrap_or_else(PoisonError::into_inner);
    (u.visible && u.state != UpdateState::Idle).then(|| u.state.clone())
}

/// The version of a downloaded update waiting to be installed.
pub fn update_ready() -> Option<String> {
    match &UPDATES.lock().unwrap_or_else(PoisonError::into_inner).state {
        UpdateState::Ready(v) => Some(v.clone()),
        _ => None,
    }
}

/// Hide the card (a ready update still installs on the next start).
pub fn dismiss_update_notice() {
    UPDATES.lock().unwrap_or_else(PoisonError::into_inner).visible = false;
}

/// Registered once by the desktop app: prepares the updater to install when the app exits.
pub fn set_restart_hook(hook: Hook) {
    let _ = RESTART_HOOK.set(hook);
}

/// Registered once by the desktop app: starts a check in the background.
pub fn set_check_hook(hook: Hook) {
    let _ = CHECK_HOOK.set(hook);
}

/// Prepare the update to be installed when the app exits (then restarted). `false` when there is no
/// hook (no updater in this build) or the updater could not be started.
pub fn prepare_restart_to_update() -> bool {
    RESTART_HOOK.get().is_some_and(|h| h())
}

/// Help > Check for Updates: show the card and check now.
pub fn check_for_updates_now() {
    {
        let mut u = UPDATES.lock().unwrap_or_else(PoisonError::into_inner);
        u.visible = true;
        if !matches!(u.state, UpdateState::Ready(_) | UpdateState::Downloading(_)) {
            u.state = UpdateState::Checking;
        }
    }
    let started = CHECK_HOOK.get().is_some_and(|h| h());
    if !started && update_ready().is_none() {
        set_update_state(UpdateState::Unavailable(
            "This copy can't update itself. Install VibezCut with VibezCut-win-Setup.exe to get automatic updates.".into(),
        ));
    }
}

// ------------------------------------------------------------------ Claude link
//
// The desktop app (`apps/filmcraft/src/claude_link.rs`, Windows) keeps one VibezCut window linked
// to Claude: it holds the local control port the `filmcraft-studio` MCP server talks to. It reports
// the link here; the UI shows it (header badge, window glow, title) and "Connect Claude to This
// Window" asks for it through the claim hook.

use std::sync::atomic::{AtomicU8, AtomicUsize, Ordering};

/// Claude's colour (the indicator glow, the header badge, the taskbar dot).
pub const CLAUDE_RGB: [u8; 3] = [0xD9, 0x77, 0x57];

/// This window's link to Claude.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ClaudeLink {
    /// No link in this build or on this platform, or turned off (`VIBEZCUT_NO_CLAUDE`).
    Off,
    /// Another VibezCut window is the one Claude works with.
    Standby,
    /// Claude can work with this window; no Claude conversation is using it now.
    Ready,
    /// A Claude conversation is working with this window.
    Connected,
}

static CLAUDE_LINK: AtomicU8 = AtomicU8::new(0);
static CLAUDE_CONVERSATIONS: AtomicUsize = AtomicUsize::new(0);
type ClaimHook = Box<dyn Fn() + Send + Sync>;
static CLAIM_HOOK: OnceLock<ClaimHook> = OnceLock::new();

/// Record the link (and how many Claude conversations are attached).
pub fn set_claude_link(link: ClaudeLink, conversations: usize) {
    let v = match link {
        ClaudeLink::Off => 0,
        ClaudeLink::Standby => 1,
        ClaudeLink::Ready => 2,
        ClaudeLink::Connected => 3,
    };
    CLAUDE_CONVERSATIONS.store(conversations, Ordering::Relaxed);
    CLAUDE_LINK.store(v, Ordering::Relaxed);
}

pub fn claude_link() -> ClaudeLink {
    match CLAUDE_LINK.load(Ordering::Relaxed) {
        1 => ClaudeLink::Standby,
        2 => ClaudeLink::Ready,
        3 => ClaudeLink::Connected,
        _ => ClaudeLink::Off,
    }
}

/// Claude conversations attached to this window.
pub fn claude_conversations() -> usize {
    CLAUDE_CONVERSATIONS.load(Ordering::Relaxed)
}

/// Registered once by the desktop app: move the link to this window.
pub fn set_claim_hook(hook: ClaimHook) {
    let _ = CLAIM_HOOK.set(hook);
}

/// Connect Claude to this window (it takes the link from the window that has it). `false` when
/// this build has no link.
pub fn claim_claude() -> bool {
    CLAIM_HOOK.get().map(|h| h()).is_some()
}
