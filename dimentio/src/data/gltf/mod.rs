//! Reading the binary glTF `bleck model export` writes: the JSON chunk
//! describes accessors, the BIN chunk holds them.
//!
//! `POSITION`, `TEXCOORD_0`, the index accessor, the embedded PNG, the morph
//! targets and every weights animation are read. Normals are present in the
//! file and ignored — the rasteriser shades from face normals, so reading them
//! would cost memory for nothing.
//!
//! ⚠️ **A file's morph targets are one list, shared by all its animations**,
//! and each animation holds the others' targets at zero. So the targets are
//! read once and the clips index into them; `morph` is where they are applied.
//!
//! ⚠️ **A missing texture is not a failure.** 277 of 864 real models carry no
//! image and no `TEXCOORD_0`, and they must still load and draw flat-shaded.
//! Everything about the material is therefore optional at every step, and a
//! chain that breaks anywhere yields an untextured mesh rather than an error.
//!
//! # Shape
//!
//! `accessor` reads one accessor out of the BIN chunk, in any of the three
//! encodings a real file uses; nothing here decodes bytes itself. `fixtures`
//! builds `.glb` files in the shape `bleck` writes them, and is shared with the
//! rasteriser's own tests so both are held to the same file.

use std::collections::HashMap;

use accessor::{read_colours, read_indices, read_scalars, read_vec2, read_vec3, view_bytes};

use super::mesh::{Blend, Face, Mask, Paint, Parts, Shape, Uv, Vec3};
use super::morph::{Animation, Clip, Key, Pose};
use super::texture::{Sampling, Texture, Transform, Wrap};

mod accessor;

/// The four bytes every binary glTF opens with.
pub(crate) const MAGIC: &[u8] = b"glTF";

/// What a vertex with no `COLOR_0` means: a multiply by one, which is the
/// specification's default and what `bleck` omits the attribute to say.
const WHITE: [u8; 4] = [255, 255, 255, 255];

/// Where the exporter declares a shape's second layer. ⚠️ **Namespaced**, and
/// it has to match `bleck.formats.gltfpaint.MASK_KEY` exactly — `extras` is a
/// free-for-all shared with every other tool that has touched the file.
pub(crate) const MASK_KEY: &str = "spmMaskTexture";

/// The one glTF extension these files use. Never in `extensionsRequired`, so
/// this reader would still load them if it ignored the transform entirely.
pub(crate) const TRANSFORM_EXTENSION: &str = "KHR_texture_transform";

/// Where `bleck` records that the file marks a shape as off — slot 20's
/// per-node visibility byte, which glTF has no field of its own for.
///
/// ⚠️ Read with a default of `false`. Every export written before this existed
/// carries no `extras`, and those must keep drawing every shape.
pub(crate) const HIDDEN_KEY: &str = "spmHidden";

/// One primitive, decoded into the slice of the model it contributes.
struct Piece {
    positions: Vec<Vec3>,
    faces: Vec<Face>,
    uvs: Option<Vec<Uv>>,
    /// `COLOR_0`, which multiplies whatever the shape draws with (D251).
    colours: Option<Vec<[u8; 4]>>,
    targets: Vec<Pose>,
}

/// Read a `.glb` into the parts a `Mesh` is built from.
///
/// ⛔ **Every primitive, not primitive 0.** `bleck` writes one per shape, and a
/// reader that took the first drew one limb of `e_lui_robo`'s 92 (D236). The
/// primitives are concatenated into one position and face list, with a `Shape`
/// recording which faces came from where so they can be hidden again.
///
/// ⛔ **Every material, not material 0** (D246). A primitive names its own, and
/// 640 of 864 real models reach more than one; the `Shape` carries which.
pub(crate) fn parse(raw: &[u8]) -> Result<Parts, String> {
    let chunks = split_chunks(raw)?;
    let json: serde_json::Value =
        serde_json::from_slice(chunks.json).map_err(|why| format!("glTF JSON: {why}"))?;
    let bin = chunks.bin;

    let primitives = json["meshes"][0]["primitives"]
        .as_array()
        .ok_or("the first mesh has no primitives")?
        .clone();
    if primitives.is_empty() {
        return Err("the first mesh has no primitives".into());
    }

    let mut positions: Vec<Vec3> = Vec::new();
    let mut faces: Vec<Face> = Vec::new();
    let mut shapes: Vec<Shape> = Vec::new();
    let mut uvs: Vec<Uv> = Vec::new();
    let mut colours: Vec<[u8; 4]> = Vec::new();
    let mut textured = false;
    let mut tinted = false;
    let mut columns: Vec<Vec<Pose>> = Vec::new();
    let mut widths: Vec<usize> = Vec::new();
    let mut palette = Palette::default();

    for primitive in &primitives {
        let piece = piece(&json, bin, primitive)?;
        let base = positions.len();
        let first = faces.len();
        faces.extend(piece.faces.iter().map(|face| Face {
            a: face.a + base,
            b: face.b + base,
            c: face.c + base,
        }));
        // ⚠️ **Absent means shown.** An export written before the flag existed
        // carries no `extras` at all, and a missing key must not blank a model.
        let off_in_file = primitive["extras"][HIDDEN_KEY].as_bool().unwrap_or(false);
        shapes.push(Shape {
            first,
            count: faces.len() - first,
            visible: !off_in_file,
            off_in_file,
            paint: palette.slot_for(&json, bin, primitive),
        });
        // ⚠️ UVs are one per position across the whole model, so a primitive
        // that carries none still has to occupy its own span — otherwise every
        // later primitive samples the one before it.
        match piece.uvs {
            Some(found) => {
                textured = true;
                uvs.extend(
                    found
                        .iter()
                        .copied()
                        .chain(std::iter::repeat(Uv::default()))
                        .take(piece.positions.len()),
                );
            }
            None => uvs.extend(std::iter::repeat_n(Uv::default(), piece.positions.len())),
        }
        // ⚠️ The same span rule as the UVs, and for the same reason: 524 of 864
        // models carry no tint at all and most of the rest tint only some of
        // their shapes, so an absent one is white rather than absent.
        match piece.colours {
            Some(found) => {
                tinted = true;
                colours.extend(
                    found
                        .iter()
                        .copied()
                        .chain(std::iter::repeat(WHITE))
                        .take(piece.positions.len()),
                );
            }
            None => colours.extend(std::iter::repeat_n(WHITE, piece.positions.len())),
        }
        widths.push(piece.positions.len());
        positions.extend(piece.positions);
        columns.push(piece.targets);
    }

    let animation = Animation::new(merge_targets(&columns, &widths), clips(&json, bin));

    Ok(Parts {
        positions,
        faces,
        shapes,
        uvs: textured.then_some(uvs),
        colours: tinted.then_some(colours),
        paints: palette.paints,
        animation,
    })
}

/// One primitive's own positions, triangles, texture coordinates and targets,
/// all indexed from zero.
fn piece(
    json: &serde_json::Value,
    bin: &[u8],
    primitive: &serde_json::Value,
) -> Result<Piece, String> {
    let position = primitive["attributes"]["POSITION"]
        .as_u64()
        .ok_or("no POSITION attribute")? as usize;
    let indices = primitive["indices"].as_u64().ok_or("no indices")? as usize;
    let corners = read_indices(json, bin, indices)?;
    Ok(Piece {
        positions: read_vec3(json, bin, position)?,
        faces: corners
            .chunks_exact(3)
            .map(|corner| Face {
                a: corner[0],
                b: corner[1],
                c: corner[2],
            })
            .collect(),
        uvs: primitive["attributes"]["TEXCOORD_0"]
            .as_u64()
            .and_then(|index| read_vec2(json, bin, index as usize).ok()),
        colours: primitive["attributes"]["COLOR_0"]
            .as_u64()
            .and_then(|index| read_colours(json, bin, index as usize).ok()),
        targets: targets(json, bin, primitive),
    })
}

/// Each target index gathered across every primitive, in primitive order.
///
/// ⚠️ **glTF holds targets per primitive and weights per mesh**, so target `n`
/// of every primitive is one pose of the model. The deltas are concatenated in
/// the same order the positions were, and a primitive short of a target — or
/// carrying one that would not read — contributes zeros rather than shifting
/// everything after it.
fn merge_targets(columns: &[Vec<Pose>], widths: &[usize]) -> Vec<Pose> {
    let total = columns.iter().map(Vec::len).max().unwrap_or(0);
    (0..total)
        .map(|index| {
            let mut deltas = Vec::new();
            for (column, &width) in columns.iter().zip(widths) {
                match column.get(index) {
                    Some(pose) if pose.deltas.len() == width => {
                        deltas.extend_from_slice(&pose.deltas);
                    }
                    Some(pose) => {
                        deltas.extend(
                            pose.deltas
                                .iter()
                                .copied()
                                .chain(std::iter::repeat(Vec3::ZERO))
                                .take(width),
                        );
                    }
                    None => deltas.extend(std::iter::repeat_n(Vec3::ZERO, width)),
                }
            }
            Pose { deltas }
        })
        .collect()
}

/// The primitive's morph targets, as position deltas.
///
/// ⚠️ Only `POSITION` is read. glTF allows `NORMAL` and `TANGENT` targets too;
/// the rasteriser shades from face normals, so a normal target would be
/// decoded and then thrown away.
///
/// ⚠️ A target that will not read becomes an **empty** pose rather than being
/// dropped. Targets are positional — target 3 of one primitive is the same
/// pose as target 3 of the next — so skipping one would slide every later
/// target of that primitive onto the wrong clip.
///
/// ⚠️ **Sparse and dense targets arrive interleaved in one file.** `bleck`
/// picks whichever is smaller per target, so a primitive's list holds both
/// shapes and a pose it never reaches is an accessor with no buffer view at
/// all. `gltf::accessor::read_vec3` is what flattens the three into deltas.
fn targets(json: &serde_json::Value, bin: &[u8], primitive: &serde_json::Value) -> Vec<Pose> {
    let Some(list) = primitive["targets"].as_array() else {
        return Vec::new();
    };
    list.iter()
        .map(|target| {
            let deltas = target["POSITION"]
                .as_u64()
                .and_then(|index| read_vec3(json, bin, index as usize).ok())
                .unwrap_or_default();
            Pose { deltas }
        })
        .collect()
}

/// Every animation in the file that drives weights, with its keyframes.
///
/// ⛔ **Only the `weights` path is understood.** A channel driving translation,
/// rotation or scale is ignored: this reader has no node transform to apply it
/// to, and pretending otherwise would play a clip that moves nothing while
/// reporting that it plays.
fn clips(json: &serde_json::Value, bin: &[u8]) -> Vec<Clip> {
    let Some(list) = json["animations"].as_array() else {
        return Vec::new();
    };
    list.iter()
        .enumerate()
        .filter_map(|(index, animation)| {
            let sampler = weight_sampler(animation)?;
            let times = read_scalars(json, bin, sampler.input).ok()?;
            let weights = read_scalars(json, bin, sampler.output).ok()?;
            let name = animation["name"]
                .as_str()
                .map_or_else(|| format!("clip {index}"), str::to_owned);
            Some(Clip {
                name,
                keys: keys(&times, &weights),
            })
        })
        .collect()
}

/// The accessors one sampler reads its input and output from.
struct Sampler {
    input: usize,
    output: usize,
}

/// The sampler behind this animation's first `weights` channel.
fn weight_sampler(animation: &serde_json::Value) -> Option<Sampler> {
    let index = animation["channels"]
        .as_array()?
        .iter()
        .find(|channel| channel["target"]["path"].as_str() == Some("weights"))?["sampler"]
        .as_u64()? as usize;
    let sampler = animation["samplers"].as_array()?.get(index)?;
    Some(Sampler {
        input: sampler["input"].as_u64()? as usize,
        output: sampler["output"].as_u64()? as usize,
    })
}

/// Split a flat weight array into one keyframe per time.
///
/// ⚠️ glTF requires `output.len() == input.len() * targets`, and the target
/// count is not stated anywhere — it is implied by that division. A file whose
/// arrays do not divide evenly yields the keys that do fit, so a truncated
/// export plays as far as it goes instead of not at all.
fn keys(times: &[f32], weights: &[f32]) -> Vec<Key> {
    if times.is_empty() {
        return Vec::new();
    }
    let stride = weights.len() / times.len();
    if stride == 0 {
        return Vec::new();
    }
    times
        .iter()
        .enumerate()
        .filter_map(|(index, &time)| {
            let at = index * stride;
            let slice = weights.get(at..at + stride)?;
            Some(Key {
                time,
                weights: slice.to_vec(),
            })
        })
        .collect()
}

/// The two chunks a `.glb` is made of.
pub(crate) struct Chunks<'a> {
    pub(crate) json: &'a [u8],
    pub(crate) bin: &'a [u8],
}

/// Split a `.glb` into its JSON and binary chunks.
///
/// ⚠️ Each chunk is padded to four bytes and the header length **includes**
/// the padding, so the next chunk starts at the declared length, not at the
/// end of the meaningful data.
pub(crate) fn split_chunks(raw: &[u8]) -> Result<Chunks<'_>, String> {
    if raw.len() < 20 {
        return Err("too short to be a glTF".into());
    }
    let mut at = 12;
    let mut json: &[u8] = &[];
    let mut bin: &[u8] = &[];
    while at + 8 <= raw.len() {
        let length = u32::from_le_bytes(raw[at..at + 4].try_into().unwrap()) as usize;
        let kind = &raw[at + 4..at + 8];
        let start = at + 8;
        let stop = start.saturating_add(length).min(raw.len());
        match kind {
            b"JSON" => json = &raw[start..stop],
            b"BIN\0" => bin = &raw[start..stop],
            _ => {}
        }
        at = start + length;
    }
    if json.is_empty() {
        return Err("glTF has no JSON chunk".into());
    }
    Ok(Chunks { json, bin })
}

/// The images the primitives read so far, and where each glTF material landed
/// among them.
///
/// ⚠️ **Keyed on the material, so a PNG is decoded once however many primitives
/// name it.** `e_lui_robo` has 68 painted primitives over 15 materials, and
/// `p_peach` 69 materials; decoding per primitive would repeat the work of the
/// whole file. A material that yields no image is remembered as `None` for the
/// same reason.
#[derive(Default)]
struct Palette {
    paints: Vec<Paint>,
    resolved: HashMap<usize, Option<usize>>,
}

impl Palette {
    /// Which paint this primitive draws with, decoding its image on first
    /// sight.
    fn slot_for(
        &mut self,
        json: &serde_json::Value,
        bin: &[u8],
        primitive: &serde_json::Value,
    ) -> Option<usize> {
        let index = primitive["material"].as_u64()? as usize;
        if let Some(&slot) = self.resolved.get(&index) {
            return slot;
        }
        let slot = material(json, bin, index).map(|paint| {
            self.paints.push(paint);
            self.paints.len() - 1
        });
        self.resolved.insert(index, slot);
        slot
    }
}

/// Follow material → texture → image → buffer view, and decode the PNG at the
/// end of it.
///
/// ⚠️ A decode failure yields no paint rather than an error, so one model with
/// a broken image cannot take the whole export down. The real-export test is
/// what catches an image the decoder has stopped understanding.
///
/// ⚠️ **The mask is optional in every direction.** A file written before D247
/// carries no `extras`, and a mask whose image fails to decode leaves the base
/// layer drawn plain rather than dropping the shape.
fn material(json: &serde_json::Value, bin: &[u8], index: usize) -> Option<Paint> {
    let material = &json["materials"][index];
    let base = &material["pbrMetallicRoughness"]["baseColorTexture"];
    Some(Paint {
        // Model art is `MASK`: opaque where drawn at all, so nothing to blend.
        blend: Blend::Opaque,
        texture: decode_reference(json, bin, base)?,
        masked: material["alphaMode"].as_str() == Some("MASK"),
        cutoff: crate::render::MASK_CUTOFF,
        sampling: sampling(json, base),
        // A glTF material carries no colour register; the exporter puts a
        // model's tint in `COLOR_0`, which the rasteriser reads per vertex.
        modulate: crate::data::mesh::Modulate::default(),
        mask: mask(json, bin, material),
    })
}

/// The second layer, declared in `material.extras` because glTF has no core
/// slot for "multiply the base by this image's alpha" (D247).
fn mask(json: &serde_json::Value, bin: &[u8], material: &serde_json::Value) -> Option<Mask> {
    let declared = material.get("extras")?.get(MASK_KEY)?;
    Some(Mask {
        texture: decode_reference(json, bin, declared)?,
        sampling: sampling(json, declared),
    })
}

/// One `textureInfo`, walked to its PNG bytes and decoded.
fn decode_reference(
    json: &serde_json::Value,
    bin: &[u8],
    info: &serde_json::Value,
) -> Option<Texture> {
    info["index"]
        .as_u64()
        .and_then(|texture| json["textures"][texture as usize]["source"].as_u64())
        .and_then(|image| json["images"][image as usize]["bufferView"].as_u64())
        .and_then(|view| view_bytes(json, bin, view as usize).ok())
        .and_then(|bytes| Texture::decode(bytes).ok())
}

/// How one `textureInfo` folds a coordinate: its sampler, and its transform.
///
/// ⛔ **The sampler's *index* is not its wrap mode.** Reading `texture.sampler`
/// as an enum gives 0 for every real file, which is not one of the three glTF
/// wrap constants and would silently fall back to REPEAT everywhere — the same
/// failure as never reading it at all.
fn sampling(json: &serde_json::Value, info: &serde_json::Value) -> Sampling {
    let sampler = info["index"]
        .as_u64()
        .and_then(|texture| json["textures"][texture as usize]["sampler"].as_u64())
        .map(|at| json["samplers"][at as usize].clone())
        .unwrap_or(serde_json::Value::Null);
    Sampling {
        wrap_s: sampler["wrapS"].as_u64().map_or(Wrap::default(), Wrap::of),
        wrap_t: sampler["wrapT"].as_u64().map_or(Wrap::default(), Wrap::of),
        transform: transform(&info["extensions"][TRANSFORM_EXTENSION]),
    }
}

/// A `KHR_texture_transform`, with the extension's own defaults for whatever it
/// leaves out.
fn transform(declared: &serde_json::Value) -> Transform {
    let pair = |name: &str, fallback: [f32; 2]| {
        declared[name]
            .as_array()
            .and_then(|found| Some([found.first()?.as_f64()?, found.get(1)?.as_f64()?]))
            .map_or(fallback, |found| [found[0] as f32, found[1] as f32])
    };
    Transform {
        offset: pair("offset", [0.0, 0.0]),
        rotation: declared["rotation"].as_f64().unwrap_or(0.0) as f32,
        scale: pair("scale", [1.0, 1.0]),
    }
}

#[cfg(test)]
pub(crate) mod fixtures;

#[cfg(test)]
mod tests;

/// One glTF primitive per shape: reading all of them, and hiding one.
#[cfg(test)]
mod shape_tests;
