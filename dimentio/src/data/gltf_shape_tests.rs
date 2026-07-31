//! One glTF primitive per shape: reading all of them, and hiding one.
//!
//! ⚠️ Split out of `gltf.rs` only to keep that module under a thousand lines,
//! the same way `mesh_real_tests.rs` was split out of `mesh.rs`. `#[path]` in
//! `gltf.rs` keeps the module where it was.
//!
//! ⛔ **The reader took `primitives[0]` and drew one limb of 92** (D236). The
//! fixtures below are two primitives that sit far apart, so a reader that
//! stopped at the first is visible in the vertex count, the face count and the
//! bounds alike.

use super::fixtures::{container, pad, painted_quads, push_floats};
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
const BLUE: Texel = Texel {
    r: 0,
    g: 0,
    b: 255,
    a: 255,
};

/// Two quads as two primitives of one mesh: the first around the origin, the
/// second ten units along X so no bounds test can confuse them.
///
/// `animated` adds one morph target to each, in the order glTF requires — same
/// count, same position in both lists. Target 0 lifts the first quad's vertex 0
/// by 3 on Y and moves nothing in the second; target 1 pushes the second quad's
/// vertex 2 by 4 on X and moves nothing in the first.
fn two_shapes(animated: bool) -> Vec<u8> {
    let near: [f32; 12] = [
        -2.0, -2.0, 0.0, 2.0, -2.0, 0.0, 2.0, 2.0, 0.0, -2.0, 2.0, 0.0,
    ];
    let far: [f32; 12] = [
        10.0, -2.0, 0.0, 14.0, -2.0, 0.0, 14.0, 2.0, 0.0, 10.0, 2.0, 0.0,
    ];
    let mut bin = Vec::new();
    push_floats(&mut bin, &near);
    let far_at = bin.len();
    push_floats(&mut bin, &far);
    let first_indices = pad(&mut bin, &[0u32, 1, 2, 0, 2, 3]);
    let second_indices = pad(&mut bin, &[0u32, 1, 2, 0, 2, 3]);

    let mut targets = [(0usize, 0usize), (0, 0)];
    let mut blocks = String::new();
    let mut views = String::new();
    if animated {
        let lift = bin.len();
        push_floats(
            &mut bin,
            &[0.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        );
        let still = bin.len();
        push_floats(&mut bin, &[0.0; 12]);
        let push = bin.len();
        push_floats(
            &mut bin,
            &[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        );
        let times = bin.len();
        push_floats(&mut bin, &[0.0, 1.0]);
        let weights = bin.len();
        push_floats(&mut bin, &[1.0, 0.0, 0.0, 1.0]);

        targets = [(4, 5), (6, 5)];
        blocks = r#"
            ,{"bufferView":4,"componentType":5126,"count":4,"type":"VEC3"}
            ,{"bufferView":5,"componentType":5126,"count":4,"type":"VEC3"}
            ,{"bufferView":6,"componentType":5126,"count":4,"type":"VEC3"}
            ,{"bufferView":7,"componentType":5126,"count":2,"type":"SCALAR"}
            ,{"bufferView":8,"componentType":5126,"count":4,"type":"SCALAR"}"#
            .to_owned();
        views = format!(
            r#",{{"buffer":0,"byteOffset":{lift},"byteLength":48}}
               ,{{"buffer":0,"byteOffset":{still},"byteLength":48}}
               ,{{"buffer":0,"byteOffset":{push},"byteLength":48}}
               ,{{"buffer":0,"byteOffset":{times},"byteLength":8}}
               ,{{"buffer":0,"byteOffset":{weights},"byteLength":16}}"#
        );
    }

    let (first_targets, second_targets) = if animated {
        (
            format!(
                r#","targets":[{{"POSITION":{}}},{{"POSITION":{}}}]"#,
                targets[0].0, targets[0].1
            ),
            format!(
                r#","targets":[{{"POSITION":{}}},{{"POSITION":{}}}]"#,
                targets[1].1, targets[1].0
            ),
        )
    } else {
        (String::new(), String::new())
    };
    let animations = if animated {
        r#","animations":[{"name":"both",
             "samplers":[{"input":7,"output":8,"interpolation":"LINEAR"}],
             "channels":[{"sampler":0,"target":{"node":0,"path":"weights"}}]}]"#
    } else {
        ""
    };
    let weights = if animated {
        r#""weights":[0.0,0.0],"#
    } else {
        ""
    };

    let json = format!(
        r#"{{"asset":{{"version":"2.0"}},
            "meshes":[{{{weights}"primitives":[
              {{"attributes":{{"POSITION":0}},"indices":1{first_targets}}},
              {{"attributes":{{"POSITION":2}},"indices":3{second_targets}}}]}}]
            {animations},
            "accessors":[{{"bufferView":0,"componentType":5126,"count":4,"type":"VEC3"}},
                         {{"bufferView":1,"componentType":5125,"count":6,"type":"SCALAR"}},
                         {{"bufferView":2,"componentType":5126,"count":4,"type":"VEC3"}},
                         {{"bufferView":3,"componentType":5125,"count":6,"type":"SCALAR"}}
                         {blocks}],
            "bufferViews":[{{"buffer":0,"byteOffset":0,"byteLength":48}},
                           {{"buffer":0,"byteOffset":{first_indices},"byteLength":24}},
                           {{"buffer":0,"byteOffset":{far_at},"byteLength":48}},
                           {{"buffer":0,"byteOffset":{second_indices},"byteLength":24}}
                           {views}],
            "buffers":[{{"byteLength":{}}}]}}"#,
        bin.len()
    );
    container(&json, &bin)
}

#[test]
fn every_primitive_is_read_not_only_the_first() {
    let parts = parse(&two_shapes(false)).expect("two primitives parse");
    assert_eq!(parts.positions.len(), 8, "the second primitive was dropped");
    assert_eq!(parts.faces.len(), 4);
}

/// ⛔ The mistake that draws a plausible model: appending the second
/// primitive's positions without shifting its indices, which folds its
/// triangles back onto the first primitive's vertices.
#[test]
fn a_later_primitives_indices_are_rebased_onto_the_merged_positions() {
    let parts = parse(&two_shapes(false)).expect("parses");
    let reach = parts
        .faces
        .iter()
        .flat_map(|face| [face.a, face.b, face.c])
        .max()
        .expect("faces");
    assert_eq!(reach, 7, "the second primitive still points at the first");
}

#[test]
fn each_primitive_becomes_a_shape_covering_its_own_faces() {
    let mesh = parse(&two_shapes(false)).expect("parses").into_mesh();
    let shapes = mesh.shapes();
    assert_eq!(shapes.len(), 2);
    assert_eq!((shapes[0].first, shapes[0].count), (0, 2));
    assert_eq!((shapes[1].first, shapes[1].count), (2, 2));
    assert!(shapes.iter().all(|shape| shape.visible));
    assert_eq!(mesh.hidden_shapes(), 0);
}

/// The point of the split: one stray shape can be taken off the screen.
#[test]
fn hiding_a_shape_stops_its_triangles_being_drawn() {
    let mut mesh = parse(&two_shapes(false)).expect("parses").into_mesh();
    mesh.set_shape_visible(1, false);
    assert_eq!(mesh.faces().len(), 2);
    assert_eq!(mesh.hidden_shapes(), 1);
    for face in mesh.faces() {
        for corner in [face.a, face.b, face.c] {
            assert!(corner < 4, "a hidden shape's triangle was still drawn");
        }
    }
    mesh.show_all_shapes();
    assert_eq!(mesh.faces().len(), 4);
    assert_eq!(mesh.hidden_shapes(), 0);
}

/// ⚠️ The bounds are measured once, from every shape. A box that shrank as
/// shapes were hidden would zoom the viewport on each click.
#[test]
fn hiding_a_shape_does_not_move_the_bounds_the_camera_is_framed_from() {
    let mut mesh = parse(&two_shapes(false)).expect("parses").into_mesh();
    let before = mesh.bounds();
    mesh.set_shape_visible(1, false);
    assert_eq!(mesh.bounds(), before);
    assert_eq!(before.max.x, 14.0, "the far quad was never in the box");
}

#[test]
fn hiding_a_shape_that_is_not_there_changes_nothing() {
    let mut mesh = parse(&two_shapes(false)).expect("parses").into_mesh();
    mesh.set_shape_visible(9, false);
    assert_eq!(mesh.faces().len(), 4);
    assert_eq!(mesh.hidden_shapes(), 0);
}

/// An OBJ names no groups, so it is one shape — a viewer offering nothing to
/// toggle would read as a control that had broken.
#[test]
fn an_obj_loads_as_a_single_shape_over_all_of_it() {
    let scratch = Scratch::new("glb-shapes-obj");
    scratch.write("plain.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");
    let mesh = Mesh::load(&scratch.path.join("plain.obj")).expect("obj");
    assert_eq!(mesh.shapes().len(), 1);
    assert_eq!(mesh.shapes()[0].count, 1);
}

/// ⚠️ **Targets are per-primitive and weights are per-mesh**, so target 1 of
/// the second primitive is the same pose as target 1 of the first. Reading only
/// the first primitive's list, or concatenating the lists end to end, both give
/// a file that loads and animates the wrong vertices.
#[test]
fn a_pose_displaces_the_primitive_that_owns_it() {
    let mut mesh = parse(&two_shapes(true))
        .expect("animated pair parses")
        .into_mesh();
    let animation = mesh.animation().expect("an animation").clone();
    assert_eq!(animation.targets(), 2);

    let rest = mesh.rest_positions().to_vec();
    mesh.pose(0, 0.0);
    assert_eq!(mesh.positions()[0], rest[0] + Vec3::new(0.0, 3.0, 0.0));
    assert_eq!(mesh.positions()[6], rest[6], "the far quad moved on pose 0");

    mesh.pose(0, 1.0);
    assert_eq!(mesh.positions()[0], rest[0], "the near quad stayed moved");
    assert_eq!(mesh.positions()[6], rest[6] + Vec3::new(4.0, 0.0, 0.0));
}

/// Every target must reach every vertex of the model, not only the primitive it
/// came from — `Animation::displace` walks them in lockstep with the positions.
#[test]
fn every_target_spans_the_whole_merged_vertex_list() {
    let mesh = parse(&two_shapes(true)).expect("parses").into_mesh();
    let animation = mesh.animation().expect("an animation");
    assert_eq!(animation.targets(), 2);
    let mut posed = mesh.clone();
    posed.pose(0, 0.5);
    assert_eq!(posed.positions().len(), 8);
}

/// ⛔ **The reader took the first material that yielded an image and painted
/// the whole mesh with it** (D246). Three primitives, three images: a reader
/// that stops at the first decodes one image and binds it three times.
#[test]
fn each_primitive_resolves_its_own_image() {
    let parts = parse(&painted_quads(&[Some(RED), Some(GREEN), Some(BLUE)])).expect("parses");
    assert_eq!(parts.paints.len(), 3, "the images were collapsed into one");

    let slots: Vec<Option<usize>> = parts.shapes.iter().map(|shape| shape.paint).collect();
    assert_eq!(slots, [Some(0), Some(1), Some(2)]);

    let sampled: Vec<Texel> = parts
        .paints
        .iter()
        .map(|paint| paint.texture.sample(0.5, 0.5))
        .collect();
    assert_eq!(sampled, [RED, GREEN, BLUE], "a slot holds the wrong image");
}

/// A primitive with no material keeps its span and draws flat, beside ones that
/// do — 24 of `e_lui_robo`'s 92 primitives are in that state, and 269 models
/// mix the two.
#[test]
fn an_unpainted_primitive_sits_between_painted_ones_without_taking_their_image() {
    let parts = parse(&painted_quads(&[Some(RED), None, Some(BLUE)])).expect("parses");
    let slots: Vec<Option<usize>> = parts.shapes.iter().map(|shape| shape.paint).collect();
    assert_eq!(slots, [Some(0), None, Some(1)]);
    assert_eq!(parts.paints.len(), 2);

    let mesh = parts.into_mesh();
    let painted: Vec<bool> = mesh
        .batches()
        .map(|batch| batch.surface.is_some())
        .collect();
    assert_eq!(painted, [true, false, true]);
}

/// ⚠️ **One decode per material, not per primitive.** Two primitives naming
/// material 0 must share one image rather than decoding the same PNG twice —
/// `e_lui_robo` has 68 painted primitives over 15 materials.
#[test]
fn primitives_that_name_one_material_share_a_single_decoded_image() {
    let raw = painted_quads(&[Some(RED), Some(GREEN)]);
    let chunks = split_chunks(&raw).expect("the fixture is a glb");
    let json = std::str::from_utf8(chunks.json).expect("the JSON chunk is text");
    assert!(
        json.contains(r#""material":1"#),
        "the fixture is not paired"
    );
    let shared = json.replace(r#""material":1"#, r#""material":0"#);
    let parts = parse(&container(&shared, chunks.bin)).expect("parses");

    assert_eq!(parts.paints.len(), 1, "one material decoded twice");
    let slots: Vec<Option<usize>> = parts.shapes.iter().map(|shape| shape.paint).collect();
    assert_eq!(slots, [Some(0), Some(0)]);
}

/// ⚠️ **`faces` and `batches` must describe the same triangles.** The renderer
/// walks one and every test asserts on the other, so a shape hidden from one
/// and not the other would be invisible to both.
#[test]
fn the_batches_flatten_to_exactly_the_faces_that_are_drawn() {
    let mut mesh = parse(&painted_quads(&[Some(RED), Some(GREEN), Some(BLUE)]))
        .expect("parses")
        .into_mesh();
    let flattened = |mesh: &Mesh| -> Vec<Face> {
        mesh.batches()
            .flat_map(|batch| batch.faces.to_vec())
            .collect()
    };
    assert_eq!(flattened(&mesh), mesh.faces());

    mesh.set_shape_visible(1, false);
    assert_eq!(flattened(&mesh), mesh.faces());
    assert_eq!(mesh.batches().count(), 2);
}
