//! An effect's running parts, as geometry the rasteriser can draw.
//!
//! One camera-facing quad per part that is running at the scrubber's position,
//! laid out from the effect's transform rows. The quads go back to the caller
//! as meshes so they can be handed to `render::scene` — there is one rasteriser
//! in this program and this module does not contain a second one.
//!
//! ⛔ **No part is paired with an image here.** Which image a part draws is not
//! decoded — six candidate fields have been refuted and the real reference is a
//! second record array the export does not carry (`docs/decision-log.md` D210,
//! D218). A quad is therefore drawn as a flat colour unless the window passes a
//! `Manual` preview, which is an image a user picked for a part they picked.

use super::camera::Basis;
use super::{Camera, Rgba};
use crate::data::effects::Entry;
use crate::data::mesh::{Bounds, Face, Mesh, Parts, Uv, Vec3};
use crate::data::texture::Texture;

/// Half the edge of a part's quad, in the units the layout below uses.
const HALF: f32 = 0.30;

/// How far from the origin the first part sits.
const RING: f32 = 1.0;

/// How much further out each successive part sits. Without it two parts whose
/// rows point the same way land in the same place and fight for the depth
/// buffer, which reads on screen as one quad flickering rather than two.
const SPREAD: f32 = 0.22;

/// The colours parts are drawn in, taken by part index and repeated. Distinct
/// hues rather than a ramp, so which quad belongs to which row of the part
/// table can be read off the frame — including by a test counting colours.
const PALETTE: [Rgba; 6] = [
    Rgba::new(226, 96, 84),
    Rgba::new(232, 178, 70),
    Rgba::new(120, 200, 120),
    Rgba::new(96, 176, 232),
    Rgba::new(170, 130, 226),
    Rgba::new(226, 132, 186),
];

/// A picture the user asked to see on one part.
///
/// ⛔ This is not a decoded pairing and must never become one. Both the part
/// and the image are chosen in the window, and the panel that offers them says
/// so on screen. Deriving either end from a field a part carries would produce
/// something that looks exactly like a measured fact and is not one.
#[derive(Debug, Clone, Copy)]
pub struct Manual<'a> {
    pub part: usize,
    pub image: &'a Texture,
}

/// One part of an effect, drawn.
pub struct Quad {
    pub mesh: Mesh,
    /// The flat colour the quad takes when it carries no image.
    pub colour: Rgba,
    /// Which of the effect's parts this is, as an index into `Entry::parts`.
    pub part: usize,
}

/// The colour a part is drawn in, so the table beside the viewport can mark a
/// row with the same one.
pub fn colour(part: usize) -> Rgba {
    PALETTE[part % PALETTE.len()]
}

/// The parts running at `time`, as camera-facing quads.
///
/// Which parts those are comes from `Entry::active_at`, the same rule that
/// marks a row in the part table: a part runs from 0 to and including its own
/// duration. Nothing here re-decides it.
pub fn quads(entry: &Entry, time: f32, camera: &Camera, manual: Option<Manual<'_>>) -> Vec<Quad> {
    let basis = Basis::of(camera);
    entry
        .active_at(time)
        .into_iter()
        .map(|part| Quad {
            // Cloned because a mesh owns its texture; only the one part the
            // user chose ever pays for it.
            mesh: quad(
                &basis,
                placement(entry, part),
                manual
                    .filter(|manual| manual.part == part)
                    .map(|manual| manual.image.clone()),
            ),
            colour: colour(part),
            part,
        })
        .collect()
}

/// The box the whole layout occupies, running or not.
///
/// Every part counts, not just the ones active now, so a camera fitted to this
/// stays put as parts start and stop instead of jumping each time the timeline
/// crosses a duration.
pub fn bounds(entry: &Entry) -> Bounds {
    let mut span = Bounds {
        min: Vec3::new(-HALF, -HALF, -HALF),
        max: Vec3::new(HALF, HALF, HALF),
    };
    for part in 0..entry.parts.len() {
        let at = placement(entry, part);
        span.min = Vec3::new(
            span.min.x.min(at.x - HALF),
            span.min.y.min(at.y - HALF),
            span.min.z.min(at.z - HALF),
        );
        span.max = Vec3::new(
            span.max.x.max(at.x + HALF),
            span.max.y.max(at.y + HALF),
            span.max.z.max(at.z + HALF),
        );
    }
    span
}

/// Where a part sits in the layout.
///
/// ⛔ **The transform rows are not a decoded scene graph.** A row is four
/// floats; most are unit length, and `chaos`'s hold an exact 72° rotation. The
/// row at the part's own position is read as a direction and the part placed
/// along it, which puts `chaos`'s parts on the five-fold ring measured in-game.
/// A part with no row of its own, or whose row has no direction, falls back to
/// an even ring by part index.
///
/// Both rules are deterministic and both are a layout, not a claim about what
/// the file means. Nothing downstream may treat a quad's position as measured.
fn placement(entry: &Entry, part: usize) -> Vec3 {
    let heading = entry
        .rows
        .get(part)
        .and_then(|row| direction(&row.values))
        .unwrap_or_else(|| ring(part, entry.parts.len()));
    heading.scaled(RING + SPREAD * part as f32)
}

/// The first three of a row's floats as a unit vector, or `None` when the row
/// is short, is not finite, or has no length to point along.
fn direction(values: &[f32]) -> Option<Vec3> {
    let point = Vec3::new(*values.first()?, *values.get(1)?, *values.get(2)?);
    if !point.x.is_finite() || !point.y.is_finite() || !point.z.is_finite() {
        return None;
    }
    let unit = point.normalised();
    (unit.length() > 0.0).then_some(unit)
}

/// An even ring in the XY plane, by part index.
fn ring(part: usize, parts: usize) -> Vec3 {
    let (sin, cos) = (std::f32::consts::TAU * part as f32 / parts.max(1) as f32).sin_cos();
    Vec3::new(cos, sin, 0.0)
}

/// A quad centred on `at` and square to the camera.
///
/// ⚠️ Built from the camera's own right and up vectors, so it must be rebuilt
/// when the camera moves. A quad fixed in world space turns edge-on as the view
/// orbits and disappears, which reads as a part that stopped running.
fn quad(basis: &Basis, at: Vec3, image: Option<Texture>) -> Mesh {
    let right = basis.right.scaled(HALF);
    let up = basis.up.scaled(HALF);
    // A bank image is cut-out art with a real alpha channel; without the mask
    // its transparent surround is drawn as a black square around the sprite.
    let masked = image.is_some();
    Parts {
        positions: vec![
            at - right + up,
            at + right + up,
            at + right - up,
            at - right - up,
        ],
        faces: vec![Face { a: 0, b: 1, c: 2 }, Face { a: 0, b: 2, c: 3 }],
        // Top-left first, matching the corner order above: the sampler puts
        // (0, 0) at the image's top-left, so a different order flips the art.
        uvs: Some(vec![
            Uv::new(0.0, 0.0),
            Uv::new(1.0, 0.0),
            Uv::new(1.0, 1.0),
            Uv::new(0.0, 1.0),
        ]),
        texture: image,
        masked,
        // A billboard is built fresh from the camera each frame; there is
        // nothing to morph and nothing that would outlive one.
        animation: None,
    }
    .into_mesh()
}

/// ⚠️ Every assertion here is on the pixel buffer. Nobody can look at this
/// window — the machine it is built on cannot capture its own desktop — so a
/// viewport that draws nothing, draws the wrong number of things, or keeps
/// drawing a part that has finished is only visible here.
#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::effects::{Part, Row};
    use crate::data::texture::{png, Texel};
    use crate::render::fixtures::{differing, FRAME};
    use crate::render::{scene, Background, Image, Piece, Size, View};

    /// Rows pointing along four different axes, so no two quads of a test
    /// effect can land on top of each other and hide the thing being measured.
    const AXES: [[f32; 4]; 4] = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [-1.0, 0.0, 0.0, 0.0],
    ];

    /// An effect with one part per duration given, each with a row of its own.
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
                })
                .collect(),
            rows: (0..durations.len())
                .map(|index| Row {
                    index,
                    values: AXES[index % AXES.len()].to_vec(),
                })
                .collect(),
        }
    }

    pub(super) fn shot(entry: &Entry, time: f32, manual: Option<Manual<'_>>) -> Image {
        let view = View {
            camera: Camera::fit(bounds(entry)),
            background: Background::DarkGrey,
        };
        let drawn = quads(entry, time, &view.camera, manual);
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
        let basis = Basis::of(&Camera::fit(bounds(&effect(&[1.0]))));
        let mesh = quad(&basis, Vec3::ZERO, None);
        let corners = mesh.positions();
        crate::render::raster::lighting(&basis, &[corners[0], corners[1], corners[2]])
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

    /// The manual preview, which is the only way an image ever reaches a part.
    #[test]
    fn a_manually_chosen_image_changes_the_pixels() {
        let entry = effect(&[1.0, 1.0]);
        let cyan = Texel {
            r: 0,
            g: 220,
            b: 220,
            a: 255,
        };
        let image = Texture::decode(&png(1, 1, &[cyan])).expect("a 1x1 png");

        let plain = shot(&entry, 0.5, None);
        let painted = shot(
            &entry,
            0.5,
            Some(Manual {
                part: 1,
                image: &image,
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
            assert_eq!(placement(&entry, part), placement(&entry, part));
        }
    }

    /// A row of four zeroes points nowhere, and normalising it gives zero — so
    /// every part with one would stack at the origin. The ring is the fallback.
    #[test]
    fn a_part_whose_row_has_no_direction_falls_back_to_the_ring() {
        let mut entry = effect(&[1.0, 1.0, 1.0]);
        for row in &mut entry.rows {
            row.values = vec![0.0, 0.0, 0.0, 0.0];
        }
        let places: Vec<Vec3> = (0..3).map(|part| placement(&entry, part)).collect();
        for (index, place) in places.iter().enumerate() {
            assert!(place.length() > 0.5, "part {index} landed at the origin");
        }
        assert_ne!(places[0], places[1]);
        assert_eq!(shades(&shot(&entry, 0.5, None)).len(), 3);
    }

    /// An export with no rows at all, and one whose rows are too short to read
    /// as a direction: both fall back rather than dropping the part.
    #[test]
    fn an_effect_with_no_usable_rows_still_draws_every_part() {
        let mut entry = effect(&[1.0, 1.0]);
        entry.rows.clear();
        assert_eq!(shades(&shot(&entry, 0.5, None)).len(), 2);

        let mut short = effect(&[1.0, 1.0]);
        for row in &mut short.rows {
            row.values = vec![1.0];
        }
        assert_eq!(shades(&shot(&short, 0.5, None)).len(), 2);
    }

    #[test]
    fn a_zero_sized_frame_is_empty_rather_than_a_panic() {
        let entry = effect(&[1.0]);
        let view = View {
            camera: Camera::fit(bounds(&entry)),
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
}

/// The real export, when one happens to be on this machine.
///
/// ⚠️ `work/` is git-ignored, so these skip rather than fail on a fresh clone
/// or in CI. They exist because every fixture above is written by this file's
/// own tests: an effect built here cannot catch a real one whose rows are all
/// zero, whose parts outnumber its rows, or which carries no parts at all.
#[cfg(test)]
mod real_export_tests {
    use super::tests::{covered, shades, shot};
    use super::*;
    use crate::data::effects::Library;
    use std::path::{Path, PathBuf};

    fn export() -> Option<PathBuf> {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()?
            .join("work")
            .join("export");
        root.join("effects.json").is_file().then_some(root)
    }

    #[test]
    fn every_real_effect_draws_at_its_first_frame_and_stops_after_its_last() {
        let Some(root) = export() else {
            eprintln!("no work/export on this machine; skipped");
            return;
        };
        let library = Library::load(&root);
        assert!(!library.entries().is_empty(), "the manifest named nothing");

        let mut drawn = 0;
        for entry in library.entries() {
            if entry.parts.is_empty() {
                assert_eq!(covered(&shot(entry, 0.0, None)), 0, "{}", entry.name);
                continue;
            }
            assert!(
                covered(&shot(entry, 0.0, None)) > 100,
                "{} drew nothing at its first frame",
                entry.name
            );
            assert_eq!(
                covered(&shot(entry, entry.seconds + 0.5, None)),
                0,
                "{} was still drawing past its last frame",
                entry.name
            );
            drawn += 1;
        }
        assert!(drawn > 100, "only {drawn} effects drew");
    }

    /// `chaos` is the effect the five-fold ring was measured on, and two of its
    /// four rows are the same direction — so it is also the case the outward
    /// spread exists for. Four parts, four separate quads.
    #[test]
    fn chaos_draws_four_separate_parts() {
        let Some(root) = export() else {
            eprintln!("no work/export on this machine; skipped");
            return;
        };
        let library = Library::load(&root);
        let entry = library
            .entries()
            .iter()
            .find(|entry| entry.name == "chaos")
            .expect("chaos is in every export");
        assert_eq!(entry.parts.len(), 4);

        let places: Vec<Vec3> = (0..4).map(|part| placement(entry, part)).collect();
        for (one, place) in places.iter().enumerate() {
            for (two, other) in places.iter().enumerate().skip(one + 1) {
                assert!(
                    (*place - *other).length() > 2.0 * HALF,
                    "parts {one} and {two} overlap at {place:?} and {other:?}"
                );
            }
        }
        assert_eq!(shades(&shot(entry, 0.0, None)).len(), 4);
    }
}
