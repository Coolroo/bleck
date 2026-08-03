//! The depth buffer, the edge test and the shading, on a hand-built frame.

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
