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

use super::camera::{Basis, Point};
use super::{Background, Rgba, Size};
use crate::data::mesh::{Mask, Uv, Vec3};
use crate::data::texture::{Sampling, Texel, Texture};

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

/// The colour a pixel takes, or `None` when a masked texel discards it.
///
/// ⚠️ **The mask is applied before the cutoff, not after.** The game multiplies
/// the alphas in the TEV and only then runs the alpha compare, so a texel the
/// base leaves opaque and the mask leaves clear is a hole (D247). Testing the
/// base's own alpha first would draw the shape solid and look plausible.
fn fill(paint: &Paint, triangle: &[Point; 3], weights: &Weights) -> Option<Rgba> {
    match paint {
        Paint::Flat { colour, tint } => {
            let shade = tinting(tint, triangle, weights);
            Some(Rgba::new(
                scale(colour.r, shade[0]),
                scale(colour.g, shade[1]),
                scale(colour.b, shade[2]),
            ))
        }
        Paint::Textured {
            texture,
            corners,
            tint,
            intensity,
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
            Some(Rgba::new(texel.r, texel.g, texel.b).shaded(*intensity))
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
            let Some(colour) = fill(paint, triangle, &weights) else {
                continue;
            };
            depth[slot] = near;
            image.set(x, y, colour);
        }
    }
}

fn fold_min(values: &[f32; 3]) -> f32 {
    values.iter().copied().fold(f32::INFINITY, f32::min)
}

fn fold_max(values: &[f32; 3]) -> f32 {
    values.iter().copied().fold(f32::NEG_INFINITY, f32::max)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::mesh::Mesh;
    use crate::render::fixtures::{covered, flat, head_on, FRAME};
    use crate::render::{render, Camera};

    /// Facing the camera at z = +1, covering the middle of the frame.
    const NEAR_QUAD: &str = "v -2 -2 1\nv 2 -2 1\nv 2 2 1\nv -2 2 1\nf 1 2 3 4\n";

    /// Tilted, and behind the near quad everywhere it overlaps it.
    const FAR_QUAD: &str = "v -2 -2 -1\nv 2 -2 -5\nv 2 2 -5\nv -2 2 -1\nf 1 2 3 4\n";

    fn centre_of(text: &str) -> Rgba {
        let mesh = Mesh::parse(text).expect("quad parses");
        let image = render(&mesh, &flat(head_on()), FRAME);
        image.pixel(FRAME.width / 2, FRAME.height / 2)
    }

    #[test]
    fn the_depth_buffer_keeps_the_nearer_face_whatever_the_draw_order() {
        // ⚠️ The instrument first: unless the two quads shade differently,
        // every assertion below would pass without a depth buffer at all.
        let near = centre_of(NEAR_QUAD);
        let far = centre_of(FAR_QUAD);
        let sky = Background::DarkGrey.pixel(0, 0, FRAME);
        assert_ne!(near, sky, "the near quad did not draw");
        assert_ne!(far, sky, "the far quad did not draw");
        assert_ne!(near, far, "the two quads are indistinguishable");

        // Far face second: a painter's-algorithm renderer would end up
        // showing it, because it is drawn last.
        let mut both = String::from(NEAR_QUAD);
        both.push_str(&shifted(FAR_QUAD, 4));
        assert_eq!(centre_of(&both), near, "the far quad painted over the near");

        let mut reversed = String::from(FAR_QUAD);
        reversed.push_str(&shifted(NEAR_QUAD, 4));
        assert_eq!(centre_of(&reversed), near, "draw order changed the result");
    }

    /// Re-index a mesh's faces so it can be appended after `offset` vertices.
    fn shifted(text: &str, offset: usize) -> String {
        text.lines()
            .map(|line| {
                if let Some(face) = line.strip_prefix("f ") {
                    let corners: Vec<String> = face
                        .split_whitespace()
                        .map(|index| (index.parse::<usize>().expect("index") + offset).to_string())
                        .collect();
                    format!("f {}\n", corners.join(" "))
                } else {
                    format!("{line}\n")
                }
            })
            .collect()
    }

    /// ⚠️ A triangle must not fill its own bounding box. The corner outside it
    /// is the assertion that matters: coverage and framing tests both still
    /// pass when the edge test is removed, because a cube's silhouette nearly
    /// fills its box anyway.
    #[test]
    fn a_triangle_covers_only_its_own_half_of_its_bounding_box() {
        // Right-angled at the bottom left, in the plane the camera faces.
        let mesh = Mesh::parse("v -2 -2 0\nv 2 -2 0\nv -2 2 0\nf 1 2 3\n").expect("parses");
        let image = render(&mesh, &flat(head_on()), FRAME);
        let sky = Background::DarkGrey.pixel(0, 0, FRAME);

        assert_ne!(image.pixel(60, 150), sky, "inside the triangle");
        assert_ne!(image.pixel(45, 60), sky, "inside, near the tall corner");
        assert_eq!(image.pixel(150, 60), sky, "the opposite corner of the box");
        assert_eq!(image.pixel(160, 40), sky, "further into that corner");
    }

    #[test]
    fn a_zero_area_face_draws_nothing() {
        let point = Mesh::parse("v 1 1 1\nv 1 1 1\nv 1 1 1\nf 1 2 3\n").expect("parses");
        let image = render(&point, &flat(Camera::fit(point.bounds())), FRAME);
        assert_eq!(covered(&image), 0);
    }

    /// ⚠️ Not asserted as zero. Three collinear points project to a line whose
    /// computed area is float noise rather than exactly 0, so the claim is that
    /// a degenerate face cannot smear across the frame — not that it is
    /// invisible.
    #[test]
    fn a_collinear_face_covers_almost_nothing() {
        let flat_line = Mesh::parse("v 0 0 0\nv 1 1 1\nv 2 2 2\nf 1 2 3\n").expect("parses");
        let image = render(&flat_line, &flat(Camera::fit(flat_line.bounds())), FRAME);
        let share = covered(&image) as f32 / FRAME.pixels() as f32;
        assert!(
            share < 0.01,
            "a collinear face covered {share} of the frame"
        );
    }

    #[test]
    fn shading_darkens_a_face_turned_away_from_the_light() {
        let basis = Basis::of(&head_on());
        let shade = |corners: &[Vec3; 3]| SURFACE.shaded(lighting(&basis, corners));
        let facing = shade(&[
            Vec3::new(-1.0, -1.0, 0.0),
            Vec3::new(1.0, -1.0, 0.0),
            Vec3::new(1.0, 1.0, 0.0),
        ]);
        // Same triangle wound the other way: two-sided shading must give the
        // same colour, or half a model with mixed winding would go dark.
        let reversed = shade(&[
            Vec3::new(1.0, 1.0, 0.0),
            Vec3::new(1.0, -1.0, 0.0),
            Vec3::new(-1.0, -1.0, 0.0),
        ]);
        assert_eq!(facing, reversed);

        // Edge-on to the camera, so it catches almost none of the light.
        let edge_on = shade(&[
            Vec3::new(0.0, -1.0, -1.0),
            Vec3::new(0.0, -1.0, 1.0),
            Vec3::new(0.0, 1.0, 1.0),
        ]);
        assert!(edge_on.r < facing.r, "{edge_on:?} vs {facing:?}");
        assert!(edge_on.r >= SURFACE.shaded(AMBIENT).r, "ambient floor lost");
    }
}

/// Painting a mesh with the texture its file carried.
///
/// ⚠️ Every assertion here is on the pixel buffer, because the machine this is
/// built on cannot capture its own screen — a texture that samples the wrong
/// texel, or the right texel at the wrong place, looks fine in a screenshot
/// nobody can take.
#[cfg(test)]
mod texture_tests {
    use super::*;
    use crate::data::gltf;
    use crate::data::gltf::fixtures::{bare_quad, painted_quads, textured_quad, tiled, QUAD_UVS};
    use crate::data::mesh::Mesh;
    use crate::data::texture::Texel;
    use crate::render::fixtures::{covered, flat, head_on, FRAME};
    use crate::render::render;

    const RED: Texel = Texel {
        r: 255,
        g: 0,
        b: 0,
        a: 255,
    };
    const GREEN: Texel = Texel {
        r: 0,
        g: 255,
        b: 0,
        a: 255,
    };
    const BLUE: Texel = Texel {
        r: 0,
        g: 0,
        b: 255,
        a: 255,
    };
    const WHITE: Texel = Texel {
        r: 255,
        g: 255,
        b: 255,
        a: 255,
    };
    const CLEAR: Texel = Texel {
        r: 255,
        g: 0,
        b: 255,
        a: 0,
    };

    fn loaded(raw: &[u8]) -> Mesh {
        gltf::parse(raw).expect("fixture parses").into_mesh()
    }

    /// The surface of a mesh's first shape, for the tests that hand a texture
    /// straight to `raster` rather than going through `render`.
    fn only_surface(mesh: &Mesh) -> crate::data::mesh::Surface<'_> {
        mesh.batches()
            .next()
            .and_then(|batch| batch.surface)
            .expect("a surface")
    }

    /// The quad fills screen 31.5..168.5 on both axes, so these four points sit
    /// one in each of its quarters and well clear of the texel boundary at 100.
    const QUARTERS: [(usize, usize); 4] = [(50, 50), (150, 50), (50, 150), (150, 150)];

    /// Which channels a pixel has any of. Enough to tell the fixture's four
    /// texels apart without pinning the exact shading term, which would make
    /// this a test of the light direction instead.
    fn channels(pixel: Rgba) -> [bool; 3] {
        [pixel.r > 0, pixel.g > 0, pixel.b > 0]
    }

    /// ⚠️ The test the whole feature exists for, and the one that catches a
    /// flipped or transposed UV: four distinct texels, four screen quarters,
    /// each named. glTF's origin is the image's top-left, so swapping u for v
    /// or flipping either axis moves at least two of these.
    #[test]
    fn each_texel_lands_in_its_own_quarter_of_the_frame() {
        let mesh = loaded(&textured_quad(QUAD_UVS, 2, 2, &[RED, GREEN, BLUE, WHITE]));
        let image = render(&mesh, &flat(head_on()), FRAME);
        let sky = Background::DarkGrey.pixel(0, 0, FRAME);

        let seen = QUARTERS.map(|(x, y)| image.pixel(x, y));
        for (pixel, at) in seen.iter().zip(QUARTERS) {
            assert_ne!(*pixel, sky, "nothing was drawn at {at:?}");
        }
        assert_eq!(channels(seen[0]), [true, false, false], "top left is red");
        assert_eq!(
            channels(seen[1]),
            [false, true, false],
            "top right is green"
        );
        assert_eq!(
            channels(seen[2]),
            [false, false, true],
            "bottom left is blue"
        );
        assert_eq!(
            channels(seen[3]),
            [true, true, true],
            "bottom right is white"
        );
        assert!(
            seen[3].r > 150,
            "the white texel came out dark: {:?}",
            seen[3]
        );
    }

    /// The same claim in the form the report was made in: a textured model is
    /// not one flat colour any more.
    #[test]
    fn a_textured_model_is_no_longer_a_single_grey() {
        let textured = render(
            &loaded(&textured_quad(QUAD_UVS, 2, 2, &[RED, GREEN, BLUE, WHITE])),
            &flat(head_on()),
            FRAME,
        );
        let plain = render(&loaded(&bare_quad()), &flat(head_on()), FRAME);

        let sky = Background::DarkGrey.pixel(0, 0, FRAME);
        let distinct = |image: &Image| {
            let mut seen: Vec<Rgba> = Vec::new();
            for (x, y) in QUARTERS {
                let pixel = image.pixel(x, y);
                if pixel != sky && !seen.contains(&pixel) {
                    seen.push(pixel);
                }
            }
            seen.len()
        };
        assert_eq!(distinct(&plain), 1, "flat shading stopped being flat");
        assert_eq!(distinct(&textured), 4, "the texture was not sampled");
    }

    /// ⚠️ The regression guard. An untextured mesh must reach exactly the
    /// pixels it did before any of this existed, so the two paths are compared
    /// against each other rather than against a remembered number.
    #[test]
    fn an_untextured_mesh_draws_exactly_what_the_obj_path_draws() {
        let from_gltf = render(&loaded(&bare_quad()), &flat(head_on()), FRAME);
        let obj = Mesh::parse("v -2 -2 0\nv 2 -2 0\nv 2 2 0\nv -2 2 0\nf 1 2 3\nf 1 3 4\n")
            .expect("the same quad as OBJ");
        let from_obj = render(&obj, &flat(head_on()), FRAME);

        assert!(covered(&from_gltf) > 10_000, "the control drew nothing");
        assert_eq!(
            crate::render::fixtures::differing(&from_gltf, &from_obj),
            0,
            "the untextured path changed"
        );
    }

    /// ⚠️ `alphaMode: "MASK"`. Cut-out art is most of this game's texture set,
    /// and a renderer that ignores alpha fills every one of those pixels with
    /// black rather than leaving the background showing.
    #[test]
    fn a_fully_transparent_masked_texture_leaves_only_the_background() {
        let mesh = loaded(&textured_quad(QUAD_UVS, 1, 1, &[CLEAR]));
        assert!(only_surface(&mesh).masked, "MASK not read");
        let image = render(&mesh, &flat(head_on()), FRAME);
        assert_eq!(covered(&image), 0, "a transparent quad was drawn anyway");
    }

    /// ✅ **A second layer's alpha multiplies the first** (D247), colour and
    /// alpha alike. Built rather than loaded, so the expected frame is exact:
    /// the base is opaque white everywhere and only the mask decides.
    ///
    /// ⚠️ **The control is the same quad with no mask**, which must draw. A
    /// test that only checked the masked frame was empty would pass on a
    /// renderer that had stopped drawing anything.
    #[test]
    fn a_second_layer_masks_the_first_rather_than_replacing_it() {
        let opaque = Texel {
            r: 255,
            g: 255,
            b: 255,
            a: 255,
        };
        let base =
            Texture::decode(&crate::data::texture::png(1, 1, &[opaque])).expect("a 1x1 white png");
        let draw = |mask: Option<Mask>| {
            let mut image = Image::filled(FRAME, Background::DarkGrey);
            let mut depth = vec![f32::NEG_INFINITY; FRAME.pixels()];
            raster(
                &mut image,
                &mut depth,
                &[
                    Point {
                        x: 20.0,
                        y: 20.0,
                        inv_z: 0.5,
                    },
                    Point {
                        x: 180.0,
                        y: 20.0,
                        inv_z: 0.5,
                    },
                    Point {
                        x: 100.0,
                        y: 180.0,
                        inv_z: 0.5,
                    },
                ],
                &Paint::Textured {
                    tint: None,
                    texture: &base,
                    corners: [Uv::new(0.5, 0.5); 3],
                    intensity: 1.0,
                    masked: true,
                    cutoff: MASK_CUTOFF,
                    sampling: &Sampling::default(),
                    mask: mask.as_ref(),
                },
            );
            covered(&image)
        };
        let over = |texel: Texel| {
            Some(Mask {
                texture: Texture::decode(&crate::data::texture::png(1, 1, &[texel]))
                    .expect("a 1x1 mask"),
                sampling: Sampling::default(),
            })
        };

        let bare = draw(None);
        assert!(bare > 5_000, "the control drew nothing: {bare}");
        assert_eq!(draw(over(opaque)), bare, "an opaque mask removed pixels");
        assert_eq!(draw(over(CLEAR)), 0, "a clear mask left the base drawn");
    }

    /// A cut-out must not take the depth buffer with it. The near triangle is
    /// filled first and discards every pixel; move the depth write above the
    /// discard and the far triangle behind it disappears.
    #[test]
    fn a_discarded_pixel_does_not_hide_what_is_behind_it() {
        let clear = loaded(&textured_quad(QUAD_UVS, 1, 1, &[CLEAR]));
        let surface = only_surface(&clear);
        let corner = |x: f32, y: f32, inv_z: f32| Point { x, y, inv_z };
        let at = |inv_z: f32| {
            [
                corner(20.0, 20.0, inv_z),
                corner(180.0, 20.0, inv_z),
                corner(100.0, 180.0, inv_z),
            ]
        };

        let mut image = Image::filled(FRAME, Background::DarkGrey);
        let mut depth = vec![f32::NEG_INFINITY; FRAME.pixels()];
        let near = at(0.5);
        raster(
            &mut image,
            &mut depth,
            &near,
            &Paint::Textured {
                tint: None,
                texture: surface.texture,
                corners: [Uv::new(0.5, 0.5); 3],
                intensity: 1.0,
                masked: true,
                cutoff: MASK_CUTOFF,
                sampling: surface.sampling,
                mask: surface.mask,
            },
        );
        assert_eq!(covered(&image), 0, "a transparent texel was drawn");

        let far = at(0.1);
        raster(
            &mut image,
            &mut depth,
            &far,
            &Paint::Flat {
                colour: Rgba::new(220, 30, 30),
                tint: None,
            },
        );
        assert!(
            covered(&image) > 5_000,
            "the cut-out claimed the depth buffer and hid the face behind it"
        );
    }

    /// The set of colours a whole frame is made of, background excluded.
    ///
    /// ⚠️ The fixture's quads are coplanar and each carries a single-texel
    /// image, so one colour here is one image sampled — and the count is
    /// directly comparable between the two paths below.
    fn palette(image: &Image) -> Vec<Rgba> {
        let sky = Background::DarkGrey.pixel(0, 0, image.size());
        let mut seen: Vec<Rgba> = Vec::new();
        for y in 0..image.size().height {
            for x in 0..image.size().width {
                let pixel = image.pixel(x, y);
                if pixel != sky && !seen.contains(&pixel) {
                    seen.push(pixel);
                }
            }
        }
        seen
    }

    fn framed(mesh: &Mesh) -> Image {
        let view = crate::render::View {
            camera: crate::render::Camera::fit(mesh.bounds()),
            background: Background::DarkGrey,
        };
        render(mesh, &view, FRAME)
    }

    /// The mesh as the reader built it before D246: whichever material came
    /// first, stretched over every primitive.
    ///
    /// ⚠️ **The control for the test below, and it has to be measured with the
    /// same ruler.** A colour count that cannot tell the old path from the new
    /// one proves nothing about either.
    fn one_image_over_all_of_it(raw: &[u8]) -> Mesh {
        let mut parts = gltf::parse(raw).expect("fixture parses");
        for shape in &mut parts.shapes {
            shape.paint = Some(0);
        }
        parts.into_mesh()
    }

    /// ⛔ **The bug this exists for.** Three primitives, three images: the frame
    /// must hold three colours, and the old path is shown holding one.
    #[test]
    fn each_primitive_is_painted_with_the_image_it_names() {
        let raw = painted_quads(&[Some(RED), Some(GREEN), Some(BLUE)]);

        let before = palette(&framed(&one_image_over_all_of_it(&raw)));
        assert_eq!(
            before.len(),
            1,
            "the control did not reproduce the single-image path: {before:?}"
        );
        assert_eq!(channels(before[0]), [true, false, false], "{before:?}");

        let after = palette(&framed(&loaded(&raw)));
        assert_eq!(
            after.len(),
            3,
            "one image was stretched over all three quads: {after:?}"
        );
        let mut signatures: Vec<[bool; 3]> = after.iter().map(|pixel| channels(*pixel)).collect();
        signatures.sort_unstable();
        assert_eq!(
            signatures,
            [
                [false, false, true],
                [false, true, false],
                [true, false, false]
            ],
            "the three quads did not sample red, green and blue"
        );
    }

    /// The same mesh with every vertex tint cleared: what the viewer drew
    /// before D251, and the control for the three tests below.
    ///
    /// ⚠️ **Measured with the same ruler.** A colour count that cannot tell the
    /// tinted path from the untinted one proves nothing about either.
    fn with_no_tint(raw: &[u8]) -> Mesh {
        let mut parts = gltf::parse(raw).expect("fixture parses");
        parts.colours = None;
        parts.into_mesh()
    }

    /// ⛔ **The bug this exists for** (D251). One greyscale image, two shapes,
    /// two tints: the disc stores one panel and colours it per shape, so the
    /// frame must hold two colours where the old path held one.
    #[test]
    fn one_image_tinted_two_ways_draws_two_colours() {
        let raw = gltf::fixtures::quads_glb(&[
            gltf::fixtures::Quad {
                image: Some(WHITE),
                tint: Some([255, 0, 0, 255]),
            },
            gltf::fixtures::Quad {
                image: Some(WHITE),
                tint: Some([0, 0, 255, 255]),
            },
        ]);

        let before = palette(&framed(&with_no_tint(&raw)));
        assert_eq!(
            before.len(),
            1,
            "the control did not reproduce the untinted path: {before:?}"
        );
        assert_eq!(channels(before[0]), [true, true, true], "{before:?}");

        let after = palette(&framed(&loaded(&raw)));
        assert_eq!(
            after.len(),
            2,
            "the tint did not reach the frame: {after:?}"
        );
        let mut signatures: Vec<[bool; 3]> = after.iter().map(|p| channels(*p)).collect();
        signatures.sort_unstable();
        assert_eq!(
            signatures,
            [[false, false, true], [true, false, false]],
            "one white panel did not come out red and blue: {after:?}"
        );
    }

    /// ⚠️ A shape with no image is drawn with its vertex colour alone — the
    /// `GX_PASSCLR` branch of the game's TEV (D247). 41 of 864 models name no
    /// image at all, so a tint that only reached the textured path would leave
    /// every one of them flat grey.
    #[test]
    fn an_untextured_shape_is_tinted_too() {
        let raw = gltf::fixtures::quads_glb(&[gltf::fixtures::Quad {
            image: None,
            tint: Some([255, 0, 0, 255]),
        }]);
        let before = palette(&framed(&with_no_tint(&raw)));
        assert_eq!(before.len(), 1, "{before:?}");
        assert_eq!(channels(before[0]), [true, true, true], "{before:?}");

        let after = palette(&framed(&loaded(&raw)));
        assert_eq!(after.len(), 1, "{after:?}");
        assert_eq!(
            channels(after[0]),
            [true, false, false],
            "an untextured shape ignored its vertex colour: {after:?}"
        );
    }

    /// ⚠️ **The regression guard for the 524 models that carry no tint.** A
    /// primitive without `COLOR_0` sits beside one that has it, and must not
    /// borrow the neighbour's — which is the span bug UVs already had.
    #[test]
    fn a_primitive_with_no_tint_keeps_its_own_colour() {
        let raw = gltf::fixtures::quads_glb(&[
            gltf::fixtures::Quad {
                image: Some(WHITE),
                tint: Some([255, 0, 0, 255]),
            },
            gltf::fixtures::Quad {
                image: Some(WHITE),
                tint: None,
            },
        ]);
        let seen = palette(&framed(&loaded(&raw)));
        assert_eq!(seen.len(), 2, "{seen:?}");
        assert!(
            seen.iter().any(|p| channels(*p) == [true, true, true]),
            "the untinted quad was reddened by its neighbour: {seen:?}"
        );
        assert!(
            seen.iter().any(|p| channels(*p) == [true, false, false]),
            "the tinted quad was not reddened: {seen:?}"
        );
    }

    /// A primitive with no material draws flat beside painted ones, rather than
    /// borrowing the first image at UV (0, 0) — which is what the old path did
    /// to 24 of `e_lui_robo`'s 92 primitives.
    #[test]
    fn an_unpainted_primitive_draws_flat_beside_painted_ones() {
        let raw = painted_quads(&[Some(RED), None, Some(BLUE)]);
        let seen = palette(&framed(&loaded(&raw)));
        assert_eq!(seen.len(), 3, "{seen:?}");
        assert!(
            seen.iter()
                .any(|pixel| channels(*pixel) == [true, true, true]),
            "no quad was flat-shaded: {seen:?}"
        );
    }

    /// ⚠️ **The regression guard for the single-material majority.** 183 of 864
    /// real models reach exactly one image, and per-primitive binding must not
    /// cost them it: both primitives here name material 0 and both must paint.
    #[test]
    fn a_model_with_one_material_still_paints_every_primitive_with_it() {
        let raw = painted_quads(&[Some(RED), Some(GREEN)]);
        let chunks = gltf::split_chunks(&raw).expect("the fixture is a glb");
        let json = std::str::from_utf8(chunks.json).expect("the JSON chunk is text");
        let shared = json.replace(r#""material":1"#, r#""material":0"#);
        let mesh = loaded(&gltf::fixtures::container(&shared, chunks.bin));

        assert_eq!(mesh.paints().len(), 1);
        let seen = palette(&framed(&mesh));
        assert_eq!(seen.len(), 1, "the quads disagreed on one image: {seen:?}");
        assert_eq!(channels(seen[0]), [true, false, false], "{seen:?}");
    }

    /// ⚠️ 21% of real models tile their texture, so coordinates well outside
    /// [0, 1] are normal. The point sampled here is one a *clamping* sampler
    /// would answer white for and a wrapping one answers blue.
    #[test]
    fn coordinates_outside_the_unit_square_wrap_instead_of_smearing_the_edge() {
        let mesh = loaded(&textured_quad(tiled(3.0), 2, 2, &[RED, GREEN, BLUE, WHITE]));
        let image = render(&mesh, &flat(head_on()), FRAME);
        let sky = Background::DarkGrey.pixel(0, 0, FRAME);

        let pixel = image.pixel(127, 72);
        assert_ne!(pixel, sky, "the tiled quad did not draw");
        assert_eq!(
            channels(pixel),
            [false, false, true],
            "clamping would answer white here, wrapping answers blue: {pixel:?}"
        );
        // And the whole frame is still made of the four texels, not of noise.
        for (x, y) in QUARTERS {
            assert_ne!(image.pixel(x, y), sky);
        }
    }
}
