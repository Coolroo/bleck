//! ⚠️ Every assertion here is on the pixel buffer. Nobody can look at this
//! window — the machine it is built on cannot capture its own desktop — so a
//! viewport that draws nothing, draws the wrong number of things, or keeps
//! drawing a part that has finished is only visible here.

use super::*;
use crate::data::effects::Part;
use crate::data::mesh::Modulate;
use crate::data::texture::{png, Texel, Wrap};
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
        Surface {
            blend: Blend::Alpha,
            ..Default::default()
        },
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
            ..Default::default()
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
                material: None,
                sampler: None,
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

/// ✅ A faded parent fades its children (D282, `0x8005f734`).
///
/// ⚠️ The chain here is opaque leaf under faded parent, which is exactly the
/// case D280's "take the last node's alpha" got wrong — an all-opaque chain
/// reduces to the same answer either way, so only a faded *ancestor* separates
/// them. Revert `posed` to `alpha: step.alpha` and this is the test that fails.
#[test]
fn a_faded_parent_fades_the_child_that_issues_the_draw() {
    let mut entry = one_draw(Modulate::default());
    entry.parts[0].draws[0].chain = vec![0, 1];
    let images = white();

    let both_opaque = [node(255.0), node(255.0)];
    let faded_parent = [node(128.0), node(255.0)];
    let at = |nodes: &[NodeDef]| shades(&shot(&entry, 0.0, Some(art_of(&images, nodes))));

    let solid = at(&both_opaque);
    let inherited = at(&faded_parent);
    assert_eq!(solid.len(), 1, "{solid:?}");
    assert_eq!(
        inherited.len(),
        1,
        "the faded chain left the frame entirely"
    );
    assert!(
        inherited[0].r < solid[0].r,
        "the leaf's own 255 was used and the parent's 128 ignored: {:?} vs {:?}",
        inherited[0],
        solid[0]
    );
}

/// ⛔ Zero is absorbing: a transparent parent takes its whole subtree with it,
/// even where the node issuing the draw is fully opaque (D282).
#[test]
fn a_transparent_parent_suppresses_an_opaque_child() {
    let mut entry = one_draw(Modulate::default());
    entry.parts[0].draws[0].chain = vec![0, 1];
    let images = white();
    let nodes = [node(0.0), node(255.0)];

    let frame = shot(&entry, 0.0, Some(art_of(&images, &nodes)));
    assert_eq!(
        shades(&frame),
        Vec::new(),
        "an opaque leaf under a transparent parent still painted"
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
                ..Default::default()
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
        nodes,
        ..Default::default()
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

/// A four-texel image whose quadrants differ, so which texel a UV transform
/// lands on is readable off the frame as a colour.
fn quadrants() -> Vec<Vec<Option<Texture>>> {
    let cell = |r, g, b| Texel { r, g, b, a: 255 };
    let raw = png(
        2,
        2,
        &[
            cell(255, 0, 0),
            cell(0, 255, 0),
            cell(0, 0, 255),
            cell(255, 255, 0),
        ],
    );
    vec![vec![Texture::decode(&raw).ok()]]
}

/// One draw naming row 0 of both shared tables.
fn tabled() -> Entry {
    let mut entry = one_draw(Modulate::default());
    entry.parts[0].draws[0].material = Some(0);
    entry.parts[0].draws[0].sampler = Some(0);
    entry
}

fn art_with<'a>(
    images: &'a [Vec<Option<Texture>>],
    nodes: &'a [NodeDef],
    curves: &'a [Curve],
    materials: &'a [MaterialDef],
    samplers: &'a [SamplerDef],
) -> Art<'a> {
    Art {
        images,
        nodes,
        curves,
        materials,
        samplers,
        ..Default::default()
    }
}

/// A curve holding one value for every frame of a 61-frame part.
fn held(value: f32) -> Curve {
    Curve {
        length: 61,
        start: 0,
        end: 60,
        looping: 0,
        samples: vec![value; 61],
    }
}

/// A curve that is one value for the first half of a part and another for the
/// second, so a frame from each half must differ and nothing else moves.
fn stepped(before: f32, after: f32) -> Curve {
    Curve {
        length: 61,
        start: 0,
        end: 60,
        looping: 0,
        samples: (0..=60)
            .map(|f| if f < 30 { before } else { after })
            .collect(),
    }
}

/// The composition D281 read out of the game's own evaluator: it fills a
/// four-byte slot array from the register and *then* lets a curve overwrite one
/// byte by tag. A material driving green alone keeps its own red, blue and
/// alpha.
///
/// ⛔ Replacing the whole register, or dropping the static fill, turns every
/// partially animated material into a stranger's colour.
#[test]
fn a_colour_curve_overrides_one_channel_and_leaves_the_register_alone() {
    let material = MaterialDef {
        rgba: vec![10, 20, 30, 40],
        curves: vec![[1, 0]],
    };
    let curves = [held(200.0)];
    let composed = material.at(&curves, 5.0);
    assert_eq!(composed.green, 200, "the curve never reached the channel");
    assert_eq!(
        (composed.red, composed.blue, composed.alpha),
        (10, 30, 40),
        "the curve replaced the whole register instead of one channel"
    );
    let plain = MaterialDef {
        rgba: vec![10, 20, 30, 40],
        curves: Vec::new(),
    };
    assert_eq!(
        plain.at(&curves, 5.0).green,
        20,
        "a material with no curve                 was moved anyway"
    );
}

/// ⚠️ **A curve that has not started leaves the register alone**, which is what
/// `spindash` depends on: its register alpha is 0 and its curve begins at frame
/// 1, so frame 0 is genuinely dark and every later frame is not (D281).
#[test]
fn a_colour_curve_before_its_first_frame_leaves_the_static_value() {
    let material = MaterialDef {
        rgba: vec![255, 255, 255, 0],
        curves: vec![[3, 0]],
    };
    let curves = [Curve {
        length: 91,
        start: 1,
        end: 90,
        looping: 0,
        samples: (1..=90).map(|f| f as f32 * 2.0).collect(),
    }];
    assert_eq!(
        material.at(&curves, 0.0).alpha,
        0,
        "the curve started early"
    );
    assert_eq!(material.at(&curves, 10.0).alpha, 20, "the curve never ran");
}

/// ⛔ **D280's trap, in the other direction.** An export written before the
/// sampler table has no `scale`, and reading a missing one as 0 collapses every
/// texture coordinate onto a single texel — every sprite a flat colour.
#[test]
fn a_sampler_with_no_recorded_scale_multiplies_by_one_rather_than_zero() {
    let plain = SamplerDef::default().at(&[], 0.0);
    assert_eq!(plain.transform.scale, [1.0, 1.0]);
    assert!(
        plain.transform.is_identity(),
        "a blank sampler moved the coordinates: {:?}",
        plain.transform
    );
    assert_eq!(plain.wrap_s, Wrap::Repeat);
    assert_eq!(plain.wrap_t, Wrap::Repeat, "a blank sampler stopped                 repeating, which is how every export before this one sampled");
}

/// ✅ The game builds `Trans(tu, 1 - tv - sv, 0)`, so with the usual `sv == 1`
/// the V shift is **negated**. Reading it as `+tv` runs every scrolling texture
/// backwards, and 75 of the file's 93 texture curves drive exactly that slot.
#[test]
fn the_v_translation_runs_the_way_the_game_builds_it() {
    let sampler = SamplerDef {
        translate: vec![0.25, 0.25],
        scale: vec![1.0, 1.0],
        ..Default::default()
    };
    let how = sampler.at(&[], 0.0);
    assert_eq!(how.transform.offset[0], 0.25, "U was negated");
    assert_eq!(how.transform.offset[1], -0.25, "V was not negated");
}

/// ✅ `Trans(.5,.5,0) · RotRad(z, -r) · Trans(-.5,-.5,0)`: the middle of the
/// image is the one point a rotation leaves alone. 19 of the file's records
/// turn +90 degrees and 7 turn -90.
#[test]
fn a_uv_rotation_turns_about_the_middle_of_the_image() {
    let sampler = SamplerDef {
        rotation: Some(90.0),
        ..Default::default()
    };
    let how = sampler.at(&[], 0.0);
    let (u, v) = how.transform.apply(0.5, 0.5);
    assert!(
        (u - 0.5).abs() < 1e-5 && (v - 0.5).abs() < 1e-5,
        "the centre moved to ({u}, {v}), so the rotation turns about a corner"
    );
    let (u, v) = how.transform.apply(1.0, 0.5);
    assert!(
        (u - 0.5).abs() < 1e-5 && v.abs() < 1e-5,
        "a quarter turn landed at ({u}, {v})"
    );
}

/// ✅ Two bits per axis, decoded by `bleck` into GX's own enum. 84 of the
/// file's 350 records ask for something other than repeat on one axis.
#[test]
fn the_wrap_modes_reach_the_sampler() {
    let of = |s, t| {
        SamplerDef {
            wrap_s: Some(s),
            wrap_t: Some(t),
            ..Default::default()
        }
        .at(&[], 0.0)
    };
    assert_eq!(of(0, 1).wrap_s, Wrap::Clamp);
    assert_eq!(of(0, 1).wrap_t, Wrap::Repeat);
    assert_eq!(of(2, 0).wrap_s, Wrap::Mirror);
    assert_eq!(of(2, 0).wrap_t, Wrap::Clamp);
}

/// ⛔ **The failure D281 exists to close.** The pose is byte-identical across
/// these two frames and only the material's own curve moves — the state 32
/// effects spend 1,523 frames in. A viewer reading the register alone renders
/// both frames the same, and a frozen tail reads as a finished animation.
#[test]
fn a_colour_curve_changes_the_frame_while_the_pose_stands_still() {
    let entry = tabled();
    let images = white();
    let nodes = [node(255.0)];
    let curves = [stepped(255.0, 0.0)];
    let materials = [MaterialDef {
        rgba: vec![0, 0, 255, 255],
        curves: vec![[0, 0]],
    }];
    let art = art_with(&images, &nodes, &curves, &materials, &[]);
    let camera = Camera::fit(bounds(&entry, Some(art)));
    let posed = |time: f32| {
        quads(&entry, time, &camera, Some(art)).pieces[0]
            .mesh
            .positions()
            .to_vec()
    };
    assert_eq!(
        posed(0.1),
        posed(0.8),
        "the pose moved, so a difference in the pixels proves nothing"
    );
    let moved = differing(&shot(&entry, 0.1, Some(art)), &shot(&entry, 0.8, Some(art)));
    assert!(
        moved > 500,
        "a colour curve changed nothing: {moved} pixels"
    );
}

/// The same for the UV evaluator: the pose stands still and a translate curve
/// walks the sampled texel across the image.
#[test]
fn a_uv_curve_changes_the_sampled_texel_while_the_pose_stands_still() {
    let entry = tabled();
    let images = quadrants();
    let nodes = [node(255.0)];
    let curves = [stepped(0.0, -0.5)];
    let samplers = [SamplerDef {
        wrap_s: Some(1),
        wrap_t: Some(1),
        scale: vec![1.0, 1.0],
        curves: vec![[1, 0]],
        ..Default::default()
    }];
    let art = art_with(&images, &nodes, &curves, &[], &samplers);
    let early = shades(&shot(&entry, 0.1, Some(art)));
    let late = shades(&shot(&entry, 0.8, Some(art)));
    assert!(!early.is_empty() && !late.is_empty(), "nothing was drawn");
    assert_ne!(
        early, late,
        "a UV curve left the sampled texels exactly where they were"
    );
}

/// ⚠️ **The static UV transform, with no curve anywhere.** 28 of 139 effects
/// carry one before any curve runs, and it changes which texel every fragment
/// of the draw lands on.
#[test]
fn a_static_uv_transform_changes_which_texel_is_sampled() {
    let entry = tabled();
    let images = quadrants();
    let nodes = [node(255.0)];
    let plain = [SamplerDef {
        scale: vec![1.0, 1.0],
        ..Default::default()
    }];
    let turned = [SamplerDef {
        scale: vec![1.0, 1.0],
        rotation: Some(90.0),
        ..Default::default()
    }];
    let at = |samplers: &[SamplerDef]| {
        let images = &images;
        let nodes = &nodes;
        shades(&shot(
            &entry,
            0.0,
            Some(art_with(images, nodes, &[], &[], samplers)),
        ))
    };
    assert_ne!(
        at(&plain),
        at(&turned),
        "a 90 degree UV rotation sampled exactly the same texels"
    );
}

/// ⚠️ An export predating the tables keeps the draw's own four channels rather
/// than reading a missing row as black.
#[test]
fn a_draw_with_no_material_row_keeps_its_own_channels() {
    let images = white();
    let nodes = [node(255.0)];
    let entry = one_draw(Modulate {
        red: 255,
        green: 0,
        blue: 0,
        alpha: 255,
    });
    let red = shades(&shot(&entry, 0.0, Some(art_of(&images, &nodes))));
    assert_eq!(red.len(), 1, "{red:?}");
    assert_eq!((red[0].g, red[0].b), (0, 0), "the inline tint was dropped");
    assert!(red[0].r > 0, "the fallback removed the whole sprite");
}

/// ⛔ **Rank, not determinant** (D281). `map_derkness` scales its ground sheet
/// by `(1.42857, 0, 1.42857)`: the volume is gone and a 14,000-unit plane is
/// not. The determinant test threw the whole thing away, which is why the
/// effect's frozen tail drew nothing at all rather than a scrolling floor.
#[test]
fn a_transform_that_flattens_a_plane_still_has_something_to_draw() {
    let sheet = [
        1.42857, 0.0, 0.0, 0.0, //
        0.0, 0.0, 0.0, 0.0, //
        0.0, 0.0, 1.42857, 0.0,
    ];
    assert!(!flat(&sheet), "a plane was skipped as having no area");
    let line = [
        0.0, 0.0, 0.0, 0.0, //
        0.0, 0.0, 0.0, 0.0, //
        0.0, 0.0, 1.0, 0.0,
    ];
    assert!(flat(&line), "a line was kept");
    assert!(flat(&[0.0; 12]), "a point was kept");
}

/// The pixels behind the rank rule: a part scaled flat in one axis must still
/// reach the frame, and one scaled to a line must not.
#[test]
fn a_part_flattened_onto_a_plane_is_drawn_and_one_flattened_onto_a_line_is_not() {
    let entry = tabled();
    let images = white();
    let meshes = [triangle(0)];
    let sheet = NodeDef {
        t: vec![0.0, 0.0, 0.0],
        r: vec![0.0, 0.0, 0.0],
        s: vec![1.0, 1.0, 0.0],
        alpha: 255.0,
        curves: Vec::new(),
    };
    let line = NodeDef {
        s: vec![1.0, 0.0, 0.0],
        ..sheet.clone()
    };
    let pieces = |nodes: &[NodeDef]| {
        let art = Art {
            images: &images,
            meshes: &meshes,
            nodes,
            ..Default::default()
        };
        quads(
            &entry,
            0.0,
            &Camera::fit(bounds(&entry, Some(art))),
            Some(art),
        )
        .pieces
        .len()
    };
    assert_eq!(pieces(&[sheet]), 1, "a flattened plane was skipped");
    assert_eq!(pieces(&[line]), 0, "a line was drawn");
}
