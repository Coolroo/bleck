//! What `bleck effect export` wrote: the effect table, each effect's parts,
//! and the transform rows behind them. **This is the data layer** — the panels
//! that draw it are in `app::effects`.
//!
//! ⚠️ The manifest is the contract, not the directory listing — the rule for
//! this whole layer, stated once in `data`'s module doc. Nothing here reads
//! `effdata.dat`; `bleck` owns that format and is tested against a real disc.
//!
//! ✅ **Which image a part draws is decoded** (D258) and arrives in the
//! manifest as `Part::draws`. `bleck` walks the five sections between them;
//! nothing here re-derives it.
//!
//! ✅ **So is the geometry** (D263, D264). A draw names a mesh in the
//! manifest's shared `meshes` table as well as an image, so an effect's real
//! shape is available here rather than a stand-in quad.
//!
//! ⚠️ **Resolve an image by name, not by counting.** `image_at` matches
//! `<source>#<n>`, the name `bleck` writes. `bank` still exists and is still
//! the *whole* bank in catalog order — useful for browsing, and never a
//! mapping. Taking the nth entry of the filtered bank would pair a part with
//! the wrong picture on any export where the catalog is not contiguous.
//!
//! ✅ **The node transforms are applied** (D266). A draw names the chain of
//! nodes above it, `nodes` holds each one's static transform and curve
//! references, and `curves` holds the samples — enough to pose the effect at
//! any frame, which is what the viewer does.
//!
//! ✅ **So are the material's colour register and the node's alpha** (D280).
//! Both were in the manifest and read by nothing; a draw is now multiplied by
//! the first and faded by the second, and one left at zero alpha is not drawn.
//!
//! ✅ **And so are the file's other two curve evaluators** (D281). The same
//! `curves` table drives a node's transform, a material's colour register and a
//! texture's UV transform; `materials` and `samplers` are the two records that
//! name the second and third, and 305 of the file's 4,752 commands belong to
//! them. Without those, 32 effects hold a byte-identical pose for 1,523 frames
//! while their real data moves — a frozen tail that reads as a finished
//! animation (D278).
//!
//! ✅ **And blend mode 0 is derived rather than assumed** (D283). It is 2,528 of
//! the file's 2,960 draws and it is not a mode: `Draw::blend_mode` folds the
//! sampler's alpha type, the descriptor's bit 15 and the frame's own evaluated
//! alpha into one of opaque, cut-out or alpha blend. ⛔ **It cannot be resolved
//! at load** — the alpha moves as an instance fades, and 341 draws change mode
//! when it does.

use serde::Deserialize;
use std::path::{Path, PathBuf};

use super::catalog;
use super::mesh::Modulate;
use super::texture::{Sampling, Transform, Wrap};

/// The file `bleck effect export` writes.
const MANIFEST: &str = "effects.json";

/// The rate the game counts animation frames at, and so the rate that turns a
/// part's frame count into the seconds shown beside it.
const FRAME_RATE: f32 = 60.0;

#[derive(Debug, Deserialize)]
struct Manifest {
    /// The disc file holding the effect system's images.
    #[serde(default)]
    textures: String,
    /// Every distinct display list, shared by index across all the draws.
    ///
    /// ⚠️ 2,960 draws share 360 meshes, which is why they are a table here
    /// rather than a field on each draw.
    #[serde(default)]
    meshes: Vec<Mesh>,
    /// The scene graph and the curves that animate it.
    #[serde(default)]
    nodes: Vec<NodeDef>,
    #[serde(default)]
    curves: Vec<Curve>,
    /// Every colour register, shared by index across the draws (D281).
    #[serde(default)]
    materials: Vec<MaterialDef>,
    /// Every texture record — wrap, UV transform and curve run (D281).
    #[serde(default)]
    samplers: Vec<SamplerDef>,
    effects: Vec<Entry>,
}

/// One section 5 material: a colour register, and the curves driving it.
///
/// ⚠️ **Read as `Option`, exactly as `Draw`'s inline copy is.** An export
/// predating this table has none, and `#[serde(default)]` on a plain `u8` would
/// make every material read as alpha 0 — every effect in that export invisible
/// (D280). Absent means "multiply by one".
#[derive(Debug, Deserialize, Clone, Default)]
pub struct MaterialDef {
    #[serde(default)]
    pub rgba: Vec<u8>,
    /// `[tag, curve]` pairs. Tags 0..3 are R, G, B, A.
    #[serde(default)]
    pub curves: Vec<[usize; 2]>,
}

impl MaterialDef {
    /// This material's colour register at `frame`.
    ///
    /// ✅ **The static register first, then a curve over the top** — the order
    /// the game's own evaluator at `0x8005c634` uses: it stores the four bytes
    /// into a slot array before the loop and a curve overwrites one of them by
    /// tag. A material with only a red curve keeps its own green, blue and
    /// alpha, so this composes with the register rather than replacing it.
    pub fn at(&self, curves: &[Curve], frame: f32) -> Modulate {
        let pick = |at: usize| self.rgba.get(at).copied().unwrap_or(255);
        let mut slots = [pick(0), pick(1), pick(2), pick(3)];
        for [slot, curve] in &self.curves {
            if let Some(value) = curves.get(*curve).and_then(|c| c.value_at(frame)) {
                if let Some(cell) = slots.get_mut(*slot) {
                    // `fctiwz` then `stbx`: truncated toward zero, low byte kept.
                    *cell = (value as i32).rem_euclid(256) as u8;
                }
            }
        }
        Modulate {
            red: slots[0],
            green: slots[1],
            blue: slots[2],
            alpha: slots[3],
        }
    }
}

/// One section 4 texture record: how the image wraps, and the UV transform
/// applied to every coordinate that samples it (D281).
///
/// ⚠️ **`scale` absent must read as 1, not 0.** An export predating this table
/// carries no scale at all, and a zero one collapses every texture coordinate
/// onto a single texel — the same failure mode as D280's alpha, in the other
/// direction.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct SamplerDef {
    /// The `effdata.tpl` index this record names.
    ///
    /// ⚠️ **Not what a draw paints with** — `Draw::image` is, and it is reached
    /// by the same walk. Kept so the two hops can be checked against each
    /// other: they are read from different sections and must agree, and only
    /// the corpus test asks.
    #[serde(default)]
    #[allow(dead_code)]
    pub image: Option<i32>,
    /// GX's own wrap enum per axis: 0 clamp, 1 repeat, 2 mirror. `bleck`
    /// decodes the file's two-bits-per-axis byte, so nothing here re-derives it.
    #[serde(default)]
    pub wrap_s: Option<u32>,
    #[serde(default)]
    pub wrap_t: Option<u32>,
    /// Two entries: U and V.
    #[serde(default)]
    pub translate: Vec<f32>,
    #[serde(default)]
    pub scale: Vec<f32>,
    /// Degrees. 19 records hold +90 and 7 hold -90 (D278).
    #[serde(default)]
    pub rotation: Option<f32>,
    /// What this record declares about its image's alpha: 0 opaque, 1 cut-out,
    /// 2 translucent — bits 2-3 of the file's `+0x03` byte (D283).
    ///
    /// ⚠️ **`None` is "this export did not record one", and must keep the plain
    /// alpha every reader used before.** Reading absent as 0 would turn 2,528
    /// draws of every schema-4 export opaque at a stroke — the same trap D280's
    /// node alpha and D281's UV scale each hit from the other direction.
    ///
    /// ⛔ **Not a blend mode.** It is one of three inputs; `Draw::blend_mode`
    /// folds it with the descriptor bit and the evaluated alpha.
    #[serde(default)]
    pub alpha_type: Option<u32>,
    /// `[tag, curve]` pairs. 0, 1 translate; 2, 3 scale; 4 rotation.
    #[serde(default)]
    pub curves: Vec<[usize; 2]>,
}

/// The point a UV rotation turns about, which the game's matrix brackets the
/// rotation with a translate either side of.
const UV_CENTRE: f32 = 0.5;

impl SamplerDef {
    /// The five UV scalars at `frame`, its own curves written over the top.
    fn slots_at(&self, curves: &[Curve], frame: f32) -> [f32; 5] {
        let pick = |v: &Vec<f32>, at: usize, fallback: f32| v.get(at).copied().unwrap_or(fallback);
        let mut slots = [
            pick(&self.translate, 0, 0.0),
            pick(&self.translate, 1, 0.0),
            pick(&self.scale, 0, 1.0),
            pick(&self.scale, 1, 1.0),
            self.rotation.unwrap_or(0.0),
        ];
        for [slot, curve] in &self.curves {
            if let Some(value) = curves.get(*curve).and_then(|c| c.value_at(frame)) {
                if let Some(cell) = slots.get_mut(*slot) {
                    *cell = value;
                }
            }
        }
        slots
    }

    /// How a coordinate is folded and transformed at `frame`.
    ///
    /// ✅ **The game's own matrix, rearranged into the one the sampler already
    /// applies.** It builds `R · T · S` — scale, then translate, then rotate
    /// about (0.5, 0.5) — where the translate's V component is `1 - tv - sv`
    /// rather than `tv`. `Transform` is scale, then rotate, then offset, which
    /// is the same family: the linear halves are identical and the offset
    /// absorbs the rest.
    ///
    /// ⚠️ **`1 - tv - sv`, not `+tv`.** With the usual `sv == 1` that is `-tv`,
    /// so reading it the obvious way runs every scrolling texture backwards.
    pub fn at(&self, curves: &[Curve], frame: f32) -> Sampling {
        let slots = self.slots_at(curves, frame);
        let radians = slots[4].to_radians();
        let (sin, cos) = radians.sin_cos();
        // The game skips its translate block outright when all three of these
        // are zero, so a degenerate `sv` of 0 leaves no offset behind.
        let shift = if slots[0] == 0.0 && slots[1] == 0.0 && slots[3] == 0.0 {
            [0.0, 0.0]
        } else {
            [slots[0], 1.0 - slots[1] - slots[3]]
        };
        let turn = |x: f32, y: f32| [cos * x + sin * y, -sin * x + cos * y];
        let moved = turn(shift[0], shift[1]);
        let centre = turn(UV_CENTRE, UV_CENTRE);
        Sampling {
            wrap_s: wrap_of(self.wrap_s),
            wrap_t: wrap_of(self.wrap_t),
            transform: Transform {
                offset: [
                    moved[0] + UV_CENTRE - centre[0],
                    moved[1] + UV_CENTRE - centre[1],
                ],
                rotation: radians,
                scale: [slots[2], slots[3]],
            },
        }
    }
}

/// GX's wrap enum as the exporter writes it.
///
/// ⚠️ **Repeat is the fallback, and it has to be.** An export carrying no wrap
/// field is what every reader saw before this landed, and clamping those would
/// change how 266 of the file's 350 records sample.
fn wrap_of(mode: Option<u32>) -> Wrap {
    match mode {
        Some(0) => Wrap::Clamp,
        Some(2) => Wrap::Mirror,
        _ => Wrap::Repeat,
    }
}

/// One node of an effect's scene graph, as `bleck` read it (D265, D266).
///
/// ⚠️ **The static values are a starting point, not the pose.** A curve
/// overwrites individual slots, and 44% of drawing nodes are flat until one
/// does.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct NodeDef {
    #[serde(default)]
    pub t: Vec<f32>,
    #[serde(default)]
    pub r: Vec<f32>,
    #[serde(default)]
    pub s: Vec<f32>,
    #[serde(default)]
    pub alpha: f32,
    /// `[slot, curve]` pairs. Slot 0..2 is translate, 3..5 rotate, 6..8 scale,
    /// 9 alpha - the game's own order, read off the array it fills.
    #[serde(default)]
    pub curves: Vec<[usize; 2]>,
}

/// One sampled curve, one value per frame (D266).
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Curve {
    #[serde(default)]
    pub length: i64,
    #[serde(default)]
    pub start: i64,
    #[serde(default)]
    pub end: i64,
    #[serde(default, rename = "loop")]
    pub looping: i64,
    #[serde(default)]
    pub samples: Vec<f32>,
}

impl Curve {
    /// This curve at `frame`, or `None` when it has nothing to say yet.
    ///
    /// ⚠️ **`None` is not zero.** A curve that has not started leaves the
    /// node's own static value alone; substituting zero would collapse every
    /// scale still waiting to begin. Transcribed from the game's evaluator.
    pub fn value_at(&self, frame: f32) -> Option<f32> {
        if self.length <= 0 {
            return None;
        }
        let length = self.length as f32;
        let mut time = frame;
        if self.looping != 0 {
            // ⚠️ The game adds `length << 6`, not `length`.
            while time < 0.0 {
                time += (self.length << 6) as f32;
            }
            time = (time as i64).rem_euclid(self.length) as f32;
        } else {
            if frame < 0.0 {
                time = 0.0;
            }
            if time >= length {
                time = length - 1.0;
            }
        }
        if time < self.start as f32 {
            return None;
        }
        if time > self.end as f32 {
            time = self.end as f32;
        }
        let at = (time - self.start as f32) as usize;
        self.samples.get(at).copied()
    }
}

/// One effect, as `bleck` described it.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Entry {
    /// The effect's own name, which is what the game's code calls it by.
    pub name: String,
    /// Position in the effect table.
    #[serde(default)]
    pub index: usize,
    /// How long the whole effect runs — the longest of its parts.
    #[serde(default)]
    pub seconds: f32,
    #[serde(default)]
    pub parts: Vec<Part>,
}

impl Entry {
    /// The two numbers that decide whether an effect is worth opening.
    pub fn describe(&self) -> String {
        format!("{} part(s) · {:.2}s", self.parts.len(), self.seconds)
    }

    /// What a copy puts on the clipboard: the name the game's own code calls
    /// this effect by, which is what someone reading that code has to search
    /// for. Not the table position, which is meaningless on its own.
    pub fn copy_text(&self) -> String {
        self.name.clone()
    }

    /// Total frames, derived from the duration rather than read: the export
    /// records seconds per effect and frames only per part.
    pub fn frames(&self) -> u32 {
        frame_at(self.seconds)
    }

    /// The parts still running `time` seconds in, as indices into `parts`.
    pub fn active_at(&self, time: f32) -> Vec<usize> {
        self.parts
            .iter()
            .enumerate()
            .filter(|(_, part)| part.active_at(time))
            .map(|(index, _)| index)
            .collect()
    }
}

/// One part of an effect: a named sub-animation with its own duration.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Part {
    /// The suffix the game composes onto the effect's name — `A`, `B`, and so on.
    pub name: String,
    /// Effect name and part name joined, which is the name the game looks up.
    #[serde(default)]
    pub composed: String,
    /// Position in the part table, running across the whole file.
    #[serde(default)]
    pub index: usize,
    /// Duration in frames, counted inclusively at 60 Hz: 61 frames is one
    /// second, and a 1-frame part lasts zero.
    #[serde(default)]
    pub frames: u32,
    #[serde(default)]
    pub seconds: f32,
    /// The draws this part issues, as `bleck` resolved them (D258, D263).
    ///
    /// ⚠️ **A list, because a part draws a set.** 560 of the file's 704 parts
    /// reach one image, 35 none, and the rest up to twelve. An export written
    /// before the binding was decoded carries none, and `serde(default)` leaves
    /// it empty rather than refusing to load.
    #[serde(default)]
    pub draws: Vec<Draw>,
}

/// One draw a part issues: geometry, and what to paint it with.
///
/// ⚠️ **A draw always names a mesh and may name no image.** The two are
/// separate hops of the same chain — a material carrying the documented `-1`
/// still has geometry to draw, so an untextured draw is a real thing rather
/// than a failed lookup.
#[derive(Debug, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct Draw {
    /// Index into the manifest's shared `meshes` table.
    #[serde(default)]
    pub mesh: usize,
    /// Every node from the part's root down to the one issuing this draw.
    ///
    /// ✅ What lets the viewer pose the draw at an arbitrary time: each node is
    /// evaluated at that frame and the results multiplied, parent first.
    #[serde(default)]
    pub chain: Vec<usize>,
    /// How this draw is composited: 0 derive, 4 additive, 5 subtractive,
    /// 6 inverse-source (D270).
    ///
    /// ⚠️ **0 is not a mode; it is a request to derive one** (D283), and it is
    /// 2,528 of the file's 2,960 draws. `blend_mode` runs the derivation, which
    /// needs the frame's evaluated alpha and so cannot be done once at load.
    #[serde(default)]
    pub blend: u32,
    /// Bit 15 of the draw's vertex descriptor, which asks outright for alpha
    /// blending (D283). 211 of the file's 2,960 draws set it.
    ///
    /// ⚠️ **Absent reads as false, and that is the safe direction**: an export
    /// predating the field then derives from the sampler and the alpha alone,
    /// which is what it would have done had the bit never been set.
    #[serde(default)]
    pub translucent: bool,
    /// Index into the effect system's own bank — 0..218 for `effdata.tpl` —
    /// or negative where the material names no texture.
    ///
    /// ⚠️ Signed on purpose. 0 is a real image, so it cannot double as "none".
    #[serde(default)]
    pub image: i32,
    #[serde(default)]
    pub wrap: u32,
    /// The material's own colour register, channel by channel.
    ///
    /// ⚠️ **`None` is "this export did not record one", not black.** An export
    /// predating the field would otherwise read as a material that multiplies
    /// every texel by zero, and every effect in it would render as nothing —
    /// which is why these are optional where `mesh` and `blend` are not.
    #[serde(default)]
    pub red: Option<u8>,
    #[serde(default)]
    pub green: Option<u8>,
    #[serde(default)]
    pub blue: Option<u8>,
    #[serde(default)]
    pub alpha: Option<u8>,
    /// Index into the manifest's shared `materials` table, or negative where
    /// the draw's material is out of range.
    ///
    /// ⚠️ **What reaches the colour *curves*.** The four channels above are the
    /// register's static value; 97 of the file's 524 materials animate it, and
    /// only this reference finds them. Absent on an export predating the table,
    /// which then falls back to the static four.
    #[serde(default)]
    pub material: Option<i32>,
    /// Index into the manifest's shared `samplers` table, or negative where the
    /// material names no texture.
    #[serde(default)]
    pub sampler: Option<i32>,
}

/// The selector that names no mode and asks for one to be worked out (D283).
pub const BLEND_DERIVED: u32 = 0;

/// The three modes the derivation can reach. ⛔ **Additive is not among them**:
/// selector 0 can only ever come out 1, 2 or 3, so a glow is always declared.
pub const BLEND_OPAQUE: u32 = 1;
pub const BLEND_CUTOUT: u32 = 2;
pub const BLEND_TRANSLUCENT: u32 = 3;

/// What a sampler's `alpha_type` says about its image.
const ALPHA_CUTOUT: u32 = 1;
const ALPHA_TRANSLUCENT: u32 = 2;

impl Draw {
    /// The bank index this draw paints with, or `None` when it paints none.
    pub fn image(&self) -> Option<usize> {
        (self.image >= 0).then_some(self.image as usize)
    }

    /// Which of the game's six blend modes composites this draw, given the
    /// alpha its material and node have already composed to at this frame.
    ///
    /// ✅ **Transcribed from `0x8005c870`-`0x8005c9f8`** (D283). A declared
    /// selector is returned untouched; selector 0 seeds an accumulator at zero,
    /// folds in the sampler's alpha type, and three things set the bit that
    /// forces alpha blending — an alpha type of 2, the descriptor's bit 15, and
    /// an evaluated alpha **strictly** between 0 and 255. Otherwise the mode is
    /// `(accumulator & 1) + 1`.
    ///
    /// ⚠️ **A function of the frame, not of the file.** The alpha it reads is
    /// the one the fade moves, so 341 draws change mode the instant an instance
    /// fades — which is why the export carries these inputs and no mode.
    ///
    /// ⚠️ **An export with no `alpha_type` keeps plain alpha.** That is what
    /// every reader before this did for all 2,528 of them, and it is also what
    /// a draw whose material names no texture gets — such a draw paints no
    /// image, so nothing composites it either way.
    pub fn blend_mode(&self, samplers: &[SamplerDef], alpha: u8) -> u32 {
        if self.blend != BLEND_DERIVED {
            return self.blend;
        }
        let Some(kind) = self
            .sampler()
            .and_then(|at| samplers.get(at))
            .and_then(|row| row.alpha_type)
        else {
            return BLEND_TRANSLUCENT;
        };
        if kind == ALPHA_TRANSLUCENT || self.translucent || (0 < alpha && alpha < 255) {
            return BLEND_TRANSLUCENT;
        }
        // ⛔ Matched rather than `kind + 1`: an alpha type of 3 — which no
        // record carries — would otherwise arrive as 4, additive, out of a
        // derivation that provably cannot produce it.
        match kind {
            ALPHA_CUTOUT => BLEND_CUTOUT,
            _ => BLEND_OPAQUE,
        }
    }

    /// This draw's row of the shared `materials` table, or `None`.
    pub fn material(&self) -> Option<usize> {
        self.material.filter(|&at| at >= 0).map(|at| at as usize)
    }

    /// This draw's row of the shared `samplers` table, or `None`.
    pub fn sampler(&self) -> Option<usize> {
        self.sampler.filter(|&at| at >= 0).map(|at| at as usize)
    }

    /// The material's colour register: what every texel of this draw is
    /// multiplied by before anything else touches it.
    ///
    /// ✅ Measured on the real export: 1,445 of 2,960 draws are white and
    /// opaque, 21 carry a black register, and 1,163 an alpha strictly between
    /// 0 and 255 (D280). An export that records none multiplies by one.
    pub fn tint(&self) -> Modulate {
        Modulate {
            red: self.red.unwrap_or(255),
            green: self.green.unwrap_or(255),
            blue: self.blue.unwrap_or(255),
            alpha: self.alpha.unwrap_or(255),
        }
    }
}

/// One display list, as indexed triangles (D263).
///
/// ⚠️ **Positions are the file's own `s16` units, unscaled.** Dimentio's star
/// spans ±320. What one unit is in the game's world is not established, so a
/// caller fits a camera to the bounds rather than assuming a scale.
///
/// ⚠️ `uvs`, `colours` and `normals` are **absent** where the display list's
/// descriptor does not name them, which is most of the file. A reader must
/// treat a short or empty array as "this geometry has none", not as an error.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Mesh {
    /// Where the display list sits in section 3 of `effdata.dat`. ⚠️ Kept
    /// because it is how a finding names one — D263's star is "the display list
    /// at 0x001C80" — and nothing else here identifies a mesh to a reader.
    #[serde(default)]
    #[allow(dead_code)]
    pub offset: u32,
    /// The GX vertex descriptor the list was read under. ⚠️ Part of a mesh's
    /// identity, not decoration: the same bytes under a different descriptor
    /// are different geometry.
    #[serde(default)]
    #[allow(dead_code)]
    pub descriptor: u32,
    /// Three per vertex.
    #[serde(default)]
    pub positions: Vec<i32>,
    /// Two per vertex, when present.
    #[serde(default)]
    pub uvs: Vec<f32>,
    /// Four per vertex, when present.
    #[serde(default)]
    pub colours: Vec<u8>,
    /// Three per vertex, when present.
    ///
    /// ⚠️ Read from the manifest and **not yet drawn with**: the rasteriser
    /// lights a face from its own winding, so a per-vertex normal has nowhere
    /// to go until it shades smoothly.
    #[serde(default)]
    #[allow(dead_code)]
    pub normals: Vec<f32>,
    /// Three per triangle, indexing the arrays above.
    #[serde(default)]
    pub triangles: Vec<usize>,
}

impl Mesh {
    pub fn vertices(&self) -> usize {
        self.positions.len() / 3
    }

    pub fn faces(&self) -> usize {
        self.triangles.len() / 3
    }

    /// Whether every index is inside the arrays it addresses.
    ///
    /// ⚠️ Checked rather than trusted: a manifest is a file on disk, and a
    /// stray index would panic the rasteriser rather than draw wrongly.
    pub fn is_sound(&self) -> bool {
        self.triangles.len() % 3 == 0
            && self.positions.len() % 3 == 0
            && self.triangles.iter().all(|&at| at < self.vertices())
            && (self.uvs.is_empty() || self.uvs.len() == self.vertices() * 2)
            && (self.colours.is_empty() || self.colours.len() == self.vertices() * 4)
    }
}

impl Part {
    /// Whether this part is still running `time` seconds into the effect.
    ///
    /// ⚠️ The end is inclusive because the frame count is. `seconds` names the
    /// part's last frame, not the frame after it, so an exclusive end would
    /// make every 1-frame part — of which the export holds many — never active
    /// at all, and a part would stop one frame early.
    pub fn active_at(&self, time: f32) -> bool {
        (0.0..=self.seconds).contains(&time)
    }

    pub fn describe(&self) -> String {
        format!("{} frames · {:.2}s", self.frames, self.seconds)
    }

    /// What a copy puts on the clipboard.
    ///
    /// ⚠️ The composed name, not the suffix. `name` is `A` or `C` on its own
    /// and names nothing outside the effect it belongs to; `composed` is what
    /// the game looks a part up by. An export that recorded no composed name
    /// falls back to the suffix, which is all there is.
    pub fn copy_text(&self) -> String {
        if self.composed.is_empty() {
            self.name.clone()
        } else {
            self.composed.clone()
        }
    }
}

/// The frame number `time` seconds in, counting the first frame as 1 — the
/// same inclusive convention the durations use.
pub fn frame_at(time: f32) -> u32 {
    (time.max(0.0) * FRAME_RATE).round() as u32 + 1
}

/// The timeline an effect scrubs along. Shared with the model viewport, which
/// plays a morph clip the same way; it lives in `transport`.
pub use super::transport::Playback;

/// Indices of the images that make up the effect system's bank.
///
/// ⚠️ This is the whole bank in catalog order, for **browsing**, and the order
/// carries no meaning beyond that. Do not index the result by a part's index,
/// frame count or table position — every one of those was tried and refuted
/// (D210), and a part's real image is reached by name through `image_at`
/// instead (D258). A wrong pairing shown in a window looks exactly like a
/// right one, and that risk did not go away when the right one was found.
///
/// An export that names no bank selects nothing, rather than every image whose
/// source happens to be blank.
pub fn bank(entries: &[catalog::Entry], source: &str) -> Vec<usize> {
    if source.is_empty() {
        return Vec::new();
    }
    entries
        .iter()
        .enumerate()
        .filter(|(_, entry)| entry.source == source)
        .map(|(index, _)| index)
        .collect()
}

/// The catalog position of image `image` of the effect bank, or `None`.
///
/// ⚠️ Matched by the **name `bleck` writes** — `<source>#<n>` — rather than by
/// counting into `bank()`. The catalog's order is the manifest's order, and
/// nothing guarantees the effect bank's images sit in it contiguously or in
/// index order; taking the nth entry of the filtered list would silently pair
/// a part with the wrong picture on any export where they do not.
pub fn image_at(entries: &[catalog::Entry], source: &str, image: usize) -> Option<usize> {
    if source.is_empty() {
        return None;
    }
    let wanted = format!("{source}#{image}");
    entries.iter().position(|entry| entry.name == wanted)
}

/// Why a folder produced no effects, so the window can say which.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Problem {
    NoManifest(PathBuf),
    Unreadable(String),
}

impl Problem {
    pub fn describe(&self) -> String {
        match self {
            // ⚠️ Names the file it wanted. "Nothing here" sends someone
            // looking in the wrong place.
            Self::NoManifest(path) => format!(
                "No {MANIFEST} in {}.\nRun: bleck effect export --out {}",
                path.display(),
                path.display()
            ),
            Self::Unreadable(why) => format!("{MANIFEST} could not be read:\n{why}"),
        }
    }
}

/// Every effect the export folder declares, and the disc file its images
/// come from.
#[derive(Default)]
pub struct Library {
    entries: Vec<Entry>,
    meshes: Vec<Mesh>,
    nodes: Vec<NodeDef>,
    curves: Vec<Curve>,
    materials: Vec<MaterialDef>,
    samplers: Vec<SamplerDef>,
    textures: String,
    problem: Option<Problem>,
}

impl Library {
    /// Read the manifest in `root`.
    ///
    /// A failure is recorded rather than returned, for the same reason as
    /// `Catalog::load`: the window is already open and needs to be told what
    /// to do about it, which `Problem` carries and a `Result` would not.
    pub fn load(root: &Path) -> Self {
        let text = match std::fs::read_to_string(root.join(MANIFEST)) {
            Ok(text) => text,
            Err(_) => {
                return Self {
                    problem: Some(Problem::NoManifest(root.to_path_buf())),
                    ..Default::default()
                }
            }
        };
        let manifest: Manifest = match serde_json::from_str(&text) {
            Ok(manifest) => manifest,
            Err(why) => {
                return Self {
                    problem: Some(Problem::Unreadable(why.to_string())),
                    ..Default::default()
                }
            }
        };
        Self {
            entries: manifest.effects,
            meshes: manifest.meshes,
            nodes: manifest.nodes,
            curves: manifest.curves,
            materials: manifest.materials,
            samplers: manifest.samplers,
            textures: manifest.textures,
            problem: None,
        }
    }

    pub fn entries(&self) -> &[Entry] {
        &self.entries
    }

    /// The shared display-list table. Empty for an export written before the
    /// geometry was decoded, which is what `Draw::mesh` degrades against.
    pub fn meshes(&self) -> &[Mesh] {
        &self.meshes
    }

    pub fn nodes(&self) -> &[NodeDef] {
        &self.nodes
    }

    pub fn curves(&self) -> &[Curve] {
        &self.curves
    }

    /// The shared colour registers. Empty for an export predating D281, which
    /// `Draw`'s own inline channels degrade against.
    pub fn materials(&self) -> &[MaterialDef] {
        &self.materials
    }

    /// The shared texture records. Empty for an export predating D281, which
    /// leaves every draw sampled repeat/repeat with no UV transform.
    pub fn samplers(&self) -> &[SamplerDef] {
        &self.samplers
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Paired with `len` because clippy asks for it; the UI branches on
    /// `problem()` and the match count instead, so only the tests call this.
    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// The disc file the effect system's images live in, as the exporter
    /// recorded it. Empty when the manifest did not say.
    pub fn textures(&self) -> &str {
        &self.textures
    }

    pub fn problem(&self) -> Option<&Problem> {
        self.problem.as_ref()
    }

    /// Indices matching a search, in manifest order. Part names are searched
    /// as well as effect names, because the composed name is what appears in
    /// the game's own code and is often the only name someone has.
    pub fn matching(&self, search: &str) -> Vec<usize> {
        let needle = search.to_lowercase();
        self.entries
            .iter()
            .enumerate()
            .filter(|(_, entry)| {
                needle.is_empty()
                    || entry.name.to_lowercase().contains(&needle)
                    || entry
                        .parts
                        .iter()
                        .any(|part| part.composed.to_lowercase().contains(&needle))
            })
            .map(|(index, _)| index)
            .collect()
    }
}

#[cfg(test)]
mod tests;
