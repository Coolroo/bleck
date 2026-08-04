//! Painting a mesh with the texture its file carried.
//!
//! ⚠️ Every assertion here is on the pixel buffer, because the machine this is
//! built on cannot capture its own screen — a texture that samples the wrong
//! texel, or the right texel at the wrong place, looks fine in a screenshot
//! nobody can take.

use super::*;
use crate::data::gltf;
use crate::data::gltf::fixtures::{bare_quad, painted_quads, textured_quad, tiled, QUAD_UVS};
use crate::data::mesh::{Mesh, Modulate};
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
            &mut Band::whole(&mut image, &mut depth),
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
                blend: Blend::Opaque,
                tint: None,
                texture: &base,
                corners: [Uv::new(0.5, 0.5); 3],
                intensity: 1.0,
                masked: true,
                cutoff: MASK_CUTOFF,
                sampling: &Sampling::default(),
                modulate: Modulate::default(),
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
        &mut Band::whole(&mut image, &mut depth),
        &near,
        &Paint::Textured {
            blend: Blend::Opaque,
            tint: None,
            texture: surface.texture,
            corners: [Uv::new(0.5, 0.5); 3],
            intensity: 1.0,
            masked: true,
            cutoff: MASK_CUTOFF,
            sampling: surface.sampling,
            modulate: Modulate::default(),
            mask: surface.mask,
        },
    );
    assert_eq!(covered(&image), 0, "a transparent texel was drawn");

    let far = at(0.1);
    raster(
        &mut Band::whole(&mut image, &mut depth),
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
