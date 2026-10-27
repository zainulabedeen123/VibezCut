//! VibezCut auto-update (Windows, Velopack) and the Claude integration that ships with it.
//!
//! * `startup()` runs first in `main`: Velopack's install / update / uninstall hooks, and it
//!   applies an update that was downloaded earlier before the app starts.
//! * `start()` runs in the background once the app is up. When VibezCut was installed with
//!   `VibezCut-Setup.exe` it checks the GitHub Releases of the VibezCut repository, downloads a
//!   newer version and tells the UI (`filmcraft_engine::vibezcut::update_ready`), which offers
//!   "Restart to update". An update that is not applied by a restart is applied on the next start.
//! * After an install or an update it keeps Claude pointed at this version: the `filmcraft-edit`
//!   skill is copied to `~/.claude/skills` and the `filmcraft-studio` MCP server is registered for
//!   the user (`claude mcp add --scope user …`), both from the files installed next to the app.
//!
//! A copy that was not installed with Setup (a zip, a developer build) skips all of this.

use filmcraft_engine::vibezcut;
use std::path::{Path, PathBuf};
use std::process::Command;
use velopack::sources::GithubSource;
use velopack::{UpdateCheck, UpdateManager, VelopackApp};

/// Velopack's start-up hooks. Must run before anything else: it may exit or restart the process.
pub fn startup() {
    VelopackApp::build()
        .on_before_uninstall_fast_callback(|_| remove_claude_integration())
        .run();
}

/// Background update check and Claude integration sync (installed copies only).
pub fn start(data_root: Option<PathBuf>) {
    let spawned = std::thread::Builder::new().name("vibezcut-update".into()).spawn(move || {
        let source = GithubSource::new(vibezcut::REPOSITORY, None, false);
        let um = match UpdateManager::new(source, None, None) {
            Ok(um) => um,
            Err(e) => {
                log::info!("updates: off, this copy was not installed with Setup ({e})");
                return;
            }
        };
        log::info!("updates: installed {} {}", um.get_app_id(), um.get_current_version_as_string());
        if let Some(root) = data_root.as_deref() {
            sync_claude_integration(root);
        }
        match um.check_for_updates() {
            Ok(UpdateCheck::UpdateAvailable(info)) => {
                let version = info.TargetFullRelease.Version.clone();
                log::info!("updates: {version} available, downloading");
                if let Err(e) = um.download_updates(&info, None) {
                    log::warn!("updates: download of {version} failed: {e}");
                    return;
                }
                let asset = info.TargetFullRelease.clone();
                let manager = um.clone();
                vibezcut::set_restart_hook(Box::new(move || match manager.wait_exit_then_apply_updates(&asset, true, true, Vec::<String>::new()) {
                    Ok(()) => true,
                    Err(e) => {
                        log::warn!("updates: could not start the updater: {e}");
                        false
                    }
                }));
                log::info!("updates: {version} downloaded, ready to install");
                vibezcut::set_update_ready(version);
            }
            Ok(_) => log::info!("updates: up to date"),
            Err(e) => log::warn!("updates: check failed: {e}"),
        }
    });
    if let Err(e) = spawned {
        log::warn!("updates: no update thread: {e}");
    }
}

/// The folder with VibezCut.exe, the studio layer and the Claude skill.
fn app_dir() -> Option<PathBuf> {
    std::env::current_exe().ok()?.parent().map(Path::to_path_buf)
}

/// After an install or update (a new version or a new install folder): copy the skill and
/// (re-)register the MCP server. Recorded in `<data dir>/claude-integration.txt` so it runs once.
fn sync_claude_integration(data_root: &Path) {
    let Some(dir) = app_dir() else { return };
    let marker = data_root.join("claude-integration.txt");
    let want = format!("{}\n{}\n", vibezcut::VERSION, dir.display());
    if std::fs::read_to_string(&marker).ok().as_deref() == Some(want.as_str()) {
        return;
    }
    let mut ok = true;
    // the editing skill
    match home_dir() {
        Some(home) => {
            let from = dir.join("claude-skill").join("filmcraft-edit");
            let to = home.join(".claude").join("skills").join("filmcraft-edit");
            if let Err(e) = copy_dir(&from, &to) {
                log::warn!("claude: skill not installed: {e}");
                ok = false;
            }
        }
        None => ok = false,
    }
    // the MCP server, run by the user's Python (full path: a bare `python` can be a Store alias)
    let server = dir.join("studio").join("run_server.py");
    match python_exe() {
        Some(py) if server.exists() => {
            let _ = run_hidden("cmd", &["/C", "claude", "mcp", "remove", "--scope", "user", "filmcraft-studio"]);
            let args = ["/C", "claude", "mcp", "add", "--scope", "user", "filmcraft-studio", "--"];
            let py = py.to_string_lossy().into_owned();
            let server = server.to_string_lossy().into_owned();
            let mut all: Vec<&str> = args.to_vec();
            all.push(&py);
            all.push(&server);
            if !run_hidden("cmd", &all) {
                log::warn!("claude: MCP server not registered (is Claude Code installed?)");
                ok = false;
            }
        }
        _ => {
            log::warn!("claude: MCP server not registered (Python 3 not found)");
            ok = false;
        }
    }
    if ok {
        let _ = std::fs::create_dir_all(data_root);
        let _ = std::fs::write(&marker, want);
        log::info!("claude: skill and MCP server set up for {}", dir.display());
    }
}

fn remove_claude_integration() {
    let _ = run_hidden("cmd", &["/C", "claude", "mcp", "remove", "--scope", "user", "filmcraft-studio"]);
    if let Some(home) = home_dir() {
        let _ = std::fs::remove_dir_all(home.join(".claude").join("skills").join("filmcraft-edit"));
    }
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE").filter(|v| !v.is_empty()).map(PathBuf::from)
}

/// The real python.exe behind `py` / `python` on PATH: the first one that has the studio's
/// packages (`mcp`), else the first one found. Several Pythons side by side are common on Windows.
fn python_exe() -> Option<PathBuf> {
    const PROBE: &str = "import sys, importlib.util as u; print(sys.executable); print(u.find_spec('mcp') is not None)";
    let mut first = None;
    for (cmd, pre) in [("python", vec![]), ("py", vec!["-3"]), ("python3", vec![])] {
        let mut c = Command::new(cmd);
        c.args(&pre).args(["-c", PROBE]);
        hide(&mut c);
        let Ok(out) = c.output() else { continue };
        if !out.status.success() {
            continue;
        }
        let text = String::from_utf8_lossy(&out.stdout).into_owned();
        let mut lines = text.lines();
        let (Some(exe), Some(has_mcp)) = (lines.next(), lines.next()) else { continue };
        let p = PathBuf::from(exe.trim());
        if !p.exists() {
            continue;
        }
        if has_mcp.trim() == "True" {
            return Some(p);
        }
        first.get_or_insert(p);
    }
    first
}

fn run_hidden(cmd: &str, args: &[&str]) -> bool {
    let mut c = Command::new(cmd);
    c.args(args);
    hide(&mut c);
    c.output().is_ok_and(|o| o.status.success())
}

fn hide(c: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    c.creation_flags(CREATE_NO_WINDOW);
}

fn copy_dir(from: &Path, to: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(to)?;
    for entry in std::fs::read_dir(from)? {
        let entry = entry?;
        let target = to.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), target)?;
        }
    }
    Ok(())
}
