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

use super::camera::{Basis, Point};
use super::{Background, Rgba, Size};
use crate::data::mesh::Vec3;

/// Light that reaches a face turned fully away from it, so nothing is pure
/// black and a silhouette still shows its shape.
const AMBIENT: f32 = 0.25;

/// Light direction in view space: over the viewer's left shoulder.
const LIGHT: Vec3 = Vec3::new(-0.4, 0.6, -0.7);

/// Untextured surface colour. Models export without materials, so every face
/// differs only by how it is lit.
const SURFACE: Rgba = Rgba::new(214, 208, 196);

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

    fn set(&mut self, x: usize, y: usize, colour: Rgba) {
        let at = (y * self.size.width + x) * 4;
        self.pixels[at] = colour.r;
        self.pixels[at + 1] = colour.g;
        self.pixels[at + 2] = colour.b;
        self.pixels[at + 3] = colour.a;
    }
}

/// Flat shading from the face's own normal — one colour for the whole
/// triangle, which is what makes facets readable on an untextured model.
pub(super) fn shade(basis: &Basis, corners: &[Vec3; 3]) -> Rgba {
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
    SURFACE.shaded(AMBIENT + (1.0 - AMBIENT) * lit)
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

pub(super) fn raster(image: &mut Image, depth: &mut [f32], triangle: &[Point; 3], colour: Rgba) {
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
        let facing = shade(
            &basis,
            &[
                Vec3::new(-1.0, -1.0, 0.0),
                Vec3::new(1.0, -1.0, 0.0),
                Vec3::new(1.0, 1.0, 0.0),
            ],
        );
        // Same triangle wound the other way: two-sided shading must give the
        // same colour, or half a model with mixed winding would go dark.
        let reversed = shade(
            &basis,
            &[
                Vec3::new(1.0, 1.0, 0.0),
                Vec3::new(1.0, -1.0, 0.0),
                Vec3::new(-1.0, -1.0, 0.0),
            ],
        );
        assert_eq!(facing, reversed);

        // Edge-on to the camera, so it catches almost none of the light.
        let edge_on = shade(
            &basis,
            &[
                Vec3::new(0.0, -1.0, -1.0),
                Vec3::new(0.0, -1.0, 1.0),
                Vec3::new(0.0, 1.0, 1.0),
            ],
        );
        assert!(edge_on.r < facing.r, "{edge_on:?} vs {facing:?}");
        assert!(edge_on.r >= SURFACE.shaded(AMBIENT).r, "ambient floor lost");
    }
}
