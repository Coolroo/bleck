//! Filling triangles into a frame: the depth buffer, the edge test, the shading.
//!
//! ⚠️ Nothing is back-face culled. Exported meshes carry no guaranteed winding,
//! and culling one would open holes in it; hidden surfaces are removed by the
//! depth buffer alone, and every face is lit from whichever side is visible.
//! Remove the two-sided flip in `shade` and half of a model goes black.
//!
//! ⚠️ The light is fixed in *view* space, so it travels with the camera. A
//! world-fixed light is more realistic and leaves the far side of a model an
//! unreadable silhouette, which is the wrong trade for something whose whole
//! job is to let a model be looked at.
//!
//! ⚠️ A textured face is still shaded. The texture is multiplied by the same
//! flat term an untextured face is filled with, so facets stay readable;
//! painting the texel straight in flattens a model into a sticker.
//!
//! How a fragment is combined with what is already there is `blend`, which is
//! a transcription of the game's own `GXSetBlendMode` switch and needs nothing
//! from this file.

use super::camera::{Basis, Point};
use super::{Background, Rgba, Size};
use crate::data::mesh::{Blend, Mask, Uv, Vec3};
use crate::data::texture::{Sampling, Texel, Texture};
use blend::mix;

/// Light that reaches a face turned fully away from it, so nothing is pure
/// black and a silhouette still shows its shape.
const AMBIENT: f32 = 0.25;

/// Light direction in view space: over the viewer's left shoulder.
const LIGHT: Vec3 = Vec3::new(-0.4, 0.6, -0.7);

/// Untextured surface colour. 277 of 864 models export without a material, so
/// their faces differ only by how they are lit. A caller that wants a different
/// flat colour passes one in `Piece::flat`; this is the default it starts from.
pub(super) const SURFACE: Rgba = Rgba::new(214, 208, 196);

/// glTF's default `alphaCutoff` in 8-bit terms: under `alphaMode: "MASK"` a
/// texel below this is discarded outright.
///
/// ⚠️ Discarded *before* the depth buffer is written, so a cut-out does not
/// hide the geometry behind it. Write depth first and every leaf and sprite
/// punches a hole through the model.
pub const MASK_CUTOFF: u8 = 128;

/// Keep any texel that is not wholly transparent.
///
/// ⛔ **This is not alpha blending, and must not be read as it.** There is no
/// blending in this rasteriser: a texel is drawn at full strength or not at
/// all. For semi-transparent art that is wrong in the other direction — a
/// faint glow comes out solid — but it is the difference between seeing the
/// sprite's shape and seeing nothing at all (D259).
pub const FAINT_CUTOFF: u8 = 1;

/// An RGBA8 frame, in the layout `egui::ColorImage::from_rgba_unmultiplied`
/// wants: four bytes per pixel, rows top to bottom.
#[derive(Debug, Clone)]
pub struct Image {
    size: Size,
    pixels: Vec<u8>,
}

impl Image {
    pub(super) fn filled(size: Size, background: Background) -> Self {
        let mut pixels = Vec::with_capacity(size.pixels() * 4);
        for y in 0..size.height {
            for x in 0..size.width {
                let colour = background.pixel(x, y, size);
                pixels.extend_from_slice(&[colour.r, colour.g, colour.b, colour.a]);
            }
        }
        Self { size, pixels }
    }

    pub fn size(&self) -> Size {
        self.size
    }

    pub fn as_rgba(&self) -> &[u8] {
        &self.pixels
    }

    /// One pixel, for the tests. The window uploads `as_rgba` wholesale and
    /// never reads a single pixel back, so nothing else calls this.
    #[allow(dead_code)]
    pub fn pixel(&self, x: usize, y: usize) -> Rgba {
        let at = (y * self.size.width + x) * 4;
        Rgba {
            r: self.pixels[at],
            g: self.pixels[at + 1],
            b: self.pixels[at + 2],
            a: self.pixels[at + 3],
        }
    }

    /// Paint one pixel. `wave` draws whole columns through this rather than
    /// through the triangle filler, which has no shape to give it.
    pub(super) fn set(&mut self, x: usize, y: usize, colour: Rgba) {
        let at = (y * self.size.width + x) * 4;
        self.pixels[at] = colour.r;
        self.pixels[at + 1] = colour.g;
        self.pixels[at + 2] = colour.b;
        self.pixels[at + 3] = colour.a;
    }
}

/// The three vertex colours a triangle's corners carry, or nothing.
///
/// ✅ **glTF multiplies `COLOR_0` into the base colour**, which is the
/// `GX_MODULATE` the game programs for a one-layer shape (D247, D251). Much of
/// this game's art is stored greyscale and coloured here: one panel with rivets
/// on it becomes the red, blue and green ones. Dropping it draws Brobot as a
/// white robot with every rivet intact.
pub(super) type Tint = Option<[[u8; 4]; 3]>;

/// What fills a triangle: one flat colour, or a texture sampled across it.
pub(super) enum Paint<'a> {
    Flat {
        colour: Rgba,
        tint: Tint,
    },
    Textured {
        texture: &'a Texture,
        corners: [Uv; 3],
        tint: Tint,
        /// The flat shading term the texel is multiplied by.
        intensity: f32,
        /// How to composite the texel onto what is already there.
        blend: Blend,
        /// The material's `alphaMode` was `MASK`, so a transparent texel is a
        /// hole rather than a dark pixel.
        masked: bool,
        /// The alpha a texel must reach to survive `masked`.
        cutoff: u8,
        /// Wrap mode and UV transform for the base image (D247).
        sampling: &'a Sampling,
        /// The second layer, whose alpha multiplies the base — colour and
        /// alpha alike, which is what the game's TEV program does.
        mask: Option<&'a Mask>,
    },
}

/// How much light the face's own normal catches, in `[AMBIENT, 1]`. One value
/// for the whole triangle, which is what makes facets readable.
pub(super) fn lighting(basis: &Basis, corners: &[Vec3; 3]) -> f32 {
    let normal = (corners[1] - corners[0])
        .cross(corners[2] - corners[0])
        .normalised();
    let mut facing = Vec3::new(
        normal.dot(basis.right),
        normal.dot(basis.up),
        normal.dot(basis.forward),
    );
    // Two-sided: a normal pointing away from the viewer is turned round,
    // so a face lit from behind is shaded rather than left black.
    if facing.z > 0.0 {
        facing = facing.scaled(-1.0);
    }
    let lit = facing.dot(LIGHT.normalised()).max(0.0);
    AMBIENT + (1.0 - AMBIENT) * lit
}

/// Half the cross product of two triangle edges: positive on one side of the
/// line a→b, negative on the other. Doubles as the barycentric weight.
fn edge(a: Point, b: Point, x: f32, y: f32) -> f32 {
    (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x)
}

/// The pixel columns or rows a triangle can touch, clipped to the frame.
struct Span {
    start: usize,
    end: usize,
}

fn span(low: f32, high: f32, limit: usize) -> Option<Span> {
    if !low.is_finite() || !high.is_finite() || high < 0.0 || low >= limit as f32 {
        return None;
    }
    let start = low.floor().max(0.0) as usize;
    let end = (high.ceil() as usize).min(limit.saturating_sub(1));
    if start > end {
        return None;
    }
    Some(Span { start, end })
}

/// A pixel's position inside the triangle, as the three edge weights that
/// produced it — barycentric, before the perspective divide.
struct Weights {
    at: [f32; 3],
}

impl Weights {
    /// The texture coordinate at this pixel, corrected for perspective.
    ///
    /// ⚠️ Interpolating u and v directly across screen space is wrong the
    /// moment a triangle is not parallel to the screen — the texture slides
    /// and swims as the camera orbits. Each corner is weighted by its own 1/z
    /// and the sum divided by the interpolated 1/z, which is what makes the
    /// mapping hold. The divisor is positive because every corner has already
    /// been rejected unless it sits in front of the near plane.
    /// The vertex colour at this pixel, on the same perspective-correct
    /// weights the UV uses. ⚠️ Interpolating it in screen space instead makes
    /// a colour gradient slide as the camera orbits, exactly as a texture does.
    fn tint(&self, triangle: &[Point; 3], corners: &[[u8; 4]; 3]) -> [f32; 4] {
        // ⚠️ A flat triangle must come out exactly flat. Interpolating three
        // equal corners still drifts a unit either way through the float
        // divide, which turns one painted panel into two near-identical
        // colours — visible to a palette count, and to nothing else.
        if corners[0] == corners[1] && corners[1] == corners[2] {
            return corners[0].map(f32::from);
        }
        let scaled = [
            self.at[0] * triangle[0].inv_z,
            self.at[1] * triangle[1].inv_z,
            self.at[2] * triangle[2].inv_z,
        ];
        let total = scaled[0] + scaled[1] + scaled[2];
        if !total.is_finite() || total <= 0.0 {
            return corners[0].map(f32::from);
        }
        std::array::from_fn(|channel| {
            (scaled[0] * f32::from(corners[0][channel])
                + scaled[1] * f32::from(corners[1][channel])
                + scaled[2] * f32::from(corners[2][channel]))
                / total
        })
    }

    fn uv(&self, triangle: &[Point; 3], corners: &[Uv; 3]) -> Uv {
        let scaled = [
            self.at[0] * triangle[0].inv_z,
            self.at[1] * triangle[1].inv_z,
            self.at[2] * triangle[2].inv_z,
        ];
        let total = scaled[0] + scaled[1] + scaled[2];
        if !total.is_finite() || total <= 0.0 {
            return corners[0];
        }
        Uv::new(
            (scaled[0] * corners[0].u + scaled[1] * corners[1].u + scaled[2] * corners[2].u)
                / total,
            (scaled[0] * corners[0].v + scaled[1] * corners[1].v + scaled[2] * corners[2].v)
                / total,
        )
    }
}

/// One channel multiplied by a 0..255 tint, which is what `GX_MODULATE` does.
fn scale(value: u8, by: f32) -> u8 {
    ((f32::from(value) * by) / 255.0).clamp(0.0, 255.0) as u8
}

/// The tint at this pixel, or an all-255 multiply-by-one where there is none.
fn tinting(tint: &Tint, triangle: &[Point; 3], weights: &Weights) -> [f32; 4] {
    match tint {
        Some(corners) => weights.tint(triangle, corners),
        None => [255.0; 4],
    }
}

/// A pixel's colour and how much of it to lay down.
///
/// ⚠️ `alpha` is 255 for everything that is not blended, so the caller's
/// composite is a no-op there rather than a special case.
pub(super) struct Fragment {
    colour: Rgba,
    alpha: u8,
    blend: Blend,
}

/// The colour a pixel takes, or `None` when a masked texel discards it.
///
/// ⚠️ **The mask is applied before the cutoff, not after.** The game multiplies
/// the alphas in the TEV and only then runs the alpha compare, so a texel the
/// base leaves opaque and the mask leaves clear is a hole (D247). Testing the
/// base's own alpha first would draw the shape solid and look plausible.
fn fill(paint: &Paint, triangle: &[Point; 3], weights: &Weights) -> Option<Fragment> {
    match paint {
        Paint::Flat { colour, tint } => {
            let shade = tinting(tint, triangle, weights);
            Some(Fragment {
                colour: Rgba::new(
                    scale(colour.r, shade[0]),
                    scale(colour.g, shade[1]),
                    scale(colour.b, shade[2]),
                ),
                alpha: 255,
                blend: Blend::Opaque,
            })
        }
        Paint::Textured {
            texture,
            corners,
            tint,
            intensity,
            blend,
            masked,
            cutoff,
            sampling,
            mask,
        } => {
            let uv = weights.uv(triangle, corners);
            let mut texel = texture.sample(uv.u, uv.v, sampling);
            if let Some(over) = mask {
                let alpha = over.texture.sample(uv.u, uv.v, &over.sampling).a as u16;
                let scale = |value: u8| ((value as u16 * alpha) / 255) as u8;
                texel = Texel {
                    r: scale(texel.r),
                    g: scale(texel.g),
                    b: scale(texel.b),
                    a: scale(texel.a),
                };
            }
            let shade = tinting(tint, triangle, weights);
            texel = Texel {
                r: scale(texel.r, shade[0]),
                g: scale(texel.g, shade[1]),
                b: scale(texel.b, shade[2]),
                a: scale(texel.a, shade[3]),
            };
            if *masked && texel.a < *cutoff {
                return None;
            }
            Some(Fragment {
                colour: Rgba::new(texel.r, texel.g, texel.b).shaded(*intensity),
                alpha: if matches!(blend, Blend::Opaque) {
                    255
                } else {
                    texel.a
                },
                blend: *blend,
            })
        }
    }
}

pub(super) fn raster(image: &mut Image, depth: &mut [f32], triangle: &[Point; 3], paint: &Paint) {
    let area = edge(triangle[0], triangle[1], triangle[2].x, triangle[2].y);
    if area.abs() < 1e-9 {
        return;
    }
    // Winding is not guaranteed, so the sign is normalised instead of culled.
    let turn = if area < 0.0 { -1.0 } else { 1.0 };
    let area = area * turn;

    let xs = triangle.map(|corner| corner.x);
    let ys = triangle.map(|corner| corner.y);
    let size = image.size();
    let (Some(columns), Some(rows)) = (
        span(fold_min(&xs), fold_max(&xs), size.width),
        span(fold_min(&ys), fold_max(&ys), size.height),
    ) else {
        return;
    };

    for y in rows.start..=rows.end {
        let at_y = y as f32 + 0.5;
        for x in columns.start..=columns.end {
            let at_x = x as f32 + 0.5;
            let w0 = edge(triangle[1], triangle[2], at_x, at_y) * turn;
            let w1 = edge(triangle[2], triangle[0], at_x, at_y) * turn;
            let w2 = edge(triangle[0], triangle[1], at_x, at_y) * turn;
            if w0 < 0.0 || w1 < 0.0 || w2 < 0.0 {
                continue;
            }
            let near =
                (w0 * triangle[0].inv_z + w1 * triangle[1].inv_z + w2 * triangle[2].inv_z) / area;
            let slot = y * size.width + x;
            // Larger 1/z is nearer, so this keeps the closest fragment
            // regardless of the order faces arrive in.
            if near <= depth[slot] {
                continue;
            }
            let weights = Weights { at: [w0, w1, w2] };
            let Some(fragment) = fill(paint, triangle, &weights) else {
                continue;
            };
            if fragment.blend == Blend::Opaque {
                depth[slot] = near;
                image.set(x, y, fragment.colour);
                continue;
            }
            // ⛔ **Depth is not written for a blended fragment.** A
            // semi-transparent sprite must not occlude what is drawn after it;
            // writing depth here makes the first sprite of a stack hide every
            // one behind it, which looks exactly like the parts not running.
            let under = image.pixel(x, y);
            image.set(
                x,
                y,
                mix(fragment.blend, fragment.colour, fragment.alpha, under),
            );
        }
    }
}
fn fold_min(values: &[f32; 3]) -> f32 {
    values.iter().copied().fold(f32::INFINITY, f32::min)
}

fn fold_max(values: &[f32; 3]) -> f32 {
    values.iter().copied().fold(f32::NEG_INFINITY, f32::max)
}

mod blend;

#[cfg(test)]
mod tests;

#[cfg(test)]
mod texture_tests;
