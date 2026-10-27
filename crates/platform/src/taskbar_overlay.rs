//! A small badge on this process's taskbar button (Windows `ITaskbarList3::SetOverlayIcon`): VibezCut
//! shows a Claude dot there while a Claude conversation works with the window.

use windows::Win32::Foundation::{HWND, LPARAM};
use windows::Win32::System::Com::{CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED, CoCreateInstance, CoInitializeEx};
use windows::Win32::UI::Shell::{ITaskbarList3, TaskbarList};
use windows::Win32::UI::WindowsAndMessaging::{
    CreateIconFromResourceEx, DestroyIcon, EnumWindows, GW_OWNER, GetWindow, GetWindowThreadProcessId, HICON, IsWindowVisible, LR_DEFAULTCOLOR,
};
use windows::core::{BOOL, PCWSTR, w};

const DOT_PNG: &[u8] = include_bytes!("../../../assets/app-icon/claude-dot.png");

pub struct TaskbarOverlay {
    list: Option<ITaskbarList3>,
    icon: Option<HICON>,
    shown: bool,
}

impl TaskbarOverlay {
    #[allow(clippy::new_without_default)]
    pub fn new() -> Self {
        // SAFETY: COM for this thread (the link thread), then the shell's taskbar object.
        let list = unsafe {
            let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
            CoCreateInstance::<_, ITaskbarList3>(&TaskbarList, None, CLSCTX_INPROC_SERVER).ok().filter(|l| l.HrInit().is_ok())
        };
        // SAFETY: a PNG icon resource (Vista+), 32×32.
        let icon = unsafe { CreateIconFromResourceEx(DOT_PNG, true, 0x0003_0000, 32, 32, LR_DEFAULTCOLOR) }.ok();
        Self { list, icon, shown: false }
    }

    pub fn show(&mut self, on: bool) {
        if on == self.shown {
            return;
        }
        let (Some(list), Some(icon)) = (&self.list, self.icon) else { return };
        let Some(hwnd) = main_window() else { return };
        // SAFETY: our own top-level window; the icon lives as long as `self`.
        let done = unsafe {
            if on {
                list.SetOverlayIcon(hwnd, icon, w!("Connected to Claude"))
            } else {
                list.SetOverlayIcon(hwnd, HICON::default(), PCWSTR::null())
            }
        };
        match done {
            Ok(()) => self.shown = on,
            Err(e) => log::warn!("taskbar badge: {e}"),
        }
    }
}

impl Drop for TaskbarOverlay {
    fn drop(&mut self) {
        if let Some(icon) = self.icon.take() {
            // SAFETY: created by CreateIconFromResourceEx above.
            let _ = unsafe { DestroyIcon(icon) };
        }
    }
}

/// This process's visible top-level window (the one with the taskbar button).
fn main_window() -> Option<HWND> {
    unsafe extern "system" fn each(hwnd: HWND, found: LPARAM) -> BOOL {
        let mut pid = 0u32;
        // SAFETY: plain window queries; `found` points at the Option below.
        unsafe {
            GetWindowThreadProcessId(hwnd, Some(&mut pid));
            if pid == std::process::id() && IsWindowVisible(hwnd).as_bool() && GetWindow(hwnd, GW_OWNER).is_err() {
                *(found.0 as *mut Option<HWND>) = Some(hwnd);
                return BOOL(0);
            }
        }
        BOOL(1)
    }
    let mut found: Option<HWND> = None;
    // SAFETY: the callback only writes `found`, which outlives the call.
    let _ = unsafe { EnumWindows(Some(each), LPARAM(&mut found as *mut _ as isize)) };
    found
}
