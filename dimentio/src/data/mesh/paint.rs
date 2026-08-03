//! What a shape is painted with: the image, how it is sampled, how its alpha is
//! read, and how the result is composited.
//!
//! ⚠️ **A model carries as many images as its shapes reach** — 15 on
//! `e_lui_robo` — so the binding is per shape and never per mesh (D246). That
//! is why `Batch` and `Surface` exist at all.

use crate::data::texture::{Sampling, Texture};

use super::geometry::{Face, Uv};

/// One shape of a model: a run of the face list, the image it draws with, and
/// whether it is drawn at all.
///
/// ⚠️ **The span, not a name.** `bleck` writes one glTF primitive per shape and
/// the Maya shape names are not bound to them — which name goes with which
/// group is undecoded (D229), so a shape identifies itself by where it sits.
///
/// ⛔ **The merge is what made `e_lui_robo` look broken** (D236). It holds 92
/// shapes, one of them a flat quad 130 units to the side; flattened into one
/// mesh there was nothing to hide and nothing to say it was separate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Shape {
    pub first: usize,
    pub count: usize,
    pub visible: bool,
    /// Which of the mesh's `paints` this shape samples, or `None` when it draws
    /// flat. `e_lui_robo` reaches 15 of them across 68 of its 92 shapes, so one
    /// image over the whole mesh paints most of the robot with a stranger's
    /// texture (D246).
    pub paint: Option<usize>,
}
/// How a paint is combined with what is already in the frame.
///
/// ✅ **The game's own switch**, read from its draw code at `0x8005c9f8`
/// (D270): each case is one `GXSetBlendMode` call, selected by the high byte of
/// a section 7 group's flags.
///
/// 🟢 The semantic check that the reading is right: the effects asking for
/// `Add` are `explosion`, `dmen_explosion`, `event_fire`, `event_enmagic`,
/// `chaos_start` and `fairyn_get` — glows and flashes, every one.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Blend {
    /// Replace what is there. Model art, which is `MASK` and never blends.
    #[default]
    Opaque,
    /// `src*a + dst*(1-a)`. What the effect renderer did before D270, and what
    /// a draw whose mode is 0 keeps doing.
    ///
    /// ⚠️ **Mode 0 is not "opaque"** — it falls through the game's switch and
    /// the mode comes from state `bleck` does not follow. 2,528 of 2,960 draws
    /// are mode 0, so guessing wrong here would be wrong nearly everywhere.
    Alpha,
    /// `src*a + dst` — `GX_BM_BLEND` with `dst = GX_BL_ONE`. The glow blend: a
    /// black surround contributes nothing instead of darkening what is behind.
    Add,
    /// `dst - src` — `GX_BM_SUBTRACT`. Six draws, in `chaos` and `event_*magic`.
    Subtract,
    /// `(1-src) * (src + dst)` — `GX_BM_BLEND` with both factors
    /// `GX_BL_INVSRCCLR`. 41 draws, all electrical: `item_thunder`,
    /// `item_biribiri`, `item_stop`.
    Inverse,
}

/// One image a mesh draws with, how it is sampled, and how its alpha is read.
///
/// ⚠️ `masked` and `sampling` belong to the material, not to the image: two
/// materials can name the same PNG, clamp one and repeat the other, and treat
/// its alpha differently. They are held here rather than once for the mesh.
#[derive(Debug, Clone, PartialEq)]
pub struct Paint {
    pub texture: Texture,
    /// The material declared `alphaMode: "MASK"` — cut-out art, where a texel
    /// below `cutoff` is not drawn at all.
    pub masked: bool,
    /// How this paint is composited onto what is already there.
    ///
    /// ✅ **Effect art needs this and model art does not.** glTF's `MASK` means
    /// exactly "no blending": a cut-out texel is opaque or absent, and blending
    /// one at its stated alpha would wash out every model on the disc. Effect
    /// sprites are semi-transparent throughout, and 432 of the file's draws ask
    /// for something other than plain alpha (D267, D270).
    pub blend: Blend,
    /// The alpha a texel must reach to be drawn when `masked`.
    ///
    /// ⚠️ **Not always glTF's 128.** Cut-out model art is opaque wherever it is
    /// drawn at all, so half is the right place to split it. Effect sprites are
    /// semi-transparent throughout — `effdata.tpl` image 21 never exceeds
    /// **109** — and a cutoff of 128 discards every texel of them, rendering
    /// the effect invisible rather than faint (D259).
    pub cutoff: u8,
    /// Wrap mode and UV transform, read from the file's sampler (D247).
    pub sampling: Sampling,
    /// A second layer whose **alpha** multiplies this one, colour included.
    ///
    /// ✅ 40 shapes on the disc carry one, and glTF has no core slot that means
    /// it — the exporter declares it in `material.extras` and this is where it
    /// lands. ⛔ **Not a second colour layer.** The TEV program the game picks
    /// for these shapes never samples the second image's RGB (D247).
    pub mask: Option<Mask>,
}

/// The second layer of a two-layer shape: an image sampled for its alpha alone.
#[derive(Debug, Clone, PartialEq)]
pub struct Mask {
    pub texture: Texture,
    pub sampling: Sampling,
}

/// One shape's faces and the surface they are painted with.
///
/// ⚠️ **This is what binds a texture, not the mesh.** A model carries as many
/// images as its shapes reach — 15 on `e_lui_robo` — and a renderer that asked
/// the mesh for "its" texture would stretch one of them over all 92 (D246).
#[derive(Debug, Clone, Copy)]
pub struct Batch<'a> {
    pub faces: &'a [Face],
    pub surface: Option<Surface<'a>>,
    /// The whole model's vertex colours, indexed by a face's corners.
    ///
    /// ⚠️ **Beside `surface`, not inside it.** A shape with no image is drawn
    /// with its vertex colour alone — the game's TEV takes the `GX_PASSCLR`
    /// path when the layer count is zero (D247) — so a tint that lived on the
    /// surface would be lost on exactly the 41 models that need it most.
    pub tints: Option<&'a [[u8; 4]]>,
}

/// The texture a mesh is painted with, and the coordinates that index it.
///
/// Only ever handed out when both are present, so the rasteriser cannot reach
/// a half-textured mesh — UVs with no image would sample nothing, and an image
/// with no UVs has no coordinate to sample it at.
#[derive(Debug, Clone, Copy)]
pub struct Surface<'a> {
    pub texture: &'a Texture,
    pub uvs: &'a [Uv],
    pub blend: Blend,
    pub masked: bool,
    pub cutoff: u8,
    pub sampling: &'a Sampling,
    pub mask: Option<&'a Mask>,
}

impl Surface<'_> {
    /// The three coordinates a face samples at, or `None` when the UV list does
    /// not reach one of its corners — which leaves that face flat-shaded rather
    /// than dropping it.
    pub fn corners(&self, face: Face) -> Option<[Uv; 3]> {
        Some([
            *self.uvs.get(face.a)?,
            *self.uvs.get(face.b)?,
            *self.uvs.get(face.c)?,
        ])
    }
}
