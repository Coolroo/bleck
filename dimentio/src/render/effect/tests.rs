//! ⚠️ Every assertion here is on the pixel buffer. Nobody can look at this
//! window — the machine it is built on cannot capture its own desktop — so a
//! viewport that draws nothing, draws the wrong number of things, or keeps
//! drawing a part that has finished is only visible here.

use super::*;
use crate::data::effects::Part;
use crate::data::texture::{png, Texel};
use crate::render::fixtures::{differing, FRAME};
use crate::render::{scene, Background, Image, Piece, Size, View};

/// An effect with one part per duration given.
fn effect(durations: &[f32]) -> Entry {
    Entry {
        name: "probe".into(),
        index: 0,
        seconds: durations.iter().copied().fold(0.0, f32::max),
        parts: durations
            .iter()
            .enumerate()
            .map(|(index, &seconds)| Part {
                name: format!("P{index}"),
                composed: format!("probeP{index}"),
                index,
                frames: (seconds * 60.0) as u32 + 1,
                seconds,
                // These fixtures test the layout and the timeline, so the
                // art arrives through `Art` rather than through the parts.
                draws: Vec::new(),
            })
            .collect(),
    }
}

pub(super) fn shot(entry: &Entry, time: f32, art: Option<Art<'_>>) -> Image {
    let view = View {
        camera: Camera::fit(bounds(entry, art)),
        background: Background::DarkGrey,
    };
    let drawn = quads(entry, time, &view.camera, art);
    let pieces: Vec<Piece<'_>> = drawn
        .iter()
        .map(|quad| Piece {
            mesh: &quad.mesh,
            flat: quad.colour,
        })
        .collect();
    scene(&pieces, &view, FRAME)
}

fn sky(size: Size) -> Rgba {
    Background::DarkGrey.pixel(0, 0, size)
}

pub(super) fn covered(image: &Image) -> usize {
    let background = sky(image.size());
    (0..image.size().height)
        .flat_map(|y| (0..image.size().width).map(move |x| (x, y)))
        .filter(|&(x, y)| image.pixel(x, y) != background)
        .count()
}

/// The distinct colours that are not the background. Each quad is one flat
/// shade, so this counts the quads that actually reached the frame.
pub(super) fn shades(image: &Image) -> Vec<Rgba> {
    let background = sky(image.size());
    let mut seen: Vec<Rgba> = Vec::new();
    for y in 0..image.size().height {
        for x in 0..image.size().width {
            let pixel = image.pixel(x, y);
            if pixel != background && !seen.contains(&pixel) {
                seen.push(pixel);
            }
        }
    }
    seen
}

#[test]
fn an_effect_with_parts_draws_something_other_than_the_background() {
    let image = shot(&effect(&[1.0]), 0.0, None);
    assert!(covered(&image) > 500, "only {} pixels", covered(&image));
}

/// ⚠️ The instrument check for every "it stopped drawing" claim below: the
/// same effect at a time inside its duration must draw, or an empty frame
/// would prove nothing at all.
#[test]
fn a_time_past_every_duration_draws_only_the_background() {
    let entry = effect(&[1.0, 0.5]);
    assert!(
        covered(&shot(&entry, 0.5, None)) > 0,
        "the control drew nothing"
    );
    assert_eq!(
        covered(&shot(&entry, 1.5, None)),
        0,
        "a finished effect drew"
    );
    assert_eq!(
        covered(&shot(&entry, 1.0001, None)),
        0,
        "one frame past the end"
    );
}

#[test]
fn a_part_stops_being_drawn_once_its_duration_passes() {
    let entry = effect(&[2.0, 0.5]);
    let short = colour(1).shaded(billboard_light());

    let both = shades(&shot(&entry, 0.5, None));
    assert_eq!(both.len(), 2, "{both:?}");
    assert!(both.contains(&short), "the short part never drew: {both:?}");

    let after = shades(&shot(&entry, 0.6, None));
    assert_eq!(after.len(), 1, "{after:?}");
    assert!(!after.contains(&short), "the finished part is still drawn");
}

#[test]
fn two_times_produce_different_frames() {
    let entry = effect(&[2.0, 0.5]);
    let moved = differing(&shot(&entry, 0.4, None), &shot(&entry, 1.4, None));
    assert!(
        moved > 500,
        "only {moved} pixels differ between the two times"
    );
}

#[test]
fn an_effect_with_no_parts_draws_the_background_rather_than_panicking() {
    let entry = effect(&[]);
    assert!(entry.parts.is_empty());
    assert_eq!(covered(&shot(&entry, 0.0, None)), 0);
    assert_eq!(covered(&shot(&entry, 4.0, None)), 0);
}

/// Five effects in the real export last a single frame, so this is the
/// common case rather than an edge one: the part is active only at 0.
#[test]
fn a_zero_length_effect_draws_at_its_only_frame_and_nowhere_else() {
    let entry = effect(&[0.0]);
    assert_eq!(entry.seconds, 0.0);
    assert!(covered(&shot(&entry, 0.0, None)) > 500);
    assert_eq!(covered(&shot(&entry, 0.001, None)), 0);
}

/// The light a quad square to the camera catches — the same for every quad,
/// which is what makes `shades` a count of them.
///
/// ⚠️ Taken from the shading code rather than written down. A number here
/// would be a second copy of the lighting rule, and it would drift from the
/// first one silently: the tests below compare exact pixel values.
fn billboard_light() -> f32 {
    let basis = Basis::of(&Camera::fit(bounds(&effect(&[1.0]), None)));
    let mesh = quad(&basis, Vec3::ZERO, HALF, None, Blend::Alpha);
    let corners = mesh.positions();
    crate::render::raster::lighting(&basis, &[corners[0], corners[1], corners[2]])
}

/// ⚠️ `lit` is what a caller with no screen searches a frame for, so it has
/// to agree with the shade the rasteriser actually lays down. This checks it
/// against `billboard_light`, which derives the factor a second and
/// independent way — and against the pixels, which are the real authority.
#[test]
fn lit_reports_the_shade_a_part_is_really_drawn_in() {
    let entry = effect(&[1.0, 1.0]);
    let camera = Camera::fit(bounds(&entry, None));
    let seen = shades(&shot(&entry, 0.5, None));
    for part in 0..2 {
        assert_eq!(lit(&camera, part), colour(part).shaded(billboard_light()));
        assert!(
            seen.contains(&lit(&camera, part)),
            "part {part} is drawn as {:?}, which is not in {seen:?}",
            lit(&camera, part)
        );
    }
    assert_ne!(lit(&camera, 0), colour(0), "the light was never applied");
}

#[test]
fn every_quad_faces_the_camera_and_so_takes_the_same_light() {
    let entry = effect(&[1.0, 1.0, 1.0, 1.0]);
    let seen = shades(&shot(&entry, 0.5, None));
    assert_eq!(seen.len(), 4, "{seen:?}");
    for part in 0..4 {
        assert!(
            seen.contains(&colour(part).shaded(billboard_light())),
            "part {part} is not in {seen:?}"
        );
    }
}

/// An image reaching one part and not another. ⚠️ The slice is indexed by
/// part, so a `None` in slot 0 must leave part 0 flat rather than shifting
/// part 1's picture onto it.
#[test]
fn a_bound_image_changes_the_pixels_of_its_own_part_only() {
    let entry = effect(&[1.0, 1.0]);
    let cyan = Texel {
        r: 0,
        g: 220,
        b: 220,
        a: 255,
    };
    let image = Texture::decode(&png(1, 1, &[cyan])).expect("a 1x1 png");
    let images = [vec![None], vec![Some(image)]];

    let plain = shot(&entry, 0.5, None);
    let painted = shot(
        &entry,
        0.5,
        Some(Art {
            images: &images,
            meshes: &[],
            nodes: &[],
            curves: &[],
        }),
    );
    assert!(
        differing(&plain, &painted) > 200,
        "the chosen image changed nothing"
    );

    // The flat colour part 1 would have taken is gone, and the texel's is
    // there instead — so the image landed on the part that was chosen.
    let after = shades(&painted);
    assert!(
        !after.contains(&colour(1).shaded(billboard_light())),
        "part 1 kept its flat colour: {after:?}"
    );
    assert!(
        after.contains(&colour(0).shaded(billboard_light())),
        "part 0 lost its flat colour: {after:?}"
    );
    assert!(
        after.contains(&Rgba::new(cyan.r, cyan.g, cyan.b).shaded(billboard_light())),
        "the texel never reached the frame: {after:?}"
    );
}

/// ⛔ The layout must not move on its own. A quad's position is a display
/// choice, and a viewer that shuffled parts between frames would look like
/// it was animating something the data does not say.
#[test]
fn the_layout_is_the_same_every_time_it_is_asked_for() {
    let entry = effect(&[1.0, 1.0, 1.0]);
    assert_eq!(
        differing(&shot(&entry, 0.5, None), &shot(&entry, 0.5, None)),
        0
    );
    for part in 0..3 {
        assert_eq!(placement(&entry, part, 1.0), placement(&entry, part, 1.0));
    }
}

/// ⛔ The rows this used to read are deleted (D270), so the fallback is now
/// the ring alone. What still has to hold is the property those tests were
/// really about: **every part gets a distinct place**, or two stack and one
/// is invisible.
#[test]
fn the_fallback_layout_gives_every_part_a_place_of_its_own() {
    let entry = effect(&[1.0, 1.0, 1.0]);
    let places: Vec<Vec3> = (0..3).map(|part| placement(&entry, part, 1.0)).collect();
    for (index, place) in places.iter().enumerate() {
        assert!(place.length() > 0.5, "part {index} landed at the origin");
    }
    assert_ne!(places[0], places[1]);
    assert_ne!(places[1], places[2]);
    assert_eq!(shades(&shot(&entry, 0.5, None)).len(), 3);
}

#[test]
fn a_zero_sized_frame_is_empty_rather_than_a_panic() {
    let entry = effect(&[1.0]);
    let view = View {
        camera: Camera::fit(bounds(&entry, None)),
        background: Background::DarkGrey,
    };
    let drawn = quads(&entry, 0.0, &view.camera, None);
    let pieces: Vec<Piece<'_>> = drawn
        .iter()
        .map(|quad| Piece {
            mesh: &quad.mesh,
            flat: quad.colour,
        })
        .collect();
    assert!(scene(&pieces, &view, Size::new(0, 0)).as_rgba().is_empty());
}
