//! Posing one node of an effect's scene graph at a frame.
//!
//! ✅ **The game's own scheme**, transcribed from the evaluator at
//! `0x8005f2d4` (D265, D266): each node's ten scalars are its static values
//! with any curve of its own written over the top, rotated z then y then x in
//! degrees, and the chain multiplied parent-first.
//!
//! Everything here takes a node and a curve table as *arguments*. It knows
//! nothing about effects, parts, draws, quads or the camera, which is why it
//! can be read — and checked against the file's own stored matrices — without
//! the renderer next door.

use crate::data::effects::{Curve, NodeDef};
use crate::data::mesh::Vec3;

/// A node's ten scalars at `frame`: its static values, with any curve of its
/// own written over the top.
///
/// ✅ **The order the game uses**, read off the slot array it fills at
/// `0x8005f290`. ⚠️ A curve that has not started leaves the static value alone
/// rather than zeroing it.
#[rustfmt::skip]
fn slots_at(node: &NodeDef, curves: &[Curve], frame: f32) -> [f32; 10] {
    let pick = |v: &Vec<f32>, at: usize| v.get(at).copied().unwrap_or(0.0);
    // Three to a row: translate, rotate, scale, then alpha — the order the
    // game's own slot array is filled in.
    let mut slots = [
        pick(&node.t, 0), pick(&node.t, 1), pick(&node.t, 2),
        pick(&node.r, 0), pick(&node.r, 1), pick(&node.r, 2),
        pick(&node.s, 0), pick(&node.s, 1), pick(&node.s, 2),
        node.alpha,
    ];
    for [slot, curve] in &node.curves {
        if let Some(value) = curves.get(*curve).and_then(|c| c.value_at(frame)) {
            if let Some(cell) = slots.get_mut(*slot) {
                *cell = value;
            }
        }
    }
    slots
}

/// A 3x3 rotation about one axis, in degrees.
fn turn(axis: usize, degrees: f32) -> [f32; 9] {
    let (sin, cos) = degrees.to_radians().sin_cos();
    match axis {
        0 => [1.0, 0.0, 0.0, 0.0, cos, -sin, 0.0, sin, cos],
        1 => [cos, 0.0, sin, 0.0, 1.0, 0.0, -sin, 0.0, cos],
        _ => [cos, -sin, 0.0, sin, cos, 0.0, 0.0, 0.0, 1.0],
    }
}

fn times(a: &[f32; 9], b: &[f32; 9]) -> [f32; 9] {
    let mut out = [0.0; 9];
    for row in 0..3 {
        for col in 0..3 {
            out[row * 3 + col] = (0..3).map(|k| a[row * 3 + k] * b[k * 3 + col]).sum();
        }
    }
    out
}

/// A node's own transform at `frame`, as a 3x4 row-major matrix.
///
/// ⚠️ Rotates **z, then y, then x, in degrees** - the order measured against
/// the file's own stored matrices, which agree on 3,738 of 3,739 nodes (D265).
fn local(node: &NodeDef, curves: &[Curve], frame: f32) -> [f32; 12] {
    let slots = slots_at(node, curves, frame);
    let mut spin = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0];
    for axis in [2usize, 1, 0] {
        spin = times(&spin, &turn(axis, slots[3 + axis]));
    }
    let mut out = [0.0; 12];
    for row in 0..3 {
        for col in 0..3 {
            out[row * 4 + col] = spin[row * 3 + col] * slots[6 + col];
        }
        out[row * 4 + 3] = slots[row];
    }
    out
}

fn concat(a: &[f32; 12], b: &[f32; 12]) -> [f32; 12] {
    let mut out = [0.0; 12];
    for row in 0..3 {
        for col in 0..3 {
            out[row * 4 + col] = (0..3).map(|k| a[row * 4 + k] * b[k * 4 + col]).sum();
        }
        out[row * 4 + 3] =
            (0..3).map(|k| a[row * 4 + k] * b[k * 4 + 3]).sum::<f32>() + a[row * 4 + 3];
    }
    out
}

pub(super) const IDENTITY: [f32; 12] = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0];

/// The rate the game counts effect frames at, and so what turns the scrubber's
/// seconds into the frame a curve is sampled at.
pub(super) const FRAME_RATE: f32 = 60.0;

/// One point through a 3x4 transform.
pub(super) fn apply(m: &[f32; 12], x: f32, y: f32, z: f32) -> Vec3 {
    Vec3::new(
        m[0] * x + m[1] * y + m[2] * z + m[3],
        m[4] * x + m[5] * y + m[6] * z + m[7],
        m[8] * x + m[9] * y + m[10] * z + m[11],
    )
}

/// Where a draw sits at `frame`: every node of its chain posed and multiplied,
/// parent first.
///
/// ✅ **This is a measured position, not a layout.** An export predating the
/// decoding carries no chain, and then the identity is returned and every part
/// stacks at the origin - which is honest about knowing nothing.
pub(super) fn posed(chain: &[usize], nodes: &[NodeDef], curves: &[Curve], frame: f32) -> [f32; 12] {
    let mut world = IDENTITY;
    for index in chain {
        if let Some(node) = nodes.get(*index) {
            world = concat(&world, &local(node, curves, frame));
        }
    }
    world
}

/// Whether a transform collapses volume to nothing.
///
/// ⚠️ Not a fault: an effect's parts scale up from zero, so a part is
/// legitimately flat before it begins. Skipping them keeps degenerate
/// triangles out of the rasteriser.
pub(super) fn flat(m: &[f32; 12]) -> bool {
    let det = m[0] * (m[5] * m[10] - m[6] * m[9]) - m[1] * (m[4] * m[10] - m[6] * m[8])
        + m[2] * (m[4] * m[9] - m[5] * m[8]);
    det.abs() < 1e-9
}
