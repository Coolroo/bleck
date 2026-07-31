//! One pose, written every way `bleck` can write it, read back the same.
//!
//! ⚠️ **The assertions are on positions, not on the document.** Sparse and
//! dense are two encodings of one displacement; a test that compared accessor
//! records would pass on a reader that applied the values to the wrong
//! vertices, which is exactly the failure a sparse index array invites.
//!
//! ⛔ **The index array is the whole difference.** Applying values in order
//! instead loads, animates, and moves the first *n* vertices of the primitive
//! rather than the ones the pose names.

use super::*;
use crate::data::gltf::fixtures::{container, pad, push_floats};
use crate::data::gltf::parse;
use crate::data::mesh::Mesh;
use crate::data::scratch::Scratch;

/// How the one morph target in `morphed_quad` is encoded.
#[derive(Clone, Copy, PartialEq)]
enum Encoding {
    /// A buffer view holding a delta for every vertex, zeros included.
    Dense,
    /// No base buffer view, and a sparse block naming vertices 0 and 2.
    Sparse(u64),
    /// A sparse block that deviates nothing — which `bleck` never writes,
    /// because the specification puts a minimum of 1 on `sparse.count`.
    Empty,
    /// Neither a buffer view nor a sparse block: zeros, by definition.
    Missing,
    /// A sparse index that points past the end of the accessor it deviates.
    Astray,
}

impl Encoding {
    /// The component type this encoding's sparse index array declares.
    fn index_kind(self) -> u64 {
        match self {
            Encoding::Sparse(kind) => kind,
            _ => UNSIGNED_BYTE,
        }
    }
}

/// A quad with one morph target that lifts vertex 0 by 3 on Y and pushes
/// vertex 2 by 5 on X, and one clip holding that target at weight 1.
fn morphed_quad(encoding: Encoding) -> Vec<u8> {
    let positions: [f32; 12] = [
        -2.0, -2.0, 0.0, 2.0, -2.0, 0.0, 2.0, 2.0, 0.0, -2.0, 2.0, 0.0,
    ];
    let mut bin = Vec::new();
    push_floats(&mut bin, &positions);
    let corners = pad(&mut bin, &[0u32, 1, 2, 0, 2, 3]);

    let dense_at = bin.len();
    push_floats(
        &mut bin,
        &[0.0, 3.0, 0.0, 0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    );

    let index_at = bin.len();
    match encoding {
        Encoding::Sparse(UNSIGNED_SHORT) => {
            bin.extend_from_slice(&0u16.to_le_bytes());
            bin.extend_from_slice(&2u16.to_le_bytes());
        }
        Encoding::Sparse(UNSIGNED_INT) => {
            bin.extend_from_slice(&0u32.to_le_bytes());
            bin.extend_from_slice(&2u32.to_le_bytes());
        }
        Encoding::Astray => bin.extend_from_slice(&[0u8, 40]),
        _ => bin.extend_from_slice(&[0u8, 2]),
    }
    let index_len = bin.len() - index_at;
    while bin.len() % 4 != 0 {
        bin.push(0);
    }

    let values_at = bin.len();
    push_floats(&mut bin, &[0.0, 3.0, 0.0, 5.0, 0.0, 0.0]);
    let times = bin.len();
    push_floats(&mut bin, &[0.0]);
    let weights = bin.len();
    push_floats(&mut bin, &[1.0]);

    let target = match encoding {
        Encoding::Dense => {
            r#"{"bufferView":2,"componentType":5126,"count":4,"type":"VEC3"}"#.to_owned()
        }
        Encoding::Missing => r#"{"componentType":5126,"count":4,"type":"VEC3"}"#.to_owned(),
        Encoding::Empty => r#"{"componentType":5126,"count":4,"type":"VEC3","sparse":{
                "count":0,"indices":{"bufferView":3,"componentType":5121},
                "values":{"bufferView":4}}}"#
            .to_owned(),
        deviating => format!(
            r#"{{"componentType":5126,"count":4,"type":"VEC3","sparse":{{
                "count":2,"indices":{{"bufferView":3,"componentType":{}}},
                "values":{{"bufferView":4}}}}}}"#,
            deviating.index_kind()
        ),
    };

    let json = format!(
        r#"{{"asset":{{"version":"2.0"}},
            "meshes":[{{"weights":[0.0],
                        "primitives":[{{"attributes":{{"POSITION":0}},"indices":1,
                          "targets":[{{"POSITION":2}}]}}]}}],
            "animations":[{{"name":"lift",
                "samplers":[{{"input":3,"output":4,"interpolation":"LINEAR"}}],
                "channels":[{{"sampler":0,"target":{{"node":0,"path":"weights"}}}}]}}],
            "accessors":[{{"bufferView":0,"componentType":5126,"count":4,"type":"VEC3"}},
                         {{"bufferView":1,"componentType":5125,"count":6,"type":"SCALAR"}},
                         {target},
                         {{"bufferView":5,"componentType":5126,"count":1,"type":"SCALAR"}},
                         {{"bufferView":6,"componentType":5126,"count":1,"type":"SCALAR"}}],
            "bufferViews":[{{"buffer":0,"byteOffset":0,"byteLength":48}},
                           {{"buffer":0,"byteOffset":{corners},"byteLength":24}},
                           {{"buffer":0,"byteOffset":{dense_at},"byteLength":48}},
                           {{"buffer":0,"byteOffset":{index_at},"byteLength":{index_len}}},
                           {{"buffer":0,"byteOffset":{values_at},"byteLength":24}},
                           {{"buffer":0,"byteOffset":{times},"byteLength":4}},
                           {{"buffer":0,"byteOffset":{weights},"byteLength":4}}],
            "buffers":[{{"byteLength":{}}}]}}"#,
        bin.len()
    );
    container(&json, &bin)
}

/// The four positions the quad draws once its one clip is posed.
fn posed(encoding: Encoding) -> Vec<Vec3> {
    let scratch = Scratch::new("glb-sparse");
    scratch.write("quad.glb", morphed_quad(encoding));
    let mut mesh = Mesh::load(&scratch.path.join("quad.glb")).expect("the quad loads");
    mesh.pose(0, 0.0);
    mesh.positions().to_vec()
}

/// ⚠️ **The claim, on the mesh rather than the file.** A reader that read the
/// sparse block at all but landed the values elsewhere would still pass every
/// structural check that could be written about the document.
#[test]
fn a_sparse_target_displaces_the_mesh_exactly_as_the_dense_one_does() {
    assert_eq!(
        posed(Encoding::Sparse(UNSIGNED_BYTE)),
        posed(Encoding::Dense)
    );
}

/// ⛔ The mutation this guards: applying the values in order. Vertices 0 and 1
/// would move instead of 0 and 2, and the file would still load.
#[test]
fn the_sparse_values_land_on_the_vertices_the_index_array_names() {
    let rest = {
        let scratch = Scratch::new("glb-sparse-rest");
        scratch.write("quad.glb", morphed_quad(Encoding::Dense));
        Mesh::load(&scratch.path.join("quad.glb"))
            .expect("loads")
            .rest_positions()
            .to_vec()
    };
    let moved = posed(Encoding::Sparse(UNSIGNED_BYTE));
    assert_eq!(moved[0], rest[0] + Vec3::new(0.0, 3.0, 0.0));
    assert_eq!(moved[1], rest[1], "vertex 1 is not in the index array");
    assert_eq!(moved[2], rest[2] + Vec3::new(5.0, 0.0, 0.0));
    assert_eq!(moved[3], rest[3]);
}

/// `bleck` narrows the index type to the primitive, so all three widths are
/// files this reader will meet.
#[test]
fn every_index_width_reads_the_same_displacement() {
    let expected = posed(Encoding::Dense);
    for kind in [UNSIGNED_BYTE, UNSIGNED_SHORT, UNSIGNED_INT] {
        assert_eq!(posed(Encoding::Sparse(kind)), expected, "width {kind}");
    }
}

/// ⚠️ **`bleck` cannot write this**, because `accessor.sparse.count` carries a
/// minimum of 1 in the specification's schema. Reading it as "no deviations"
/// costs nothing and is what the field means, so another exporter's file works.
#[test]
fn a_sparse_target_that_deviates_nothing_displaces_nothing() {
    let scratch = Scratch::new("glb-sparse-empty");
    scratch.write("quad.glb", morphed_quad(Encoding::Empty));
    let mut mesh = Mesh::load(&scratch.path.join("quad.glb")).expect("loads");
    let rest = mesh.rest_positions().to_vec();
    mesh.pose(0, 0.0);
    assert_eq!(mesh.positions(), rest);
}

/// What `bleck` writes for a pose that misses a primitive entirely: an
/// accessor with no buffer view at all, which the specification defines as
/// zeros and which occupies no bytes.
#[test]
fn a_target_with_no_buffer_view_reads_as_zeros_rather_than_failing() {
    let scratch = Scratch::new("glb-sparse-missing");
    scratch.write("quad.glb", morphed_quad(Encoding::Missing));
    let mut mesh = Mesh::load(&scratch.path.join("quad.glb")).expect("loads");
    let rest = mesh.rest_positions().to_vec();
    mesh.pose(0, 0.0);
    assert_eq!(mesh.positions(), rest);
}

/// ⚠️ **An index off the end must cost the target, not the file.** One bad
/// accessor in a 90-primitive model would otherwise take the whole model off
/// the screen.
#[test]
fn a_sparse_index_past_the_end_of_the_accessor_costs_only_that_target() {
    let parts = parse(&morphed_quad(Encoding::Astray)).expect("the file still parses");
    let rest = parts.positions.clone();
    let mut mesh = parts.into_mesh();
    mesh.pose(0, 0.0);
    assert_eq!(
        mesh.positions(),
        rest,
        "a target that would not read moved the mesh anyway"
    );
}

/// ⚠️ The control for the test above. Without it, a reader that refused
/// *every* sparse target would pass it.
#[test]
fn the_same_file_with_a_valid_index_does_move_the_mesh() {
    let parts = parse(&morphed_quad(Encoding::Sparse(UNSIGNED_BYTE))).expect("parses");
    let rest = parts.positions.clone();
    let mut mesh = parts.into_mesh();
    mesh.pose(0, 0.0);
    assert_ne!(mesh.positions(), rest);
}
