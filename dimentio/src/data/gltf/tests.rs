//! Reading the container, the material chain and the morph clips out of files
//! this module's own `fixtures` wrote.

use super::fixtures::{animated_quad, bare_triangle, textured_quad, QUAD_UVS};
use super::*;
use crate::data::mesh::Mesh;
use crate::data::scratch::Scratch;
use crate::data::texture::Texel;

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

/// ⛔ The regression that prompted this reader. A `.glb` is binary, and
/// reading it as UTF-8 text fails in a way that looked like the file was
/// absent — every model in the folder reported "Mesh file is missing"
/// while sitting on disk.
#[test]
fn a_binary_gltf_is_not_reported_as_a_missing_file() {
    let scratch = Scratch::new("glb-missing");
    let path = scratch.path.join("cube.glb");
    scratch.write("cube.glb", bare_triangle());
    let mesh = Mesh::load(&path).expect("a glb should load");
    assert_eq!(mesh.positions().len(), 3);
    assert_eq!(mesh.faces().len(), 1);
}

#[test]
fn the_format_is_sniffed_by_content_not_by_extension() {
    let scratch = Scratch::new("glb-sniff");
    scratch.write("actually_gltf.obj", bare_triangle());
    let path = scratch.path.join("actually_gltf.obj");
    assert!(Mesh::load(&path).is_ok(), "extension should not decide");
}

#[test]
fn obj_still_loads_alongside_it() {
    let scratch = Scratch::new("glb-obj");
    scratch.write("plain.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");
    let path = scratch.path.join("plain.obj");
    assert_eq!(Mesh::load(&path).expect("obj").faces().len(), 1);
}

#[test]
fn a_truncated_glb_is_refused_rather_than_panicking() {
    let mut raw = bare_triangle();
    raw.truncate(40);
    assert!(parse(&raw).is_err());
}

#[test]
fn something_that_is_neither_gltf_nor_text_is_named_as_such() {
    let scratch = Scratch::new("glb-junk");
    scratch.write("junk.glb", [0xFF_u8, 0xFE, 0x00, 0x01, 0x02]);
    let path = scratch.path.join("junk.glb");
    let problem = Mesh::load(&path).expect_err("junk should not load");
    assert!(format!("{problem:?}").contains("text"), "{problem:?}");
}

/// ⚠️ The state 277 of 864 real models are in. A mesh with no material
/// must load, and must carry nothing that would send it down the textured
/// path — otherwise flat shading is silently replaced by a black surface.
#[test]
fn a_model_with_no_material_carries_no_uvs_and_no_texture() {
    let parts = parse(&bare_triangle()).expect("bare triangle parses");
    assert!(parts.uvs.is_none());
    assert!(parts.paints.is_empty());
    assert!(parts
        .into_mesh()
        .batches()
        .all(|batch| batch.surface.is_none()));
}

#[test]
fn texcoords_the_image_and_the_alpha_mode_are_all_read() {
    let parts = parse(&textured_quad(QUAD_UVS, 2, 1, &[RED, GREEN])).expect("textured quad parses");
    assert_eq!(parts.positions.len(), 4);
    assert_eq!(parts.faces.len(), 2);
    let paint = parts.paints.first().expect("a material");
    assert!(paint.masked, "alphaMode MASK was not read");

    let uvs = parts.uvs.as_ref().expect("TEXCOORD_0");
    assert_eq!(uvs.len(), 4);
    assert_eq!((uvs[0].u, uvs[0].v), (0.0, 1.0));
    assert_eq!((uvs[2].u, uvs[2].v), (1.0, 0.0));

    let texture = &paint.texture;
    assert_eq!(texture.width(), 2);
    assert_eq!(texture.height(), 1);
    let plain = crate::data::texture::Sampling::default();
    assert_eq!(texture.sample(0.25, 0.5, &plain), RED);
    assert_eq!(texture.sample(0.75, 0.5, &plain), GREEN);
}

/// The image sits in the same BIN chunk as the geometry, at an offset the
/// document declares. Reading the wrong view yields geometry bytes, which
/// the PNG decoder rejects — so this is the test that the chain
/// material → texture → image → bufferView is walked correctly.
/// ⚠️ Every model that carries no clip must come back exactly as it did
/// before any of this existed. 646 of 864 exported models are in that
/// state, and an `Animation` conjured out of an empty target list would
/// give every one of them a clip picker over nothing.
#[test]
fn a_model_with_no_targets_carries_no_animation() {
    let parts = parse(&bare_triangle()).expect("bare triangle parses");
    assert!(parts.animation.is_none());
    assert!(parts.into_mesh().animation().is_none());
}

#[test]
fn the_targets_and_both_clips_are_read() {
    let parts = parse(&animated_quad()).expect("animated quad parses");
    let animation = parts.animation.as_ref().expect("an animation");
    assert_eq!(animation.targets(), 2);
    let names: Vec<&str> = animation
        .clips()
        .iter()
        .map(|clip| clip.name.as_str())
        .collect();
    assert_eq!(names, ["wave", "jump"]);
}

/// ⛔ The failure that looks like success: reading the sampler's *index*
/// as its accessor. Both are small integers, the file still loads, and the
/// clip plays whatever accessor 0 happens to be.
#[test]
fn a_clips_keyframes_are_its_own_times_and_weights() {
    let parts = parse(&animated_quad()).expect("animated quad parses");
    let animation = parts.animation.as_ref().expect("an animation");
    let wave = &animation.clips()[0];
    assert_eq!(wave.keys.len(), 2);
    assert_eq!(wave.keys[0].time, 0.0);
    assert_eq!(wave.keys[0].weights, vec![1.0, 0.0]);
    assert_eq!(wave.keys[1].time, 1.0);
    assert_eq!(wave.keys[1].weights, vec![0.0, 1.0]);
    assert_eq!(wave.seconds(), 1.0);

    let jump = &animation.clips()[1];
    assert_eq!(jump.keys.len(), 1);
    assert_eq!(jump.keys[0].weights, vec![0.0, 1.0]);
}

/// The whole point, on the mesh rather than the accessors: posing moves
/// the vertices the target names and leaves the others where they were.
#[test]
fn posing_a_loaded_mesh_moves_the_vertices_its_target_names() {
    let scratch = Scratch::new("glb-morph");
    scratch.write("wave.glb", animated_quad());
    let mut mesh = Mesh::load(&scratch.path.join("wave.glb")).expect("animated quad loads");
    let rest = mesh.rest_positions().to_vec();
    assert_eq!(mesh.positions(), rest, "nothing is posed until it is asked");

    mesh.pose(0, 0.0);
    assert_eq!(mesh.positions()[0], rest[0] + Vec3::new(0.0, 3.0, 0.0));
    assert_eq!(mesh.positions()[2], rest[2]);

    mesh.pose(0, 1.0);
    assert_eq!(mesh.positions()[0], rest[0]);
    assert_eq!(mesh.positions()[2], rest[2] + Vec3::new(3.0, 0.0, 0.0));

    mesh.unpose();
    assert_eq!(mesh.positions(), rest);
}

/// ⚠️ The bounds are measured once, from the rest pose. A box that
/// followed the animation would refit the camera on every frame.
#[test]
fn posing_does_not_move_the_bounds_the_camera_is_framed_from() {
    let scratch = Scratch::new("glb-morph-bounds");
    scratch.write("wave.glb", animated_quad());
    let mut mesh = Mesh::load(&scratch.path.join("wave.glb")).expect("loads");
    let before = mesh.bounds();
    mesh.pose(0, 0.0);
    assert_eq!(mesh.bounds(), before);
}

#[test]
fn posing_a_mesh_with_no_animation_leaves_it_exactly_as_it_was() {
    let scratch = Scratch::new("glb-nomorph");
    scratch.write("bare.glb", bare_triangle());
    let mut mesh = Mesh::load(&scratch.path.join("bare.glb")).expect("loads");
    let before = mesh.positions().to_vec();
    mesh.pose(0, 0.5);
    mesh.pose(7, 900.0);
    assert_eq!(mesh.positions(), before);
}

#[test]
fn the_texture_survives_a_round_trip_through_a_file_on_disk() {
    let scratch = Scratch::new("glb-textured");
    scratch.write("quad.glb", textured_quad(QUAD_UVS, 2, 1, &[RED, GREEN]));
    let mesh = Mesh::load(&scratch.path.join("quad.glb")).expect("textured quad loads");
    let surface = mesh
        .batches()
        .next()
        .and_then(|batch| batch.surface)
        .expect("a surface");
    assert_eq!(surface.texture.sample(0.75, 0.5, surface.sampling), GREEN);
    assert_eq!(surface.uvs.len(), mesh.positions().len());
}
