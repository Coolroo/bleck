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
use crate::data::mesh::{Blend, Mask, Modulate, Uv, Vec3};
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
        let texel = &mut self.pixels[at..at + 4];
        texel[0] = colour.r;
        texel[1] = colour.g;
        texel[2] = colour.b;
        texel[3] = colour.a;
    }

    /// Cut the frame into `count` runs of rows, each carrying its own slice of
    /// the depth buffer.
    ///
    /// ⚠️ **Rows, not tiles.** A run of whole rows is contiguous in both
    /// buffers, so the split is a `chunks_mut` and no band can reach a pixel
    /// another one owns — which is what lets them be filled at the same time.
    pub(super) fn bands<'a>(&'a mut self, depth: &'a mut [f32], count: usize) -> Vec<Band<'a>> {
        let size = self.size;
        let rows = size.height.div_ceil(count.max(1)).max(1);
        self.pixels
            .chunks_mut(rows * size.width * 4)
            .zip(depth.chunks_mut(rows * size.width))
            .enumerate()
            .map(|(index, (pixels, depth))| Band {
                top: index * rows,
                rows: pixels.len() / (size.width * 4),
                pixels,
                depth,
                size,
            })
            .collect()
    }
}

/// A run of the frame's rows, and the depth over the same run.
///
/// ⚠️ **A band holds its rows outright**, so several can be filled at once
/// without any of them seeing another's pixels. `top` is what keeps the edge
/// test in the whole frame's coordinates: a triangle is projected once, and each
/// band fills only the part of it that lands in its own rows.
pub(super) struct Band<'a> {
    pixels: &'a mut [u8],
    depth: &'a mut [f32],
    /// The whole frame, not the band — `span` clips a triangle against the
    /// frame and only then against the rows this one holds.
    size: Size,
    top: usize,
    rows: usize,
}

impl<'a> Band<'a> {
    /// The whole frame as one band. Only the tests reach for it: `scene` splits
    /// a frame by core count and fills the parts at once.
    #[cfg(test)]
    pub(super) fn whole(image: &'a mut Image, depth: &'a mut [f32]) -> Self {
        let size = image.size;
        Self {
            pixels: &mut image.pixels,
            depth,
            size,
            top: 0,
            rows: size.height,
        }
    }

    /// The pixel at an index the caller already holds. The triangle filler works
    /// one out for the depth test, and reaching back through `x, y` costs it a
    /// multiply and four bounds checks per fragment.
    fn at(&self, slot: usize) -> Rgba {
        let texel = &self.pixels[slot * 4..slot * 4 + 4];
        Rgba {
            r: texel[0],
            g: texel[1],
            b: texel[2],
            a: texel[3],
        }
    }

    fn put(&mut self, slot: usize, colour: Rgba) {
        let texel = &mut self.pixels[slot * 4..slot * 4 + 4];
        texel[0] = colour.r;
        texel[1] = colour.g;
        texel[2] = colour.b;
        texel[3] = colour.a;
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
        /// The constant colour every texel is multiplied by — the material's
        /// own, with the drawing node's alpha already folded into it (D280).
        modulate: Modulate,
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

/// One edge of a triangle, kept as the four constants `edge` would otherwise
/// re-subtract at every pixel of it.
///
/// ⚠️ **The same arithmetic in the same order**, only hoisted: `row` is the
/// left-hand product and `at` the right-hand one, so a weight comes out bit for
/// bit what `edge` returns. A cheaper recurrence — stepping the weight along the
/// row by adding `dy` — would drift, and the drift decides pixels on the
/// boundary.
#[derive(Debug, Clone, Copy)]
struct Rail {
    ax: f32,
    ay: f32,
    dx: f32,
    dy: f32,
}

impl Rail {
    fn between(a: Point, b: Point) -> Self {
        Self {
            ax: a.x,
            ay: a.y,
            dx: b.x - a.x,
            dy: b.y - a.y,
        }
    }

    /// The half of the weight that only moves with the row.
    fn row(&self, at_y: f32) -> f32 {
        self.dx * (at_y - self.ay)
    }

    fn at(&self, row: f32, at_x: f32) -> f32 {
        row - self.dy * (at_x - self.ax)
    }
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

/// Below this width a bounding box is walked whole rather than solved for.
const NARROW: usize = 24;

/// How far a row of the bounding box has to be walked at all.
///
/// A triangle is convex, so each row meets it in one run of pixels; the rest of
/// the box is edge tests that can only fail. Between a fifth and a half of the
/// box is inside on real effect geometry, and a fan of small triangles is the
/// worse end of that.
///
/// ⚠️ **Narrowing only — the edge test still decides.** Each bound is solved in
/// f64 and then widened by a pixel, so a rounding difference between this and
/// the f32 test below can only leave a pixel in the run for that test to reject.
/// Trusting the solve outright would make the boundary depend on which of the
/// two saw it first.
fn run(rails: &[Rail; 3], rows: &[f32; 3], turn: f32, columns: &Span) -> Option<Span> {
    let (mut low, mut high) = (columns.start as f64, columns.end as f64);
    for (rail, &row) in rails.iter().zip(rows) {
        // The weight along the row is `base + slope * (x + 0.5)`, which is the
        // edge test rearranged to put x on its own.
        let slope = -f64::from(rail.dy) * f64::from(turn);
        let base = (f64::from(row) + f64::from(rail.dy) * f64::from(rail.ax)) * f64::from(turn);
        if !slope.is_finite() || !base.is_finite() {
            return Some(Span {
                start: columns.start,
                end: columns.end,
            });
        }
        if slope == 0.0 {
            if base < 0.0 {
                return None;
            }
            continue;
        }
        let crosses = -base / slope - 0.5;
        if !crosses.is_finite() {
            continue;
        }
        if slope > 0.0 {
            low = low.max(crosses - 1.0);
        } else {
            high = high.min(crosses + 1.0);
        }
    }
    let start = (low.ceil().max(columns.start as f64)) as usize;
    let end = (high.floor().min(columns.end as f64)) as usize;
    if start > end || high < columns.start as f64 {
        return None;
    }
    Some(Span { start, end })
}

/// A pixel's position inside the triangle, as the three edge weights that
/// produced it — barycentric, before the perspective divide.
struct Weights {
    /// Each weight scaled by its corner's 1/z, and their sum.
    ///
    /// ⚠️ **Carried rather than worked out twice.** The depth test needs that
    /// sum and so does every interpolation under it, and the two were computing
    /// it separately — the same three multiplies and two adds, at every pixel of
    /// every textured triangle.
    scaled: [f32; 3],
    total: f32,
}

impl Weights {
    fn of(at: [f32; 3], triangle: &[Point; 3]) -> Self {
        let scaled = [
            at[0] * triangle[0].inv_z,
            at[1] * triangle[1].inv_z,
            at[2] * triangle[2].inv_z,
        ];
        Self {
            total: scaled[0] + scaled[1] + scaled[2],
            scaled,
        }
    }

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
    fn tint(&self, corners: &[[u8; 4]; 3]) -> [f32; 4] {
        // ⚠️ A flat triangle must come out exactly flat. Interpolating three
        // equal corners still drifts a unit either way through the float
        // divide, which turns one painted panel into two near-identical
        // colours — visible to a palette count, and to nothing else.
        if corners[0] == corners[1] && corners[1] == corners[2] {
            return corners[0].map(f32::from);
        }
        let scaled = self.scaled;
        let total = self.total;
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

    fn uv(&self, corners: &[Uv; 3]) -> Uv {
        let scaled = self.scaled;
        let total = self.total;
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
fn tinting(tint: &Tint, weights: &Weights) -> [f32; 4] {
    match tint {
        Some(corners) => weights.tint(corners),
        None => [255.0; 4],
    }
}

/// A per-pixel tint with the surface's constant colour folded into it.
///
/// ⚠️ **One chain of multiplies, not two passes.** The vertex colour and the
/// material's colour register are both `GX_MODULATE` inputs, so combining them
/// here keeps a single rounding step; scaling the texel twice loses a level of
/// every faint channel.
fn modulated(shade: [f32; 4], by: Modulate) -> [f32; 4] {
    let channels = [by.red, by.green, by.blue, by.alpha];
    std::array::from_fn(|channel| shade[channel] * f32::from(channels[channel]) / 255.0)
}

/// A pixel's colour and how much of it to lay down.
///
/// ⚠️ `alpha` is 255 for everything that is not blended, so the caller's
/// composite is a no-op there rather than a special case.
#[derive(Debug, Clone, Copy)]
pub(super) struct Fragment {
    colour: Rgba,
    alpha: u8,
    blend: Blend,
}

/// What `fill` would work out again at every pixel of a triangle and need not.
///
/// ⚠️ **Vertex colour is what decides which arm applies**, and effect art never
/// carries any: an effect part's colour comes from its material's register,
/// which is one value for the whole draw. So `Ready::Whole` and `Ready::Shade`
/// are the paths every effect takes, and `Interpolated` is the model viewport's.
enum Ready {
    /// A flat colour with nothing to interpolate is the same fragment at every
    /// pixel, so the inner loop is a depth test and a store.
    Whole(Fragment),
    /// The tint chain is one value across the triangle; the texel it multiplies
    /// is not.
    Shade([f32; 4]),
    /// The corners disagree, so every pixel is weighed on its own.
    Interpolated,
}

impl Ready {
    /// ⚠️ **The same chain of multiplies `fill` runs, evaluated once.** A tint
    /// of all-255 is what `tinting` returns for a triangle with no vertex
    /// colour, so folding the material's register into it here is bit for bit
    /// what the per-pixel path produced.
    fn of(paint: &Paint) -> Self {
        match paint {
            Paint::Flat { tint: Some(_), .. } | Paint::Textured { tint: Some(_), .. } => {
                Self::Interpolated
            }
            Paint::Flat { colour, .. } => Self::Whole(Fragment {
                colour: Rgba::new(
                    scale(colour.r, 255.0),
                    scale(colour.g, 255.0),
                    scale(colour.b, 255.0),
                ),
                alpha: 255,
                blend: Blend::Opaque,
            }),
            Paint::Textured { modulate, .. } => Self::Shade(modulated([255.0; 4], *modulate)),
        }
    }
}

/// The colour a pixel takes, or `None` when a masked texel discards it.
///
/// ⚠️ **The mask is applied before the cutoff, not after.** The game multiplies
/// the alphas in the TEV and only then runs the alpha compare, so a texel the
/// base leaves opaque and the mask leaves clear is a hole (D247). Testing the
/// base's own alpha first would draw the shape solid and look plausible.
fn fill(paint: &Paint, weights: &Weights, ready: &Ready) -> Option<Fragment> {
    if let Ready::Whole(fragment) = ready {
        return Some(*fragment);
    }
    match paint {
        Paint::Flat { colour, tint } => {
            let shade = tinting(tint, weights);
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
            modulate,
            mask,
        } => {
            let uv = weights.uv(corners);
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
            // ⚠️ **Before the alpha compare, not after** — the same order the
            // mask above takes, and for the same reason: the game multiplies
            // its colour register in and only then runs the compare, so a
            // surface the material fades to nothing is a hole (D247, D280).
            let shade = match ready {
                Ready::Shade(constant) => *constant,
                _ => modulated(tinting(tint, weights), *modulate),
            };
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

/// Fill one triangle into whichever rows of the frame `band` holds.
pub(super) fn raster(band: &mut Band, triangle: &[Point; 3], paint: &Paint) {
    let area = edge(triangle[0], triangle[1], triangle[2].x, triangle[2].y);
    if area.abs() < 1e-9 {
        return;
    }
    // Winding is not guaranteed, so the sign is normalised instead of culled.
    let turn = if area < 0.0 { -1.0 } else { 1.0 };
    let area = area * turn;

    let xs = triangle.map(|corner| corner.x);
    let ys = triangle.map(|corner| corner.y);
    let size = band.size;
    let (Some(columns), Some(rows)) = (
        span(fold_min(&xs), fold_max(&xs), size.width),
        span(fold_min(&ys), fold_max(&ys), size.height),
    ) else {
        return;
    };

    let rails = [
        Rail::between(triangle[1], triangle[2]),
        Rail::between(triangle[2], triangle[0]),
        Rail::between(triangle[0], triangle[1]),
    ];
    let ready = Ready::of(paint);
    // ⚠️ A narrow triangle is walked whole. Solving for a row's ends costs three
    // divides, which is more than testing the handful of pixels it would save —
    // and `mini_gameclear` alone issues 26,851 triangles a frame, nearly all of
    // them a few pixels across.
    let solve = columns.end - columns.start >= NARROW;
    // The rows this band owns, and no others. A triangle spanning the frame is
    // handed to every band and each fills its own slice of it.
    let first = rows.start.max(band.top);
    let last = rows.end.min(band.top + band.rows.saturating_sub(1));
    if band.rows == 0 || first > last {
        return;
    }

    for y in first..=last {
        let at_y = y as f32 + 0.5;
        let held = [rails[0].row(at_y), rails[1].row(at_y), rails[2].row(at_y)];
        let across = if solve {
            match run(&rails, &held, turn, &columns) {
                Some(across) => across,
                None => continue,
            }
        } else {
            Span {
                start: columns.start,
                end: columns.end,
            }
        };
        let line = (y - band.top) * size.width;
        for x in across.start..=across.end {
            let at_x = x as f32 + 0.5;
            let w0 = rails[0].at(held[0], at_x) * turn;
            let w1 = rails[1].at(held[1], at_x) * turn;
            let w2 = rails[2].at(held[2], at_x) * turn;
            if w0 < 0.0 || w1 < 0.0 || w2 < 0.0 {
                continue;
            }
            let weights = Weights::of([w0, w1, w2], triangle);
            let near = weights.total / area;
            let slot = line + x;
            // Larger 1/z is nearer, so this keeps the closest fragment
            // regardless of the order faces arrive in.
            if near <= band.depth[slot] {
                continue;
            }
            let Some(fragment) = fill(paint, &weights, &ready) else {
                continue;
            };
            if fragment.blend == Blend::Opaque {
                band.depth[slot] = near;
                band.put(slot, fragment.colour);
                continue;
            }
            // ⛔ **Depth is not written for a blended fragment.** A
            // semi-transparent sprite must not occlude what is drawn after it;
            // writing depth here makes the first sprite of a stack hide every
            // one behind it, which looks exactly like the parts not running.
            let under = band.at(slot);
            band.put(
                slot,
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
