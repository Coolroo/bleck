//! Compositing one fragment onto what is already in the frame.
//!
//! ✅ **The game's own five modes**, read from its draw code at `0x8005c9f8`
//! (D270). The arithmetic is here rather than in the triangle filler because it
//! is a table of measured facts about `GXSetBlendMode`, and it needs nothing
//! from the rasteriser to state them.

use crate::data::mesh::Blend;
use crate::render::Rgba;

/// One channel of a blend, in the game's own terms.
///
/// ⚠️ **Saturating, not wrapping.** An additive glow over a bright background
/// overflows constantly, and wrapping turns a highlight into a dark hole — the
/// most visible possible wrong answer.
fn channel(blend: Blend, src: u8, alpha: u8, dst: u8) -> u8 {
    let (src, alpha, dst) = (src as i32, alpha as i32, dst as i32);
    let scaled = src * alpha / 255;
    let value = match blend {
        // Handled by the caller; here for completeness.
        Blend::Opaque => src,
        Blend::Alpha => scaled + dst * (255 - alpha) / 255,
        Blend::Add => scaled + dst,
        Blend::Subtract => dst - src,
        // `GX_BL_INVSRCCLR` on both sides: (1 - src) * (src + dst).
        Blend::Inverse => (255 - src) * (src + dst) / 255,
    };
    value.clamp(0, 255) as u8
}

pub(super) fn mix(blend: Blend, src: Rgba, alpha: u8, dst: Rgba) -> Rgba {
    Rgba::new(
        channel(blend, src.r, alpha, dst.r),
        channel(blend, src.g, alpha, dst.g),
        channel(blend, src.b, alpha, dst.b),
    )
}
