//! Still images (PNG, JPEG, GIF, WebP, TIFF, BMP, Targa, DPX, OpenEXR, Radiance HDR, DNG camera raw) as media
//! sources. Animated PNG and GIF files open as movies instead ([`crate::animated`]); here they would
//! show their first frame.

use std::sync::Arc;

use filmcraft_frame::VideoFrame;
use filmcraft_time::{FrameRate, TICKS_PER_SECOND, Tick};

use crate::{FrameRequest, MediaError, MediaInfo, MediaKind, MediaSource, Result, VideoStreamInfo};

pub mod dng;
pub mod exr;
pub mod hdr;
mod ycbcr_tiff;

/// Default still duration (Premiere's preference default is 5 seconds).
pub const DEFAULT_STILL_DURATION: Tick = Tick(5 * TICKS_PER_SECOND);

/// Whether `b` (the contents of the file `name`) is a still image we decode.
pub fn sniff(name: &str, b: &[u8]) -> bool {
    crate::dpx::sniff(b)
        || hdr::sniff(b)
        || crate::tga::sniff(name, b)
        || b.starts_with(b"\x89PNG")
        || b.starts_with(&[0xFF, 0xD8, 0xFF])
        || b.starts_with(b"GIF8")
        || (b.len() > 12 && &b[0..4] == b"RIFF" && &b[8..12] == b"WEBP")
        || b.starts_with(b"II*\0")
        || b.starts_with(b"MM\0*")
        || b.starts_with(b"BM")
}

/// A decoded picture: straight-alpha RGBA8, top row first.
pub struct Raster {
    pub width: u32,
    pub height: u32,
    pub rgba: Vec<u8>,
    /// Whether any pixel is not fully opaque.
    pub has_alpha: bool,
}

/// The most pixels a still keeps at full resolution: 16.8 MP (4096 x 4096, or 5K 5120 x 2880), about
/// twice a 4K frame. A bigger picture is downscaled, keeping its aspect ratio, when it is decoded.
/// The renderer converts a still to 32-bit float RGBA (16 bytes a pixel) for every frame, and an export
/// renders many frames at once: a 16117 x 7764 PNG logo needed one 2 GB allocation, and the failed
/// allocation aborted the whole app in the middle of an export. The clip still reports the picture's
/// own size, so layout and Motion scale and position do not change: the compositor derives its pixel
/// scale from the frame it gets, as it does for proxies.
pub const MAX_STILL_PIXELS: u64 = 1 << 24;

/// `(width, height)` scaled down, aspect ratio kept, so that `width * height <= max_pixels`; `None`
/// when it already fits (or is empty).
pub fn capped_size(width: u32, height: u32, max_pixels: u64) -> Option<(u32, u32)> {
    let pixels = u64::from(width) * u64::from(height);
    if width == 0 || height == 0 || pixels <= max_pixels {
        return None;
    }
    let k = (max_pixels as f64 / pixels as f64).sqrt();
    // floor: the product stays within the budget
    let (mut w, mut h) = (((f64::from(width) * k).floor() as u32).max(1), ((f64::from(height) * k).floor() as u32).max(1));
    // a thin strip: the short side cannot go below one pixel, so the long side gives way instead
    let budget = u32::try_from(max_pixels).unwrap_or(u32::MAX).max(1);
    if h == 1 {
        w = w.min(budget);
    }
    if w == 1 {
        h = h.min(budget);
    }
    Some((w, h))
}

/// Decode a still image file (`name` picks Targa, which has no magic number; the content picks
/// every other format), at the size the file has.
pub fn decode_raster(name: &str, bytes: &[u8]) -> Result<Raster> {
    decode_limited(name, bytes, u64::MAX).map(|(raster, _)| raster)
}

/// [`decode_raster`] for a picture the renderer will hold: one over [`MAX_STILL_PIXELS`] is downscaled.
/// Returns the picture and the size the file really has.
pub fn decode_raster_capped(name: &str, bytes: &[u8]) -> Result<(Raster, (u32, u32))> {
    decode_limited(name, bytes, MAX_STILL_PIXELS)
}

fn decode_limited(name: &str, bytes: &[u8], max_pixels: u64) -> Result<(Raster, (u32, u32))> {
    if crate::dpx::sniff(bytes) {
        return shrink(crate::dpx::decode(name, bytes)?, max_pixels);
    }
    if crate::tga::sniff(name, bytes) {
        return shrink(crate::tga::decode(name, bytes)?, max_pixels);
    }
    if ycbcr_tiff::sniff(bytes) {
        return shrink(ycbcr_tiff::decode(name, bytes)?, max_pixels);
    }
    let img = image::load_from_memory(bytes).map_err(|e| MediaError::Decode(format!("{name}: {e}")))?;
    let size = (img.width(), img.height());
    let has_alpha = img.color().has_alpha();
    // shrink before the RGBA8 copy: the full-size copy is the biggest buffer of all
    let img = match capped_size(size.0, size.1, max_pixels) {
        Some((w, h)) => img.resize_exact(w, h, image::imageops::FilterType::CatmullRom),
        None => img,
    };
    let rgba = img.to_rgba8();
    let (width, height) = rgba.dimensions();
    Ok((Raster { width, height, rgba: rgba.into_raw(), has_alpha }, size))
}

/// A decoded raster over the budget, downscaled; with the size it had.
fn shrink(r: Raster, max_pixels: u64) -> Result<(Raster, (u32, u32))> {
    let size = (r.width, r.height);
    let Some((w, h)) = capped_size(r.width, r.height, max_pixels) else {
        return Ok((r, size));
    };
    let has_alpha = r.has_alpha;
    let buf = image::RgbaImage::from_raw(r.width, r.height, r.rgba).ok_or_else(|| MediaError::Decode("image buffer does not match its size".into()))?;
    let out = image::imageops::resize(&buf, w, h, image::imageops::FilterType::CatmullRom);
    Ok((Raster { width: w, height: h, rgba: out.into_raw(), has_alpha }, size))
}

pub struct StillSource {
    info: MediaInfo,
    frame: Arc<VideoFrame>,
}

impl StillSource {
    pub fn decode(name: &str, bytes: &[u8]) -> Result<Self> {
        Self::decode_with(name, bytes, MAX_STILL_PIXELS)
    }

    fn decode_with(name: &str, bytes: &[u8], max_pixels: u64) -> Result<Self> {
        // a DNG is a TIFF too: develop its raw image instead of reading its preview
        if dng::sniff(bytes) {
            return dng::still(name, bytes);
        }
        if hdr::sniff(bytes) {
            return hdr::still(name, bytes);
        }
        let (r, size) = decode_limited(name, bytes, max_pixels)?;
        Ok(Self::from_rgba_sized(name, size, r.width, r.height, r.rgba, r.has_alpha, bytes.len() as u64))
    }

    pub fn from_rgba(name: &str, w: u32, h: u32, rgba: Vec<u8>, has_alpha: bool, file_size: u64) -> Self {
        Self::from_rgba_sized(name, (w, h), w, h, rgba, has_alpha, file_size)
    }

    /// A still whose picture (`w` x `h`) is smaller than the image it stands for (`size`, what the clip
    /// reports): a downscaled huge picture.
    pub fn from_rgba_sized(name: &str, size: (u32, u32), w: u32, h: u32, rgba: Vec<u8>, has_alpha: bool, file_size: u64) -> Self {
        let codec = name.rsplit('.').next().unwrap_or("image").to_ascii_uppercase();
        let info = MediaInfo {
            name: name.to_string(),
            kind: MediaKind::Still,
            duration: DEFAULT_STILL_DURATION,
            video: Some(VideoStreamInfo {
                width: size.0,
                height: size.1,
                frame_rate: FrameRate::FPS_29_97,
                par: (1, 1),
                codec,
                pixel_format: if has_alpha { "RGBA 8-bit".into() } else { "RGB 8-bit".into() },
                color: filmcraft_color::ColorInfo::SRGB_FULL,
                has_alpha,
                bitrate: None,
                hdr: None,
            }),
            audio_streams: Vec::new(),
            container: "Image".into(),
            start_timecode: None,
            file_size: Some(file_size),
        };
        Self { info, frame: Arc::new(VideoFrame::rgba8(w, h, rgba)) }
    }
}

impl MediaSource for StillSource {
    fn info(&self) -> &MediaInfo {
        &self.info
    }
    fn video_frame(&self, _req: FrameRequest) -> Result<Arc<VideoFrame>> {
        Ok(self.frame.clone())
    }
    fn audio(&self, _start: i64, _frames: usize, _sample_rate: u32) -> Result<filmcraft_frame::AudioBuffer> {
        Err(MediaError::NoStream("audio"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn png(w: u32, h: u32) -> Vec<u8> {
        let img = image::RgbaImage::from_pixel(w, h, image::Rgba([200, 40, 40, 255]));
        let mut out = std::io::Cursor::new(Vec::new());
        img.write_to(&mut out, image::ImageFormat::Png).expect("a test PNG encodes");
        out.into_inner()
    }

    #[test]
    fn capped_size_keeps_the_aspect_ratio_inside_the_budget() {
        // 4096 x 4096 and 5K fit; 8K UHD does not
        assert_eq!(capped_size(4096, 4096, MAX_STILL_PIXELS), None);
        assert_eq!(capped_size(5120, 2880, MAX_STILL_PIXELS), None);
        assert!(capped_size(7680, 4320, MAX_STILL_PIXELS).is_some());
        // an empty picture has nothing to cap
        assert_eq!(capped_size(0, 100, 10), None);
        // the 16117 x 7764 logo that needed a 2 GB float copy
        let (w, h) = capped_size(16117, 7764, MAX_STILL_PIXELS).expect("over the budget");
        assert!(u64::from(w) * u64::from(h) <= MAX_STILL_PIXELS, "{w}x{h}");
        assert!(u64::from(w) * u64::from(h) * 100 > MAX_STILL_PIXELS * 98, "not much smaller than it must be: {w}x{h}");
        assert!((f64::from(w) / f64::from(h) - 16117.0 / 7764.0).abs() < 0.01, "{w}x{h}");
        // a thin strip never collapses to nothing
        assert_eq!(capped_size(100_000, 1, 10), Some((10, 1)));
        assert_eq!(capped_size(1, 100_000, 10), Some((1, 10)));
        assert_eq!(capped_size(u32::MAX, u32::MAX, 1), Some((1, 1)));
        // whatever the shape, the product is within the budget
        for (w, h) in [(16117, 7764), (40_000_000, 1), (1, 40_000_000), (9000, 9000), (u32::MAX, 3)] {
            let (nw, nh) = capped_size(w, h, MAX_STILL_PIXELS).expect("over the budget");
            assert!(u64::from(nw) * u64::from(nh) <= MAX_STILL_PIXELS, "{w}x{h} -> {nw}x{nh}");
        }
    }

    #[test]
    fn a_huge_still_is_downscaled_but_keeps_its_own_size() {
        // the same shape as the crash, with a small budget: a 400 x 200 picture, at most 10 000 pixels
        let s = StillSource::decode_with("huge.png", &png(400, 200), 10_000).expect("decodes");
        let v = s.info().video.as_ref().expect("a picture");
        assert_eq!((v.width, v.height), (400, 200), "the clip reports the real size, so layout and scale do not change");
        let f = s.video_frame(FrameRequest::full(Tick(0))).expect("a frame");
        assert!(u64::from(f.width) * u64::from(f.height) <= 10_000, "{}x{}", f.width, f.height);
        assert!((f64::from(f.width) / f64::from(f.height) - 2.0).abs() < 0.1, "{}x{}", f.width, f.height);
    }

    #[test]
    fn a_still_within_the_budget_is_untouched() {
        let s = StillSource::decode_with("small.png", &png(50, 20), 10_000).expect("decodes");
        let f = s.video_frame(FrameRequest::full(Tick(0))).expect("a frame");
        assert_eq!((f.width, f.height), (50, 20));
        let v = s.info().video.as_ref().expect("a picture");
        assert_eq!((v.width, v.height), (50, 20));
        // the uncapped decode (used elsewhere) never shrinks
        let (r, size) = decode_limited("big.png", &png(400, 200), u64::MAX).expect("decodes");
        assert_eq!(((r.width, r.height), size), ((400, 200), (400, 200)));
    }
}
