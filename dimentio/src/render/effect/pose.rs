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

/// Where a node puts what it draws, and how visible it is there.
///
/// ⚠️ **Both halves come out of the same ten slots.** Nine of them build the
/// matrix and the tenth is alpha; returning only the matrix is what left 660
/// drawing nodes' alpha curves unread (D278, D280).
pub(super) struct Pose {
    pub(super) world: [f32; 12],
    /// Slot 9 folded down the chain, 0..255.
    ///
    /// ✅ **A chain's product, the way the game's walker builds it** (D282).
    /// D280 kept one node's own alpha because inheritance was unestablished;
    /// `0x8005f734` establishes it, and the walker hands the composed value to
    /// a child while a sibling gets the incoming one unchanged -- the same
    /// shape it uses for the matrix and for the mirror-parity flag.
    pub(super) alpha: f32,
}

/// Fully visible: what a node with nothing to say about alpha contributes, and
/// what an export carrying no scene graph at all leaves every draw at.
const OPAQUE: f32 = 255.0;

impl Pose {
    /// What a draw with no scene graph behind it is posed at: stacked on the
    /// origin, and fully visible.
    ///
    /// ⚠️ **Opaque, not transparent.** An export predating D266 names no chain
    /// at all, and starting those draws at zero alpha would render every effect
    /// in it as an empty frame.
    pub(super) fn unknown() -> Self {
        Self {
            world: IDENTITY,
            alpha: OPAQUE,
        }
    }
}

/// A node's own transform at `frame`, as a 3x4 row-major matrix, and its alpha.
///
/// ⚠️ Rotates **z, then y, then x, in degrees** - the order measured against
/// the file's own stored matrices, which agree on 3,738 of 3,739 nodes (D265).
fn local(node: &NodeDef, curves: &[Curve], frame: f32) -> Pose {
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
    Pose {
        world: out,
        alpha: slots[9],
    }
}

/// Fold one node's alpha into the chain's, as the game's walker does.
///
/// ✅ Transcribed from `0x8005f734` (D282), eight bits throughout:
///
/// ```text
/// if own == 0 { 0 } else { (parent * (own + 1)) >> 8 }
/// ```
///
/// ⚠️ **Zero is absorbing, and that is the point.** A node whose own alpha is
/// zero suppresses everything under it -- the game skips the draw *and* the
/// child recursion, while siblings still walk. Because a chain is one root-to-
/// leaf path, folding along it reproduces that: once zero, always zero.
///
/// ⚠️ **The game truncates rather than clamps.** `clrlwi` keeps the low byte,
/// so a curve overshooting 255 wraps to a low alpha instead of saturating.
/// That is the behaviour, not a rounding error to correct here.
fn compose(parent: f32, own: f32) -> f32 {
    let own = (own as i32 as u32) & 0xFF;
    if own == 0 {
        return 0.0;
    }
    let parent = (parent as i32 as u32) & 0xFF;
    (((parent * (own + 1)) >> 8) & 0xFF) as f32
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
///
/// ⚠️ **The alpha comes back folded down the chain**, not taken from the node
/// issuing the draw: each one scales what its parent left, the way `compose`
/// describes (D282). D280 took the last node's, which is what a chain of
/// opaque parents reduces to and is why the difference only shows where a
/// parent is faded.
pub(super) fn posed(chain: &[usize], nodes: &[NodeDef], curves: &[Curve], frame: f32) -> Pose {
    let mut posed = Pose {
        world: IDENTITY,
        alpha: OPAQUE,
    };
    for index in chain {
        if let Some(node) = nodes.get(*index) {
            let step = local(node, curves, frame);
            posed = Pose {
                world: concat(&posed.world, &step.world),
                alpha: compose(posed.alpha, step.alpha),
            };
        }
    }
    posed
}

/// Below which a 2x2 minor counts as zero. The transforms this sees are built
/// from the file's own scales, which are 0 exactly or of order 1.
const DEGENERATE: f32 = 1e-9;

/// Whether a transform leaves nothing with area for the rasteriser to fill.
///
/// ⚠️ **Rank, not determinant.** A singular transform still draws whenever it
/// has a *plane* left to map a triangle onto, and effect geometry is mostly
/// planar already — so a zero determinant says nothing on its own. `map_derkness`
/// scales its ground sheet by `(1.42857, 0, 1.42857)`: volume gone, a 14,000-unit
/// sheet still there, and the determinant test threw the whole thing away
/// (D281). Rank below 2 is a point or a line, which genuinely has no area.
///
/// ⚠️ Not a fault either way: an effect's parts scale up from zero, so a part
/// is legitimately collapsed before it begins.
pub(super) fn flat(m: &[f32; 12]) -> bool {
    for (top, bottom) in [(0usize, 1usize), (0, 2), (1, 2)] {
        for (left, right) in [(0usize, 1usize), (0, 2), (1, 2)] {
            let minor = m[top * 4 + left] * m[bottom * 4 + right]
                - m[top * 4 + right] * m[bottom * 4 + left];
            if minor.abs() > DEGENERATE {
                return false;
            }
        }
    }
    true
}
