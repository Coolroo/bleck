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
//! ✅ **And the placement is measured too**, since D266. A draw carries the
//! chain of nodes above it; each is posed at the frame — static translate,
//! rotate and scale, with any curve of its own written over the top — and the
//! results multiplied parent-first. That is the game's own scheme, transcribed
//! from the evaluator at `0x8005f2d4`.
//!
//! ✅ **And so is how visible each draw is**, since D280: the material's own
//! colour register multiplies every texel, and the drawing node's alpha at that
//! frame multiplies its opacity. ⛔ **A draw those two leave at zero alpha is
//! not issued at all** — drawn, it would be a solid sprite where the data says
//! there is nothing, which is the most convincing wrong picture available.
//!
//! ✅ **And both of those move over time**, since D281. The file drives three
//! things from one curve table, not one: a node's transform, a material's
//! colour register, and a texture's UV transform. `shading` and `sampling`
//! evaluate the second and third at the same frame the pose is taken at.
//! ⚠️ Without them 32 effects hold a byte-identical pose for 1,523 frames while
//! their colour and UV data moves — which reads as a finished animation rather
//! than as a bug, so nobody reports it (D278).
//!
//! ⚠️ **A flat part is not a missing part.** An effect's scales rise from zero,
//! so 44% of draws collapse to nothing at frame 0 and are skipped. The exploded
//! layout survives only for a draw with **no** geometry, where there is no
//! measured position to use instead.
//!
//! The matrix arithmetic that poses a node chain is `pose`, which takes nodes
//! and curves as arguments and knows nothing of effects, parts or the camera.

use super::camera::Basis;
use super::{Camera, Rgba};
use crate::data::effects::{
    self as effects, Curve, Draw, Entry, MaterialDef, Mesh as Geometry, NodeDef, SamplerDef,
};
use crate::data::mesh::{Blend, Bounds, Face, Mesh, Modulate, Paint, Parts, Shape, Uv, Vec3};
use crate::data::texture::{Sampling, Texture};
use pose::{apply, flat, posed, Pose, FRAME_RATE};

mod pose;

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
#[derive(Debug, Clone, Copy, Default)]
pub struct Art<'a> {
    pub images: &'a [Vec<Option<Texture>>],
    /// The manifest's shared display-list table, indexed by `Draw::mesh`.
    /// Empty for an export predating the geometry, which falls back.
    pub meshes: &'a [Geometry],
    /// The scene graph, and the curves that pose it. Empty for an export
    /// predating D266, in which case every part stacks at the origin.
    pub nodes: &'a [NodeDef],
    pub curves: &'a [Curve],
    /// The colour registers and the texture records, indexed by
    /// `Draw::material` and `Draw::sampler`. Empty for an export predating
    /// D281, which then keeps the draw's own static channels and samples
    /// repeat/repeat with no UV transform.
    pub materials: &'a [MaterialDef],
    pub samplers: &'a [SamplerDef],
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

/// What a part issued at one instant, and what it did not.
///
/// ⚠️ **The two travel together on purpose.** A draw removed for having no
/// alpha left is invisible in the pieces by definition, and a caller counting
/// only pieces cannot tell it from a draw that was never declared — which is
/// how "nothing was drawn" came to be reported as "re-run the export" (D280).
pub struct Drawn {
    pub pieces: Vec<Quad>,
    /// Draws left out because the node's alpha and the material's composed to
    /// zero.
    pub faded: usize,
}

/// Everything about painting one draw that is not the image or the geometry.
///
/// ⚠️ **Travelling together because every one is a function of the frame.** The
/// colour register and the UV transform are sampled from the shared curve table
/// (D281), and since D283 the blend mode and the alpha compare are derived from
/// the alpha those produce — so passing them separately down four call sites is
/// how one of them comes to be evaluated at the wrong time.
#[derive(Debug, Clone, Copy, Default)]
struct Surface {
    blend: Blend,
    /// Whether a texel below `cutoff` is discarded — the game's alpha compare.
    masked: bool,
    cutoff: u8,
    modulate: Modulate,
    sampling: Sampling,
}

impl Surface {
    /// The blend state and alpha compare one of the game's six modes asks for.
    ///
    /// ✅ **One table for the derived modes and the declared ones**, because the
    /// game runs both through the same switch at `0x8005c9f8` — the derivation
    /// produces a number and the switch reads it (D270, D283).
    ///
    /// ⚠️ **Modes 1 and 2 write depth and mode 3 does not**, which is the whole
    /// reason the mode has to reach here rather than being folded into a colour:
    /// a cut-out sprite occludes what is behind it and a blended one must not.
    /// The rasteriser writes depth for `Blend::Opaque` alone, so both of the
    /// non-blending modes carry it and differ only in their compare.
    fn painted(mode: u32, modulate: Modulate, sampling: Sampling) -> Self {
        let (blend, masked, cutoff) = match mode {
            // Alpha compare always passes: the black surround of an opaque
            // draw is painted, which is what the game does (D283).
            effects::BLEND_OPAQUE => (Blend::Opaque, false, 0),
            effects::BLEND_CUTOUT => (Blend::Opaque, true, super::MASK_CUTOFF),
            4 => (Blend::Add, true, super::FAINT_CUTOFF),
            5 => (Blend::Subtract, true, super::FAINT_CUTOFF),
            6 => (Blend::Inverse, true, super::FAINT_CUTOFF),
            // ⚠️ Mode 3 and the fallback are one arm on purpose: plain alpha is
            // what an unrecognised selector must keep doing, and what every
            // reader before D283 did with all 2,528 derived draws.
            _ => (Blend::Alpha, true, super::FAINT_CUTOFF),
        };
        Self {
            blend,
            masked,
            cutoff,
            modulate,
            sampling,
        }
    }
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
    let mesh = quad(
        &basis,
        Vec3::ZERO,
        HALF,
        None,
        Surface::painted(
            effects::BLEND_TRANSLUCENT,
            Modulate::default(),
            Sampling::default(),
        ),
    );
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
pub fn quads(entry: &Entry, time: f32, camera: &Camera, art: Option<Art<'_>>) -> Drawn {
    let basis = Basis::of(camera);
    let scale = spread(entry, art);
    let frame = time * FRAME_RATE;
    let mut built = Vec::new();
    let mut faded = 0;
    for part in entry.active_at(time) {
        let count = entry.parts.get(part).map_or(0, |p| p.draws.len());
        for draw in 0..count.max(1) {
            // Cloned because a mesh owns its texture; only the parts actually
            // running at this instant ever pay for it.
            let image = art.and_then(|art| art.of(part, draw));
            let named = entry.parts.get(part).and_then(|p| p.draws.get(draw));
            let shape = art.zip(named).and_then(|(art, d)| art.geometry(d.mesh));
            let pose = match (art, named) {
                (Some(art), Some(named)) => posed(&named.chain, art.nodes, art.curves, frame),
                _ => Pose::unknown(),
            };
            // ⚠️ A flat part is not a fault — an effect's parts scale up from
            // zero, so this one has not begun. Drawing it would push degenerate
            // triangles at the rasteriser for nothing.
            if shape.is_some() && flat(&pose.world) {
                continue;
            }
            let modulate = shading(named, &pose, art, frame);
            // ⛔ **Not drawn at all, rather than drawn and blended away.** A
            // draw whose node and material together leave no alpha contributes
            // nothing to the frame, and painting it solid is the most
            // convincing wrong picture there is (D280).
            if modulate.invisible() {
                faded += 1;
                continue;
            }
            // ✅ The game's own blend mode (D270), with selector 0's derivation
            // run at the alpha this frame composed to (D283) — which is why it
            // is taken here rather than once when the manifest was loaded.
            let how = Surface::painted(
                mode_of(named, art, modulate.alpha),
                modulate,
                sampling(named, art, frame),
            );
            built.push(Quad {
                mesh: match shape {
                    Some(geometry) => real(geometry, &pose.world, image, how),
                    // ⛔ No geometry means no measured position either, so the
                    // stand-in keeps the exploded layout rather than pretending
                    // the origin is where it belongs.
                    None => quad(
                        &basis,
                        placement(entry, part, scale),
                        scale * HALF,
                        image,
                        how,
                    ),
                },
                colour: colour(part),
                part,
                stood_in: shape.is_none(),
            });
        }
    }
    Drawn {
        pieces: built,
        faded,
    }
}

/// What a draw's texels are multiplied by: the material's colour register at
/// this frame, with the drawing node's alpha folded into its alpha channel.
///
/// ⚠️ **Only the alpha is composed.** The node carries no colour of its own, so
/// the RGB is the material's alone.
///
/// ✅ **A colour curve overrides one channel of the register, not all four**
/// (D281) — the game fills a four-byte slot array from the register before its
/// curve loop runs. A material with a red curve alone keeps its own green, blue
/// and alpha, which is why this composes with D280's static read rather than
/// replacing it. An export with no `materials` table falls back to that read.
fn shading(named: Option<&Draw>, pose: &Pose, art: Option<Art<'_>>, frame: f32) -> Modulate {
    let material =
        animated(named, art, frame).unwrap_or_else(|| named.map(Draw::tint).unwrap_or_default());
    Modulate {
        alpha: fade(pose.alpha, material.alpha),
        ..material
    }
}

/// Which of the game's blend modes composites a draw at this frame.
///
/// ⚠️ **Taken at the alpha the frame composed to**, never at the material's own.
/// The game tests the value the instance fade has already scaled (D283), so a
/// draw that is opaque at rest becomes an alpha blend the moment it fades — and
/// evaluating this once at load would pin 341 draws to the wrong mode.
///
/// ⚠️ An export with no art at all keeps every declared selector and derives
/// nothing, which is plain alpha: the same answer it gave before D283.
fn mode_of(named: Option<&Draw>, art: Option<Art<'_>>, alpha: u8) -> u32 {
    let samplers = art.map_or(&[][..], |art| art.samplers);
    named.map_or(effects::BLEND_TRANSLUCENT, |draw| {
        draw.blend_mode(samplers, alpha)
    })
}

/// The colour register at `frame`, or `None` where the manifest holds no row
/// for this draw.
fn animated(named: Option<&Draw>, art: Option<Art<'_>>, frame: f32) -> Option<Modulate> {
    let (art, named) = art.zip(named)?;
    let row = art.materials.get(named.material()?)?;
    Some(row.at(art.curves, frame))
}

/// How a draw's image is folded and transformed at `frame`.
///
/// ⚠️ **Repeat/repeat with no transform is the fallback, not the answer.** It
/// is what every export before D281 was drawn with, so a manifest that names no
/// sampler must keep sampling the way it always did rather than clamping.
fn sampling(named: Option<&Draw>, art: Option<Art<'_>>, frame: f32) -> Sampling {
    let Some((art, named)) = art.zip(named) else {
        return Sampling::default();
    };
    named
        .sampler()
        .and_then(|at| art.samplers.get(at))
        .map(|row| row.at(art.curves, frame))
        .unwrap_or_default()
}

/// Two 0..255 opacities as one.
///
/// ⚠️ Clamped as well as scaled: a curve is sampled data and nothing guarantees
/// it stays inside the range the slot is read at.
fn fade(node: f32, material: u8) -> u8 {
    ((node.clamp(0.0, 255.0) * f32::from(material)) / 255.0).round() as u8
}

/// The box the whole layout occupies, running or not.
///
/// Every part counts, not just the ones active now, so a camera fitted to this
/// stays put as parts start and stop instead of jumping each time the timeline
/// crosses a duration.
pub fn bounds(entry: &Entry, art: Option<Art<'_>>) -> Bounds {
    let scale = spread(entry, art);
    let mut span: Option<Bounds> = None;
    // ⚠️ **Sampled across the timeline, not taken at one instant.** An effect's
    // parts scale up from zero and back down, so a camera fitted to frame 0
    // would frame a pose that is often empty — and one fitted per frame would
    // zoom in and out as parts came and went.
    for step in 0..=SAMPLES {
        let time = entry.seconds * step as f32 / SAMPLES as f32;
        let frame = time * FRAME_RATE;
        for part in 0..entry.parts.len().max(1) {
            let draws = entry
                .parts
                .get(part)
                .map(|p| p.draws.as_slice())
                .unwrap_or_default();
            let mut here: Option<Bounds> = None;
            for named in draws {
                let Some(geometry) = art.and_then(|art| art.geometry(named.mesh)) else {
                    continue;
                };
                let pose = match art {
                    Some(art) => posed(&named.chain, art.nodes, art.curves, frame),
                    None => Pose::unknown(),
                };
                if flat(&pose.world) {
                    continue;
                }
                // ⚠️ **The camera is fitted to what is drawn, so what is not
                // drawn must not stretch it.** An effect with a transparent
                // draw far off-centre would otherwise be framed around empty
                // space and rendered a few pixels across (D280).
                if shading(Some(named), &pose, art, frame).invisible() {
                    continue;
                }
                here = Some(union(here, box_of(geometry, &pose.world)));
            }
            let here = here.unwrap_or_else(|| {
                // No geometry, so the stand-in billboard's own extent.
                let at = placement(entry, part, scale);
                let corner = Vec3::new(scale * HALF, scale * HALF, scale * HALF);
                Bounds {
                    min: at - corner,
                    max: at + corner,
                }
            });
            span = Some(union(span, here));
        }
    }
    span.unwrap_or(Bounds {
        min: Vec3::new(-HALF, -HALF, -HALF),
        max: Vec3::new(HALF, HALF, HALF),
    })
}

/// How many instants the camera is fitted across. ⚠️ A reporting choice, not a
/// decoded one: enough that a part which only appears late is still framed.
const SAMPLES: usize = 12;

/// ⚠️ **Per axis, not a radius.** A single reach used for all three collapses
/// to a cube, which hides exactly the anisotropy a caller needs to see: one
/// display list of the file's 360 is 640 units wide and 58,642 deep, and as a
/// cube it reports as perfectly ordinary (D264).
fn box_of(geometry: &Geometry, world: &[f32; 12]) -> Bounds {
    let mut span: Option<Bounds> = None;
    for p in geometry.positions.chunks_exact(3) {
        let point = apply(world, p[0] as f32, p[1] as f32, p[2] as f32);
        span = Some(union(
            span,
            Bounds {
                min: point,
                max: point,
            },
        ));
    }
    span.unwrap_or(Bounds {
        min: Vec3::ZERO,
        max: Vec3::ZERO,
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
/// ⛔ **Only reached by a draw with no geometry**, which has no measured
/// position to use instead. Deterministic, and a layout rather than a claim
/// about the file: nothing downstream may treat this as where the game puts a
/// part. A draw that *has* geometry is posed by `posed` and never comes here.
fn placement(entry: &Entry, part: usize, scale: f32) -> Vec3 {
    // ⚠️ **Nothing to explode when there is only one part.** Offsetting a lone
    // part pushes it off-centre for no gain, and a camera fitted to the result
    // frames mostly empty space — which is how `item_delete` came to render as
    // nothing at all.
    if entry.parts.len() < 2 {
        return Vec3::ZERO;
    }
    // ⛔ An even ring by part index, and nothing more. The transform rows this
    // used to read are deleted (D270) — they were section 6 sliced by a field
    // that never indexed it. A draw with real geometry never reaches here.
    ring(part, entry.parts.len()).scaled(scale * (RING + SPREAD * part as f32))
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
fn real(geometry: &Geometry, world: &[f32; 12], image: Option<Texture>, how: Surface) -> Mesh {
    let positions: Vec<Vec3> = geometry
        .positions
        .chunks_exact(3)
        .map(|p| apply(world, p[0] as f32, p[1] as f32, p[2] as f32))
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
    let paints: Vec<Paint> = image.map(|t| painted(t, how)).into_iter().collect();
    let paint = (!paints.is_empty()).then_some(0);
    Parts {
        shapes: vec![Shape {
            first: 0,
            count: faces.len(),
            visible: true,
            off_in_file: false,
            paint,
        }],
        positions,
        faces,
        uvs,
        colours,
        paints,
        // The curves that animate an effect are sampled by the caller and
        // baked into this mesh; there is no morph clip here to play.
        animation: None,
    }
    .into_mesh()
}

/// How an effect's bank image is sampled and composited.
///
/// ✅ **The wrap modes and the UV transform are the file's own** (D281), rather
/// than the repeat/repeat default this passed until now. 84 of the file's 350
/// texture records ask for something other than repeat on at least one axis,
/// and the moment a UV curve pushes a coordinate out of the unit square the
/// difference is the whole sprite.
///
/// ✅ **And so is the alpha compare** (D283). It used to be "keep any texel that
/// is not wholly transparent" for every draw; a draw the file declares opaque
/// now keeps every texel including its surround, and one it declares cut-out
/// drops everything under half.
fn painted(texture: Texture, how: Surface) -> Paint {
    Paint {
        texture,
        masked: how.masked,
        blend: how.blend,
        cutoff: how.cutoff,
        sampling: how.sampling,
        modulate: how.modulate,
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
fn quad(basis: &Basis, at: Vec3, half: f32, image: Option<Texture>, how: Surface) -> Mesh {
    let right = basis.right.scaled(half);
    let up = basis.up.scaled(half);
    let paints: Vec<Paint> = image.map(|t| painted(t, how)).into_iter().collect();
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
            off_in_file: false,
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

#[cfg(test)]
mod tests;

#[cfg(test)]
mod real_export_tests;
