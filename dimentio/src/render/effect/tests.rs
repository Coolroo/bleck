//! ⚠️ Every assertion here is on the pixel buffer. Nobody can look at this
//! window — the machine it is built on cannot capture its own desktop — so a
//! viewport that draws nothing, draws the wrong number of things, or keeps
//! drawing a part that has finished is only visible here.

use super::*;
use crate::data::effects::Part;
use crate::data::mesh::Modulate;
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
        .pieces
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
    let mesh = quad(
        &basis,
        Vec3::ZERO,
        HALF,
        None,
        Blend::Alpha,
        Modulate::default(),
    );
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

/// One node holding still at a given alpha, with no curve of its own.
fn node(alpha: f32) -> NodeDef {
    NodeDef {
        t: vec![0.0, 0.0, 0.0],
        r: vec![0.0, 0.0, 0.0],
        s: vec![1.0, 1.0, 1.0],
        alpha,
        curves: Vec::new(),
    }
}

/// An effect of one part issuing one draw, so a node chain and a material sit
/// behind something the frame can be searched for.
///
/// ⚠️ The mesh table handed alongside is empty in most of these, so the draw
/// falls back to the billboard — which carries the same image, blend and
/// material register the real geometry does, and is what makes the composition
/// checkable without a display list fixture.
fn one_draw(material: Modulate) -> Entry {
    Entry {
        name: "probe".into(),
        index: 0,
        seconds: 1.0,
        parts: vec![Part {
            name: "A".into(),
            composed: "probeA".into(),
            index: 0,
            frames: 61,
            seconds: 1.0,
            draws: vec![Draw {
                mesh: 0,
                chain: vec![0],
                blend: 0,
                image: 0,
                wrap: 0,
                red: Some(material.red),
                green: Some(material.green),
                blue: Some(material.blue),
                alpha: Some(material.alpha),
            }],
        }],
    }
}

const WHITE: Texel = Texel {
    r: 255,
    g: 255,
    b: 255,
    a: 255,
};

fn white() -> Vec<Vec<Option<Texture>>> {
    vec![vec![Texture::decode(&png(1, 1, &[WHITE])).ok()]]
}

/// ⛔ **The failure this whole thing exists to stop.** A drawing node holding
/// alpha 0 is transparent for as long as it holds it, and painting it lays a
/// solid sprite over the frame — which looks deliberate and gets reported by
/// nobody. The control is the same fixture at 255.
#[test]
fn a_node_holding_zero_alpha_paints_nothing_while_the_same_draw_at_full_alpha_does() {
    let entry = one_draw(Modulate::default());
    let images = white();
    let shown = [node(255.0)];
    let hidden = [node(0.0)];
    let art = |nodes: &[NodeDef]| shot(&entry, 0.0, Some(art_of(&images, nodes)));

    assert!(
        covered(&art(&shown)) > 500,
        "the control drew nothing: {}",
        covered(&art(&shown))
    );
    assert_eq!(covered(&art(&hidden)), 0, "a transparent node was painted");
}

/// ⚠️ **Not issued, rather than issued and blended away.** The pixels alone
/// cannot tell the two apart — a fully faded texel is discarded by the cutoff
/// either way — but the reel counts pieces, so an invisible draw left in the
/// list still reports as a part that painted.
#[test]
fn a_draw_with_nothing_left_of_its_alpha_is_never_issued() {
    let entry = one_draw(Modulate::default());
    let images = white();
    let camera = Camera::fit(bounds(&entry, None));
    let pieces = |nodes: &[NodeDef]| quads(&entry, 0.0, &camera, Some(art_of(&images, nodes)));

    let shown = pieces(&[node(255.0)]);
    assert_eq!(shown.pieces.len(), 1, "the control issued nothing");
    assert_eq!(shown.faded, 0, "the control counted a fade");
    let hidden = pieces(&[node(0.0)]);
    assert_eq!(hidden.pieces.len(), 0, "a transparent draw was issued");
    assert_eq!(hidden.faded, 1, "the fade was never counted, so the report                 cannot tell it from a draw that was never declared");
    // The material's own alpha closes the same door, on its own.
    let faded = one_draw(Modulate {
        alpha: 0,
        ..Default::default()
    });
    assert_eq!(
        quads(&faded, 0.0, &camera, Some(art_of(&images, &[node(255.0)])))
            .pieces
            .len(),
        0,
        "a material with no alpha was drawn"
    );
}

/// A node halfway through a fade must land halfway, not at either end.
#[test]
fn an_intermediate_node_alpha_composites_instead_of_snapping_to_solid() {
    let entry = one_draw(Modulate::default());
    let images = white();
    let at = |alpha: f32| shot(&entry, 0.0, Some(art_of(&images, &[node(alpha)])));

    let solid = shades(&at(255.0));
    let half = shades(&at(128.0));
    assert_eq!(solid.len(), 1, "{solid:?}");
    assert_eq!(
        half.len(),
        1,
        "the half-faded draw left the frame: {half:?}"
    );
    assert_ne!(half[0], solid[0], "128 was drawn exactly as 255");
    // Blended towards the backdrop, which is darker than the white sprite.
    assert!(half[0].r < solid[0].r, "{:?} vs {:?}", half[0], solid[0]);
    assert!(
        half[0] != sky(FRAME),
        "the half-faded draw composited away to nothing"
    );
}

/// ✅ 291 of the file's 524 materials are not white (D278). A viewer that drops
/// the register paints a coloured glow as a white sprite.
#[test]
fn a_tinted_material_changes_the_colour_that_reaches_the_frame() {
    let images = white();
    let nodes = [node(255.0)];
    let plain = shades(&shot(
        &one_draw(Modulate::default()),
        0.0,
        Some(art_of(&images, &nodes)),
    ));
    let red = shades(&shot(
        &one_draw(Modulate {
            red: 255,
            green: 0,
            blue: 0,
            alpha: 255,
        }),
        0.0,
        Some(art_of(&images, &nodes)),
    ));
    assert_eq!(plain.len(), 1, "{plain:?}");
    assert_eq!(red.len(), 1, "{red:?}");
    assert!(plain[0].g > 0 && plain[0].b > 0, "{:?}", plain[0]);
    assert_eq!((red[0].g, red[0].b), (0, 0), "the tint never arrived");
    assert!(red[0].r > 0, "the tint removed the whole sprite");
}

/// ⚠️ **The camera is fitted to what is drawn.** A transparent draw far from
/// the rest would otherwise frame empty space and shrink everything else to a
/// few pixels — the same fault as D264's over-deep geometry, from a different
/// cause.
#[test]
fn an_invisible_draw_does_not_stretch_the_bounds() {
    let mut entry = one_draw(Modulate::default());
    let far = Draw {
        mesh: 1,
        chain: vec![1],
        ..entry.parts[0].draws[0].clone()
    };
    entry.parts[0].draws.push(far);
    let meshes = [triangle(0), triangle(4_000)];
    let images = white();
    let visible = [node(255.0), node(255.0)];
    let faded = [node(255.0), node(0.0)];
    let span = |nodes: &[NodeDef]| {
        bounds(
            &entry,
            Some(Art {
                images: &images,
                meshes: &meshes,
                nodes,
                curves: &[],
            }),
        )
    };
    assert!(span(&visible).max.x > 1_000.0, "the control never reached");
    assert!(
        span(&faded).max.x < 1_000.0,
        "a transparent draw still framed the camera: {:?}",
        span(&faded).max
    );
}

/// One triangle, ten units across, starting at `at` along x.
fn triangle(at: i32) -> Geometry {
    Geometry {
        positions: vec![at, 0, 0, at + 10, 0, 0, at, 10, 0],
        triangles: vec![0, 1, 2],
        ..Default::default()
    }
}

fn art_of<'a>(images: &'a [Vec<Option<Texture>>], nodes: &'a [NodeDef]) -> Art<'a> {
    Art {
        images,
        meshes: &[],
        nodes,
        curves: &[],
    }
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
        .pieces
        .iter()
        .map(|quad| Piece {
            mesh: &quad.mesh,
            flat: quad.colour,
        })
        .collect();
    assert!(scene(&pieces, &view, Size::new(0, 0)).as_rgba().is_empty());
}
