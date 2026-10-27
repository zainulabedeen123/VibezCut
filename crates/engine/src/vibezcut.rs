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
