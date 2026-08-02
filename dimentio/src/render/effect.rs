//! An effect's running parts, as geometry the rasteriser can draw.
//!
//! One piece per draw issued by a part running at the scrubber's position. The
//! pieces go back to the caller as meshes so they can be handed to
//! `render::scene` — there is one rasteriser in this program and this module
//! does not contain a second one.
//!
//! ✅ **A part's image is decoded** (D258) and so is **its geometry** (D263):
//! both arrive already resolved, as `Art`. Nothing in this module derives
//! either; `bleck` owns the format and writes them into the export, which is
//! the same division every other format keeps.
//!
//! ⚠️ **A camera-facing quad is now the fallback, not the rendering.** An
//! export predating D263 carries no `meshes`, and a draw that names one the
//! manifest does not hold falls back to a billboard so the part still appears.
//! ⛔ Do not read a billboard as an effect's shape — it means the geometry was
//! missing, which the caller's report says out loud.
//!
//! ⛔ **The placement between parts is still a display choice.** Each draw's
//! *shape* is measured; where one part sits relative to another is not, because
//! section 9's node transforms are read but not applied. The layout below is an
//! **exploded view** — deliberately separated so the parts can be told apart —
//! and nothing downstream may read a piece's position as where the game puts it.

use super::camera::Basis;
use super::{Camera, Rgba};
use crate::data::effects::{Entry, Mesh as Geometry};
use crate::data::mesh::{Bounds, Face, Mesh, Paint, Parts, Shape, Uv, Vec3};
use crate::data::texture::{Sampling, Texture};

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

/// What each draw paints with, and the geometry it paints.
///
/// ✅ Since D258 the image is the **decoded** pairing — five sections past the
/// part record — and since D263 the geometry is decoded too. `bleck` resolves
/// both into the export; nothing here re-derives either.
///
/// ⚠️ **`images` is indexed by part, then by draw within that part**, so a short
/// slice leaves the draws past its end unpainted rather than shifting the
/// artwork along by one. A slot of `None` is a draw that paints no image, which
/// the file's untextured materials genuinely do.
#[derive(Debug, Clone, Copy)]
pub struct Art<'a> {
    pub images: &'a [Vec<Option<Texture>>],
    /// The manifest's shared display-list table, indexed by `Draw::mesh`.
    /// Empty for an export predating the geometry, which falls back.
    pub meshes: &'a [Geometry],
}

impl<'a> Art<'a> {
    fn of(&self, part: usize, draw: usize) -> Option<Texture> {
        self.images.get(part)?.get(draw).cloned().flatten()
    }

    /// The geometry a draw names, or `None` when the manifest does not hold it
    /// or holds it malformed.
    ///
    /// ⚠️ Soundness is checked here rather than trusted: a manifest is a file
    /// on disk, and a stray index would panic the rasteriser.
    ///
    /// ⚠️ The result borrows from the **table**, not from `self` — `Art` is
    /// `Copy`, so a copy made inside a closure would otherwise own the
    /// reference and die at the end of it.
    fn geometry(&self, at: usize) -> Option<&'a Geometry> {
        self.meshes
            .get(at)
            .filter(|mesh| mesh.is_sound() && mesh.faces() > 0)
    }
}

/// One draw of an effect, ready for the rasteriser.
pub struct Quad {
    pub mesh: Mesh,
    /// The flat colour the piece takes when it carries no image.
    pub colour: Rgba,
    /// Which of the effect's parts this is, as an index into `Entry::parts`.
    pub part: usize,
    /// ⚠️ **True when this is a stand-in billboard rather than the effect's own
    /// shape** — the draw named no mesh the manifest holds. A caller reporting
    /// what it drew has to be able to say so, because a billboard looks like a
    /// deliberate sprite and is not.
    pub stood_in: bool,
}

/// The colour a part is drawn in, so the table beside the viewport can mark a
/// row with the same one.
pub fn colour(part: usize) -> Rgba {
    PALETTE[part % PALETTE.len()]
}

/// The colour part `part` actually lands in the frame as, once the billboard
/// lighting has been applied — which is what a caller counting parts in a
/// rendered image has to look for. `colour` alone never appears in a frame.
///
/// ⚠️ **Derived by lighting a real quad, not by writing the factor down.** A
/// constant here would be a second copy of the shading rule and would drift
/// from the first one silently, leaving a caller searching a frame for a shade
/// nothing draws in. Every quad faces the camera, so one of them answers for
/// all of them.
pub fn lit(camera: &Camera, part: usize) -> Rgba {
    let basis = Basis::of(camera);
    let mesh = quad(&basis, Vec3::ZERO, HALF, None);
    let corners = mesh.positions();
    let intensity = super::raster::lighting(&basis, &[corners[0], corners[1], corners[2]]);
    colour(part).shaded(intensity)
}

/// Every draw issued by a part running at `time`.
///
/// Which parts those are comes from `Entry::active_at`, the same rule that
/// marks a row in the part table: a part runs from 0 to and including its own
/// duration. Nothing here re-decides it.
///
/// ⚠️ **A part with no draws still produces one piece.** An export predating
/// the decoding carries none, and dropping those parts would turn a stale
/// export into an effect that renders as nothing at all.
pub fn quads(entry: &Entry, time: f32, camera: &Camera, art: Option<Art<'_>>) -> Vec<Quad> {
    let basis = Basis::of(camera);
    let scale = spread(entry, art);
    let mut built = Vec::new();
    for part in entry.active_at(time) {
        let at = placement(entry, part, scale);
        let count = entry.parts.get(part).map_or(0, |p| p.draws.len());
        for draw in 0..count.max(1) {
            // Cloned because a mesh owns its texture; only the parts actually
            // running at this instant ever pay for it.
            let image = art.and_then(|art| art.of(part, draw));
            let shape = art
                .zip(entry.parts.get(part).and_then(|p| p.draws.get(draw)))
                .and_then(|(art, draw)| art.geometry(draw.mesh));
            built.push(Quad {
                mesh: match shape {
                    Some(geometry) => real(geometry, at, image),
                    None => quad(&basis, at, scale * HALF, image),
                },
                colour: colour(part),
                part,
                stood_in: shape.is_none(),
            });
        }
    }
    built
}

/// The box the whole layout occupies, running or not.
///
/// Every part counts, not just the ones active now, so a camera fitted to this
/// stays put as parts start and stop instead of jumping each time the timeline
/// crosses a duration.
pub fn bounds(entry: &Entry, art: Option<Art<'_>>) -> Bounds {
    let scale = spread(entry, art);
    let mut span: Option<Bounds> = None;
    for part in 0..entry.parts.len().max(1) {
        let at = placement(entry, part, scale);
        let draws = entry
            .parts
            .get(part)
            .map(|p| p.draws.as_slice())
            .unwrap_or_default();
        let mut here: Option<Bounds> = None;
        for geometry in draws
            .iter()
            .filter_map(|draw| art.and_then(|art| art.geometry(draw.mesh)))
        {
            here = Some(union(here, box_of(geometry, at)));
        }
        // No geometry means a stand-in billboard, which is a cube of side
        // `2 * scale * HALF` about its placement.
        let corner = Vec3::new(scale * HALF, scale * HALF, scale * HALF);
        let here = here.unwrap_or(Bounds {
            min: at - corner,
            max: at + corner,
        });
        span = Some(union(span, here));
    }
    span.unwrap_or(Bounds {
        min: Vec3::new(-HALF, -HALF, -HALF),
        max: Vec3::new(HALF, HALF, HALF),
    })
}

/// ⚠️ **Per axis, not a radius.** A single reach used for all three collapses
/// to a cube, which hides exactly the anisotropy a caller needs to see: one
/// display list of the file's 360 is 640 units wide and 58,642 deep, and as a
/// cube it reports as perfectly ordinary (D264).
fn box_of(geometry: &Geometry, at: Vec3) -> Bounds {
    let mut span: Option<Bounds> = None;
    for p in geometry.positions.chunks_exact(3) {
        let point = at + Vec3::new(p[0] as f32, p[1] as f32, p[2] as f32);
        span = Some(union(
            span,
            Bounds {
                min: point,
                max: point,
            },
        ));
    }
    span.unwrap_or(Bounds {
        min: at,
        max: at,
    })
}

fn union(so_far: Option<Bounds>, here: Bounds) -> Bounds {
    match so_far {
        None => here,
        Some(box_) => Bounds {
            min: Vec3::new(
                box_.min.x.min(here.min.x),
                box_.min.y.min(here.min.y),
                box_.min.z.min(here.min.z),
            ),
            max: Vec3::new(
                box_.max.x.max(here.max.x),
                box_.max.y.max(here.max.y),
                box_.max.z.max(here.max.z),
            ),
        },
    }
}

/// How far a display list reaches **in the plane the layout separates parts
/// in**, which is not the same as how far it reaches overall.
///
/// ⚠️ Measured in XY on purpose. One display list of the file's 360 is 640
/// units wide and 58,642 deep (D264); scaling the exploded layout by its full
/// 3D reach would fling every part of that effect a hundred widths apart and
/// leave a fitted camera framing empty space.
fn flat_extent(geometry: &Geometry) -> f32 {
    geometry
        .positions
        .chunks_exact(3)
        .map(|p| {
            let (x, y) = (p[0] as f32, p[1] as f32);
            (x * x + y * y).sqrt()
        })
        .fold(0.0, f32::max)
        .max(1.0)
}

/// The unit the exploded layout is measured in.
///
/// ⚠️ **Derived from the geometry, never fixed.** Effect positions are the
/// file's own `s16` units — Dimentio's star spans ±320 — while the fallback
/// billboard is built at a fraction of one. A constant offset would either
/// stack every real mesh on the origin or fling every billboard out of frame.
fn spread(entry: &Entry, art: Option<Art<'_>>) -> f32 {
    let biggest = entry
        .parts
        .iter()
        .flat_map(|part| part.draws.iter())
        .filter_map(|draw| art.and_then(|art| art.geometry(draw.mesh)))
        .map(flat_extent)
        .fold(0.0_f32, f32::max);
    if biggest > 0.0 {
        biggest
    } else {
        1.0
    }
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
fn placement(entry: &Entry, part: usize, scale: f32) -> Vec3 {
    // ⚠️ **Nothing to explode when there is only one part.** Offsetting a lone
    // part pushes it off-centre for no gain, and a camera fitted to the result
    // frames mostly empty space — which is how `item_delete` came to render as
    // nothing at all.
    if entry.parts.len() < 2 {
        return Vec3::ZERO;
    }
    let heading = entry
        .rows
        .get(part)
        .and_then(|row| direction(&row.values))
        .unwrap_or_else(|| ring(part, entry.parts.len()));
    heading.scaled(scale * (RING + SPREAD * part as f32))
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

/// A display list, as the rasteriser's own mesh, centred on `at`.
///
/// ✅ **This is the effect's real shape** (D263) — indexed triangles out of the
/// file, in the file's own units. Nothing is scaled or reoriented: the camera
/// fits itself to the bounds, so a guessed conversion here would be a second,
/// invisible scale on top of the one the viewer already applies.
///
/// ⚠️ **Fixed in world space, unlike the billboard below.** Effect geometry is
/// mostly flat, so orbiting to its edge legitimately shows almost nothing —
/// that is the shape, not a part that stopped running.
fn real(geometry: &Geometry, at: Vec3, image: Option<Texture>) -> Mesh {
    let positions: Vec<Vec3> = geometry
        .positions
        .chunks_exact(3)
        .map(|p| at + Vec3::new(p[0] as f32, p[1] as f32, p[2] as f32))
        .collect();
    let faces: Vec<Face> = geometry
        .triangles
        .chunks_exact(3)
        .map(|t| Face {
            a: t[0],
            b: t[1],
            c: t[2],
        })
        .collect();
    let uvs = (geometry.uvs.len() == positions.len() * 2).then(|| {
        geometry
            .uvs
            .chunks_exact(2)
            .map(|c| Uv::new(c[0], c[1]))
            .collect()
    });
    // ✅ Section 15's vertex colours, where the descriptor names them. The game
    // modulates them into the texture, which is what `colours` means here too.
    let colours = (geometry.colours.len() == positions.len() * 4).then(|| {
        geometry
            .colours
            .chunks_exact(4)
            .map(|c| [c[0], c[1], c[2], c[3]])
            .collect()
    });
    let paints: Vec<Paint> = image.map(cutout).into_iter().collect();
    let paint = (!paints.is_empty()).then_some(0);
    Parts {
        shapes: vec![Shape {
            first: 0,
            count: faces.len(),
            visible: true,
            paint,
        }],
        positions,
        faces,
        uvs,
        colours,
        paints,
        // Section 10's curves would animate this; they are not read (D263).
        animation: None,
    }
    .into_mesh()
}

/// How an effect's bank image is sampled: cut-out art with a real alpha
/// channel, so without the mask its transparent surround draws as a black
/// square around the sprite.
fn cutout(texture: Texture) -> Paint {
    Paint {
        texture,
        masked: true,
        cutoff: super::FAINT_CUTOFF,
        sampling: Sampling::default(),
        mask: None,
    }
}

/// A quad of edge `2 * half` centred on `at` and square to the camera.
///
/// ⚠️ **The fallback, not the rendering.** It stands in for a draw whose
/// geometry the manifest does not hold — an export predating D263, or a mesh
/// index it cannot resolve — so that the part still appears rather than
/// vanishing. `Quad::stood_in` marks every one.
///
/// ⚠️ Built from the camera's own right and up vectors, so it must be rebuilt
/// when the camera moves. A quad fixed in world space turns edge-on as the view
/// orbits and disappears, which reads as a part that stopped running.
fn quad(basis: &Basis, at: Vec3, half: f32, image: Option<Texture>) -> Mesh {
    let right = basis.right.scaled(half);
    let up = basis.up.scaled(half);
    let paints: Vec<Paint> = image.map(cutout).into_iter().collect();
    let paint = (!paints.is_empty()).then_some(0);
    Parts {
        positions: vec![
            at - right + up,
            at + right + up,
            at + right - up,
            at - right - up,
        ],
        faces: vec![Face { a: 0, b: 1, c: 2 }, Face { a: 0, b: 2, c: 3 }],
        // One billboard is one shape; there is nothing here to hide separately.
        shapes: vec![Shape {
            first: 0,
            count: 2,
            visible: true,
            paint,
        }],
        // Top-left first, matching the corner order above: the sampler puts
        // (0, 0) at the image's top-left, so a different order flips the art.
        uvs: Some(vec![
            Uv::new(0.0, 0.0),
            Uv::new(1.0, 0.0),
            Uv::new(1.0, 1.0),
            Uv::new(0.0, 1.0),
        ]),
        // An effect part carries no vertex colour: its tint comes from the
        // part record's own fields, not from a model file's slot 5.
        colours: None,
        paints,
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
                    // These fixtures test the layout and the timeline, so the
                    // art arrives through `Art` rather than through the parts.
                    draws: Vec::new(),
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
        let mesh = quad(&basis, Vec3::ZERO, HALF, None);
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

    /// A row of four zeroes points nowhere, and normalising it gives zero — so
    /// every part with one would stack at the origin. The ring is the fallback.
    #[test]
    fn a_part_whose_row_has_no_direction_falls_back_to_the_ring() {
        let mut entry = effect(&[1.0, 1.0, 1.0]);
        for row in &mut entry.rows {
            row.values = vec![0.0, 0.0, 0.0, 0.0];
        }
        let places: Vec<Vec3> = (0..3).map(|part| placement(&entry, part, 1.0)).collect();
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

        let places: Vec<Vec3> = (0..4).map(|part| placement(entry, part, 1.0)).collect();
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
