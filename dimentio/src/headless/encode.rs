//! Writing a finished sheet, or a run of cells, out to a file.
//!
//! The two formats answer different questions and the extension picks between
//! them: a PNG contact sheet is for judging colour, a looping GIF is for
//! watching motion.

use std::io::BufWriter;
use std::path::Path;

use image::codecs::gif::{GifEncoder, Repeat};
use image::codecs::png::PngEncoder;
use image::{Delay, ExtendedColorType, Frame as GifFrame, ImageEncoder, RgbaImage};

use crate::render::{Image, Size};

/// The shortest delay a GIF can express: its unit is a **centisecond**.
///
/// ⚠️ Anything faster is rounded, so a 60 Hz effect cannot be played at rate —
/// one game frame is 1.67 cs. `write_gif` says what it actually used rather
/// than pretending, because a GIF that plays at 2/3 speed looks like a slow
/// effect rather than a limitation of the format.
pub(super) const GIF_TICK_MS: u32 = 10;

/// Whether a path asks for an animation rather than a still.
///
/// ⚠️ Decided by extension, deliberately: a caller writing `--out foo.gif` and
/// getting a PNG named `.gif` would have no way to tell until something else
/// refused to open it.
pub(super) fn wants_gif(path: &Path) -> bool {
    path.extension()
        .is_some_and(|kind| kind.eq_ignore_ascii_case("gif"))
}

/// Create the folder above `path`, when the path names one.
fn make_room(path: &Path) -> Result<(), String> {
    if let Some(folder) = path
        .parent()
        .filter(|folder| !folder.as_os_str().is_empty())
    {
        std::fs::create_dir_all(folder)
            .map_err(|why| format!("could not create {}: {why}", folder.display()))?;
    }
    Ok(())
}

/// Write a sequence of equally-sized frames as a looping GIF.
///
/// `gap` is the wall-clock spacing between frames in milliseconds, rounded up
/// to `GIF_TICK_MS`; the rounding is returned so a caller can report the rate
/// it really got.
///
/// ⚠️ **256 colours, quantised.** The encoder reduces each frame, and effect
/// art includes smooth ramps — `dmen_magic`'s shuriken is a blue-to-magenta
/// gradient — so a GIF is for watching motion, not for judging colour. Use a
/// PNG contact sheet for that.
pub(super) fn write_gif(path: &Path, frames: &[Image], gap: u32) -> Result<u32, String> {
    if frames.is_empty() {
        return Err("no frames to animate".to_owned());
    }
    make_room(path)?;
    let used = gap.div_ceil(GIF_TICK_MS).max(1) * GIF_TICK_MS;
    let file = std::fs::File::create(path)
        .map_err(|why| format!("could not write {}: {why}", path.display()))?;

    let mut encoder = GifEncoder::new(BufWriter::new(file));
    encoder
        .set_repeat(Repeat::Infinite)
        .map_err(|why| format!("could not set the loop on {}: {why}", path.display()))?;
    for (at, frame) in frames.iter().enumerate() {
        let size = frame.size();
        let buffer = RgbaImage::from_raw(
            size.width as u32,
            size.height as u32,
            frame.as_rgba().to_vec(),
        )
        .ok_or_else(|| format!("frame {at} is not {}x{}", size.width, size.height))?;
        encoder
            .encode_frame(GifFrame::from_parts(
                buffer,
                0,
                0,
                Delay::from_numer_denom_ms(used, 1),
            ))
            .map_err(|why| format!("could not encode frame {at} of {}: {why}", path.display()))?;
    }
    Ok(used)
}

/// Write RGBA8 out as a PNG, creating the folder above it if it is missing.
pub(super) fn write_png(path: &Path, pixels: &[u8], size: Size) -> Result<(), String> {
    make_room(path)?;
    let file = std::fs::File::create(path)
        .map_err(|why| format!("could not write {}: {why}", path.display()))?;
    PngEncoder::new(BufWriter::new(file))
        .write_image(
            pixels,
            size.width as u32,
            size.height as u32,
            ExtendedColorType::Rgba8,
        )
        .map_err(|why| format!("could not encode {}: {why}", path.display()))
}

/// ⚠️ These write real files, into the system temp dir, and remove them. The
/// GIF encoder is a dependency; what is worth testing is that we hand it the
/// right frames and report what it did.
#[cfg(test)]
mod tests {
    use super::*;
    use crate::render::{self, Background, View};
    use std::path::PathBuf;

    fn scratch(name: &str) -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!("dimentio-gif-{}-{name}", std::process::id()));
        path
    }

    /// A frame with no geometry in it, so only the background fills it.
    ///
    /// ⚠️ Built through the public renderer rather than by poking pixels —
    /// `Image`'s writer is private to `render`, and the point here is the
    /// encoder, not the drawing.
    fn plain(size: usize, background: Background) -> Image {
        render::scene(
            &[],
            &View {
                background,
                ..Default::default()
            },
            Size::new(size, size),
        )
    }

    #[test]
    fn a_gif_is_written_and_starts_with_the_right_magic() {
        let out = scratch("magic.gif");
        let frames = [
            plain(8, Background::DarkGrey),
            plain(8, Background::Gradient),
        ];
        let tick = write_gif(&out, &frames, 40).expect("writes");
        assert_eq!(tick, 40);
        let bytes = std::fs::read(&out).expect("reads back");
        assert_eq!(&bytes[..6], b"GIF89a", "not a GIF");
        // The looping block is what makes it repeat rather than play once.
        assert!(
            bytes.windows(11).any(|run| run == b"NETSCAPE2.0"),
            "no loop block"
        );
        let _ = std::fs::remove_file(&out);
    }

    /// ⚠️ **A GIF delay is a whole centisecond.** One game frame is 16.7ms, so
    /// a request for it must round *up* to 20 and say so — rounding down to 10
    /// would play the effect at double speed.
    #[test]
    fn a_delay_rounds_up_to_the_formats_own_tick() {
        let out = scratch("tick.gif");
        let frames = [plain(4, Background::DarkGrey)];
        assert_eq!(write_gif(&out, &frames, 17).expect("writes"), 20);
        assert_eq!(write_gif(&out, &frames, 10).expect("writes"), 10);
        // ⛔ Never zero: a zero-delay GIF plays as fast as the viewer likes.
        assert_eq!(write_gif(&out, &frames, 0).expect("writes"), 10);
        let _ = std::fs::remove_file(&out);
    }

    #[test]
    fn no_frames_is_an_error_rather_than_an_empty_file() {
        let out = scratch("empty.gif");
        assert!(write_gif(&out, &[], 40).is_err());
        assert!(!out.is_file(), "an empty GIF was left behind");
    }

    #[test]
    fn only_a_gif_extension_asks_for_an_animation() {
        assert!(wants_gif(Path::new("a.gif")));
        assert!(wants_gif(Path::new("A.GIF")));
        assert!(!wants_gif(Path::new("a.png")));
        assert!(!wants_gif(Path::new("gif")));
    }
}
