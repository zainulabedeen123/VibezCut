//! VibezCut ⇄ Claude (Windows): one VibezCut window at a time is the one Claude works with.
//!
//! * That window listens on 127.0.0.1:9876, the control channel the `filmcraft-studio` MCP
//!   server talks to, with a fresh 64-hex token per hold, written to
//!   `%USERPROFILE%\.filmcraft-studio\control.token` (the MCP server reads it there). Every request
//!   must carry the token (`control_server::serve_custom`).
//! * Other windows wait: when the holder closes, the next one takes the port within a couple of
//!   seconds. "Connect Claude to This Window" ([`vibezcut::claim_claude`]) writes a claim file with
//!   this process id; the holder sees it, lets go, and the claimer takes the port.
//! * A Claude conversation that works with VibezCut keeps one connection open and says
//!   `vibezcut.attach` on it (then `vibezcut.ping` every few seconds). While such a connection is
//!   open the window shows "connected to Claude": header badge, window glow, title, and a Claude
//!   dot on its taskbar button. When the conversation ends its process exits, the connection
//!   closes, and the indicators go away.
//!
//! `VIBEZCUT_NO_CLAUDE=1` turns the link off. A window started with `--control PORT` uses the
//! plain control server instead.

use filmcraft_engine::vibezcut::{self, ClaudeLink};
use filmcraft_platform::taskbar_overlay::TaskbarOverlay;
use filmcraft_ui_egui::ControlRequest;
use serde_json::{Value, json};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::time::{Duration, Instant, SystemTime};

/// The port Claude's `filmcraft-studio` MCP server connects to (`VIBEZCUT_CLAUDE_PORT` for tests,
/// with `FILMCRAFT_CONTROL_PORT` on the MCP server's side).
fn port() -> u16 {
    std::env::var("VIBEZCUT_CLAUDE_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(9876)
}
/// A claim newer than this belongs to a window that is taking the link; others leave the port to it.
const CLAIM_FRESH: Duration = Duration::from_secs(5);

/// Start the link (in the background). The receiver carries Claude's requests to the UI thread,
/// whichever window holds the link over time. `None` when turned off.
pub fn start(ctx: egui::Context) -> Option<Receiver<ControlRequest>> {
    if std::env::var_os("VIBEZCUT_NO_CLAUDE").is_some_and(|v| !v.is_empty()) {
        log::info!("claude: link off (VIBEZCUT_NO_CLAUDE)");
        return None;
    }
    let dir = std::env::var_os("USERPROFILE").filter(|v| !v.is_empty()).map(|h| PathBuf::from(h).join(".filmcraft-studio"))?;
    let (tx, rx) = channel();
    let claim_dir = dir.clone();
    vibezcut::set_claim_hook(Box::new(move || {
        let _ = std::fs::create_dir_all(&claim_dir);
        if let Err(e) = std::fs::write(claim_dir.join("claim"), format!("{}\n", std::process::id())) {
            log::warn!("claude: could not ask for the link: {e}");
        }
    }));
    vibezcut::set_claude_link(ClaudeLink::Standby, 0);
    let spawned = std::thread::Builder::new().name("claude-link".into()).spawn(move || run(&dir, &tx, &ctx));
    if let Err(e) = spawned {
        log::warn!("claude: no link thread: {e}");
        vibezcut::set_claude_link(ClaudeLink::Off, 0);
    }
    Some(rx)
}

fn run(dir: &Path, tx: &Sender<ControlRequest>, ctx: &egui::Context) {
    let me = std::process::id();
    let mut taskbar = TaskbarOverlay::new();
    loop {
        set_state(ctx, &mut taskbar, ClaudeLink::Standby, 0);
        let listener = wait_for_port(dir, me);
        if claim(dir).is_some_and(|(pid, _)| pid == me) {
            let _ = std::fs::remove_file(dir.join("claim"));
        }
        let Some(token) = new_token(dir) else {
            drop(listener);
            std::thread::sleep(Duration::from_secs(10));
            continue;
        };
        log::info!("claude: this window is linked to Claude (127.0.0.1:{})", port());
        hold(dir, me, listener, &token, tx, ctx, &mut taskbar);
        log::info!("claude: link handed to another window");
    }
}

/// Wait until this window may take the port, and take it.
fn wait_for_port(dir: &Path, me: u32) -> TcpListener {
    loop {
        // a window that is taking the link over gets the first chance at the port
        let claim = claim(dir);
        let mine = claim.is_some_and(|(pid, _)| pid == me);
        let other_claims = claim.is_some_and(|(pid, age)| pid != me && age < CLAIM_FRESH);
        if !other_claims && let Ok(l) = TcpListener::bind(("127.0.0.1", port())) {
            return l;
        }
        std::thread::sleep(Duration::from_millis(if mine { 150 } else { 1500 }));
    }
}

/// Serve Claude until another window claims the link.
fn hold(dir: &Path, me: u32, listener: TcpListener, token: &str, tx: &Sender<ControlRequest>, ctx: &egui::Context, taskbar: &mut TaskbarOverlay) {
    let released = Arc::new(AtomicBool::new(false));
    let attached = Arc::new(AtomicUsize::new(0));
    let open = Arc::new(AtomicUsize::new(0));
    if let Err(e) = listener.set_nonblocking(true) {
        log::warn!("claude: {e}");
    }
    let mut shown = None;
    let mut next_claim_check = Instant::now();
    loop {
        match listener.accept() {
            Ok((stream, _)) => accept(stream, token, tx, ctx, &released, &attached, &open),
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(40)),
            Err(e) => {
                log::warn!("claude: accept: {e}");
                std::thread::sleep(Duration::from_millis(200));
            }
        }
        let n = attached.load(Ordering::SeqCst);
        let state = if n > 0 { ClaudeLink::Connected } else { ClaudeLink::Ready };
        if shown != Some((state, n)) {
            shown = Some((state, n));
            set_state(ctx, taskbar, state, n);
        }
        if Instant::now() >= next_claim_check {
            next_claim_check = Instant::now() + Duration::from_millis(250);
            if claim(dir).is_some_and(|(pid, age)| pid != me && age < CLAIM_FRESH) {
                // open connections close at their next request; the conversations reconnect to the new window
                released.store(true, Ordering::SeqCst);
                return;
            }
        }
    }
}

fn accept(
    stream: TcpStream,
    token: &str,
    tx: &Sender<ControlRequest>,
    ctx: &egui::Context,
    released: &Arc<AtomicBool>,
    attached: &Arc<AtomicUsize>,
    open: &Arc<AtomicUsize>,
) {
    if open.load(Ordering::SeqCst) >= crate::control_server::MAX_CONNECTIONS {
        return; // dropped: the peer sees the connection close
    }
    if stream.set_nonblocking(false).is_err() {
        return;
    }
    let (token, tx, ctx) = (token.to_string(), tx.clone(), ctx.clone());
    let (released, attached) = (Arc::clone(released), Arc::clone(attached));
    let slot = Counted::new(Arc::clone(open));
    let spawned = std::thread::Builder::new().name("claude-conn".into()).spawn(move || {
        let _slot = slot;
        let mut attachment: Option<Counted> = None;
        let served = crate::control_server::serve_custom(stream, &token, |method, params| {
            if released.load(Ordering::SeqCst) {
                return None;
            }
            match method.as_str() {
                "vibezcut.attach" => {
                    if attachment.is_none() {
                        attachment = Some(Counted::new(Arc::clone(&attached)));
                        ctx.request_repaint();
                    }
                    Some(json!({"ok": true, "result": {"app": vibezcut::NAME, "version": vibezcut::VERSION, "pid": std::process::id()}}))
                }
                "vibezcut.ping" => Some(json!({"ok": true, "result": Value::Null})),
                _ => crate::control_server::forward(&tx, &ctx, method, params),
            }
        });
        if let Err(e) = served {
            log::warn!("claude: connection: {e}");
        }
        drop(attachment);
        ctx.request_repaint();
    });
    if let Err(e) = spawned {
        log::warn!("claude: no connection thread: {e}");
    }
}

/// One counted thing (an open connection, an attached conversation); uncounted when dropped.
struct Counted(Arc<AtomicUsize>);

impl Counted {
    fn new(n: Arc<AtomicUsize>) -> Self {
        n.fetch_add(1, Ordering::SeqCst);
        Self(n)
    }
}

impl Drop for Counted {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

fn set_state(ctx: &egui::Context, taskbar: &mut TaskbarOverlay, state: ClaudeLink, conversations: usize) {
    vibezcut::set_claude_link(state, conversations);
    taskbar.show(state == ClaudeLink::Connected);
    ctx.request_repaint();
}

/// The pending claim: (process id, age).
fn claim(dir: &Path) -> Option<(u32, Duration)> {
    let f = dir.join("claim");
    let pid = std::fs::read_to_string(&f).ok()?.trim().parse().ok()?;
    let age = std::fs::metadata(&f).and_then(|m| m.modified()).ok().and_then(|t| SystemTime::now().duration_since(t).ok()).unwrap_or_default();
    Some((pid, age))
}

/// A fresh 64-hex token for this hold, written where the MCP server reads it.
fn new_token(dir: &Path) -> Option<String> {
    let mut bytes = [0u8; 32];
    if let Err(e) = getrandom::fill(&mut bytes) {
        log::warn!("claude: no control token: {e}");
        return None;
    }
    let token: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    let written = std::fs::create_dir_all(dir).and_then(|()| std::fs::write(dir.join("control.token"), format!("{token}\n")));
    if let Err(e) = written {
        log::warn!("claude: control token not written: {e}");
        return None;
    }
    Some(token)
}
