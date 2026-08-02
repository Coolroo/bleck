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

use std::collections::HashMap;

use super::gltf_accessor::{
    read_colours, read_indices, read_scalars, read_vec2, read_vec3, view_bytes,
};
use super::mesh::{Face, Mask, Paint, Parts, Shape, Uv, Vec3};
use super::morph::{Animation, Clip, Key, Pose};
use super::texture::{Sampling, Texture, Transform, Wrap};

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
        shapes.push(Shape {
            first,
            count: faces.len() - first,
            visible: true,
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
/// all. `gltf_accessor::read_vec3` is what flattens the three into deltas.
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
        blended: false,
        texture: decode_reference(json, bin, base)?,
        masked: material["alphaMode"].as_str() == Some("MASK"),
        cutoff: crate::render::MASK_CUTOFF,
        sampling: sampling(json, base),
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

/// Building the files this reader is pointed at, in the shape
/// `bleck.formats.gltf` writes them.
#[cfg(test)]
pub(crate) mod fixtures {
    use super::MAGIC;
    use crate::data::texture::{png, Texel};

    /// A quad in the plane the camera faces, its four corners mapped to the
    /// four corners of the texture. Vertex 0 is the bottom left, and its `v`
    /// is 1 — glTF's origin is the image's top-left, so the *bottom* of the
    /// model samples the *bottom* of the image at v = 1.
    pub(crate) const QUAD_UVS: [(f32, f32); 4] = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)];

    /// The same quad with the texture repeated `times` over — what 21% of real
    /// models do, and what a sampler that clamps instead of wrapping ruins.
    pub(crate) fn tiled(times: f32) -> [(f32, f32); 4] {
        QUAD_UVS.map(|(u, v)| (u * times, v * times))
    }

    /// One triangle with no material at all, which is what an untextured model
    /// looks like on disk.
    pub(crate) fn bare_triangle() -> Vec<u8> {
        let positions: [f32; 9] = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0];
        let mut bin = Vec::new();
        push_floats(&mut bin, &positions);
        let indices = pad(&mut bin, &[0u32, 1, 2]);
        let json = format!(
            r#"{{"asset":{{"version":"2.0"}},
                "meshes":[{{"primitives":[{{"attributes":{{"POSITION":0}},"indices":1}}]}}],
                "accessors":[{{"bufferView":0,"componentType":5126,"count":3,"type":"VEC3"}},
                             {{"bufferView":1,"componentType":5125,"count":3,"type":"SCALAR"}}],
                "bufferViews":[{{"buffer":0,"byteOffset":0,"byteLength":36}},
                               {{"buffer":0,"byteOffset":{indices},"byteLength":12}}],
                "buffers":[{{"byteLength":{}}}]}}"#,
            bin.len()
        );
        container(&json, &bin)
    }

    /// A textured quad: four corners, two triangles, `TEXCOORD_0`, and `image`
    /// embedded as the PNG the material points at. It sits in the plane the
    /// `head_on` camera faces, spanning ±2 on both axes.
    pub(crate) fn textured_quad(
        uvs: [(f32, f32); 4],
        width: u32,
        height: u32,
        texels: &[Texel],
    ) -> Vec<u8> {
        let positions: [f32; 12] = [
            -2.0, -2.0, 0.0, 2.0, -2.0, 0.0, 2.0, 2.0, 0.0, -2.0, 2.0, 0.0,
        ];
        let mut bin = Vec::new();
        push_floats(&mut bin, &positions);

        let uv_at = bin.len();
        for (u, v) in uvs {
            push_floats(&mut bin, &[u, v]);
        }
        let indices = pad(&mut bin, &[0u32, 1, 2, 0, 2, 3]);

        let image_at = bin.len();
        let image = png(width, height, texels);
        bin.extend_from_slice(&image);

        let json = format!(
            r#"{{"asset":{{"version":"2.0"}},
                "meshes":[{{"primitives":[{{"attributes":{{"POSITION":0,"TEXCOORD_0":1}},
                             "indices":2,"material":0}}]}}],
                "accessors":[{{"bufferView":0,"componentType":5126,"count":4,"type":"VEC3"}},
                             {{"bufferView":1,"componentType":5126,"count":4,"type":"VEC2"}},
                             {{"bufferView":2,"componentType":5125,"count":6,"type":"SCALAR"}}],
                "bufferViews":[{{"buffer":0,"byteOffset":0,"byteLength":48}},
                               {{"buffer":0,"byteOffset":{uv_at},"byteLength":32}},
                               {{"buffer":0,"byteOffset":{indices},"byteLength":24}},
                               {{"buffer":0,"byteOffset":{image_at},"byteLength":{}}}],
                "images":[{{"bufferView":3,"mimeType":"image/png"}}],
                "samplers":[{{"wrapS":10497,"wrapT":10497}}],
                "textures":[{{"sampler":0,"source":0}}],
                "materials":[{{"pbrMetallicRoughness":{{"baseColorTexture":{{"index":0}}}},
                               "alphaMode":"MASK","doubleSided":true}}],
                "buffers":[{{"byteLength":{}}}]}}"#,
            image.len(),
            bin.len()
        );
        container(&json, &bin)
    }

    /// The same quad with no `TEXCOORD_0` and no material — the shape 277 of
    /// 864 real models are in, and the control the textured tests compare to.
    pub(crate) fn bare_quad() -> Vec<u8> {
        let positions: [f32; 12] = [
            -2.0, -2.0, 0.0, 2.0, -2.0, 0.0, 2.0, 2.0, 0.0, -2.0, 2.0, 0.0,
        ];
        let mut bin = Vec::new();
        push_floats(&mut bin, &positions);
        let indices = pad(&mut bin, &[0u32, 1, 2, 0, 2, 3]);
        let json = format!(
            r#"{{"asset":{{"version":"2.0"}},
                "meshes":[{{"primitives":[{{"attributes":{{"POSITION":0}},"indices":1}}]}}],
                "accessors":[{{"bufferView":0,"componentType":5126,"count":4,"type":"VEC3"}},
                             {{"bufferView":1,"componentType":5125,"count":6,"type":"SCALAR"}}],
                "bufferViews":[{{"buffer":0,"byteOffset":0,"byteLength":48}},
                               {{"buffer":0,"byteOffset":{indices},"byteLength":24}}],
                "buffers":[{{"byteLength":{}}}]}}"#,
            bin.len()
        );
        container(&json, &bin)
    }

    /// The quad with two morph targets and two named animations over them, in
    /// the shape `bleck.formats.gltf` writes: one shared target list, and each
    /// clip holding the other's target at zero.
    ///
    /// Target 0 lifts vertex 0 by 3 on Y; target 1 pushes vertex 2 by 3 on X.
    /// `wave` steps from the first to the second over one second; `jump` is a
    /// single key holding the second.
    pub(crate) fn animated_quad() -> Vec<u8> {
        let positions: [f32; 12] = [
            -2.0, -2.0, 0.0, 2.0, -2.0, 0.0, 2.0, 2.0, 0.0, -2.0, 2.0, 0.0,
        ];
        let mut bin = Vec::new();
        push_floats(&mut bin, &positions);
        let indices = pad(&mut bin, &[0u32, 1, 2, 0, 2, 3]);

        let first_at = bin.len();
        push_floats(
            &mut bin,
            &[0.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        );
        let second_at = bin.len();
        push_floats(
            &mut bin,
            &[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        );

        let wave_times = bin.len();
        push_floats(&mut bin, &[0.0, 1.0]);
        let wave_weights = bin.len();
        push_floats(&mut bin, &[1.0, 0.0, 0.0, 1.0]);
        let jump_times = bin.len();
        push_floats(&mut bin, &[0.0]);
        let jump_weights = bin.len();
        push_floats(&mut bin, &[0.0, 1.0]);

        let json = format!(
            r#"{{"asset":{{"version":"2.0"}},
                "meshes":[{{"weights":[0.0,0.0],
                            "primitives":[{{"attributes":{{"POSITION":0}},"indices":1,
                              "targets":[{{"POSITION":2}},{{"POSITION":3}}]}}]}}],
                "animations":[
                  {{"name":"wave",
                    "samplers":[{{"input":4,"output":5,"interpolation":"LINEAR"}}],
                    "channels":[{{"sampler":0,"target":{{"node":0,"path":"weights"}}}}]}},
                  {{"name":"jump",
                    "samplers":[{{"input":6,"output":7,"interpolation":"LINEAR"}}],
                    "channels":[{{"sampler":0,"target":{{"node":0,"path":"weights"}}}}]}}],
                "accessors":[{{"bufferView":0,"componentType":5126,"count":4,"type":"VEC3"}},
                             {{"bufferView":1,"componentType":5125,"count":6,"type":"SCALAR"}},
                             {{"bufferView":2,"componentType":5126,"count":4,"type":"VEC3"}},
                             {{"bufferView":3,"componentType":5126,"count":4,"type":"VEC3"}},
                             {{"bufferView":4,"componentType":5126,"count":2,"type":"SCALAR"}},
                             {{"bufferView":5,"componentType":5126,"count":4,"type":"SCALAR"}},
                             {{"bufferView":6,"componentType":5126,"count":1,"type":"SCALAR"}},
                             {{"bufferView":7,"componentType":5126,"count":2,"type":"SCALAR"}}],
                "bufferViews":[{{"buffer":0,"byteOffset":0,"byteLength":48}},
                               {{"buffer":0,"byteOffset":{indices},"byteLength":24}},
                               {{"buffer":0,"byteOffset":{first_at},"byteLength":48}},
                               {{"buffer":0,"byteOffset":{second_at},"byteLength":48}},
                               {{"buffer":0,"byteOffset":{wave_times},"byteLength":8}},
                               {{"buffer":0,"byteOffset":{wave_weights},"byteLength":16}},
                               {{"buffer":0,"byteOffset":{jump_times},"byteLength":4}},
                               {{"buffer":0,"byteOffset":{jump_weights},"byteLength":8}}],
                "buffers":[{{"byteLength":{}}}]}}"#,
            bin.len()
        );
        container(&json, &bin)
    }

    /// One quad per entry, side by side along X, each painted with its own
    /// solid-colour image — or bare where the entry is `None`, which is the
    /// state 24 of `e_lui_robo`'s 92 primitives are in.
    ///
    /// ⚠️ **Solid images, one texel each, on purpose.** Every pixel a quad
    /// covers is then exactly that quad's colour, so counting the frame's
    /// distinct colours counts the images that were sampled. All the quads are
    /// coplanar, so they take the same shading term and cannot differ for any
    /// other reason.
    pub(crate) fn painted_quads(colours: &[Option<Texel>]) -> Vec<u8> {
        let quads: Vec<Quad> = colours
            .iter()
            .map(|image| Quad {
                image: *image,
                tint: None,
            })
            .collect();
        quads_glb(&quads)
    }

    /// One quad's image and its vertex tint, either of which may be absent.
    #[derive(Clone, Copy)]
    pub(crate) struct Quad {
        pub(crate) image: Option<Texel>,
        pub(crate) tint: Option<[u8; 4]>,
    }

    /// The same coplanar quads, each optionally carrying a `COLOR_0` (D251).
    pub(crate) fn quads_glb(quads: &[Quad]) -> Vec<u8> {
        let mut bin: Vec<u8> = Vec::new();
        let mut views: Vec<String> = Vec::new();
        let mut accessors: Vec<String> = Vec::new();
        let mut primitives: Vec<String> = Vec::new();
        let mut images: Vec<String> = Vec::new();
        let mut textures: Vec<String> = Vec::new();
        let mut materials: Vec<String> = Vec::new();
        /// Declare a buffer view over `bin` and report its index.
        fn view(views: &mut Vec<String>, at: usize, length: usize) -> usize {
            views.push(format!(
                r#"{{"buffer":0,"byteOffset":{at},"byteLength":{length}}}"#
            ));
            views.len() - 1
        }

        for (index, quad) in quads.iter().enumerate() {
            let colour = &quad.image;
            let centre = index as f32 * 6.0;
            let at = bin.len();
            push_floats(
                &mut bin,
                &[
                    centre - 2.0,
                    -2.0,
                    0.0,
                    centre + 2.0,
                    -2.0,
                    0.0,
                    centre + 2.0,
                    2.0,
                    0.0,
                    centre - 2.0,
                    2.0,
                    0.0,
                ],
            );
            let held = view(&mut views, at, 48);
            let position = accessors.len();
            accessors.push(format!(
                r#"{{"bufferView":{held},"componentType":5126,"count":4,"type":"VEC3"}}"#
            ));

            let mut attributes = format!(r#""POSITION":{position}"#);
            let mut names = String::new();
            if let Some(texel) = colour {
                let uv_at = bin.len();
                for (u, v) in QUAD_UVS {
                    push_floats(&mut bin, &[u, v]);
                }
                let held = view(&mut views, uv_at, 32);
                let uv = accessors.len();
                accessors.push(format!(
                    r#"{{"bufferView":{held},"componentType":5126,"count":4,"type":"VEC2"}}"#
                ));
                attributes.push_str(&format!(r#","TEXCOORD_0":{uv}"#));

                let image_at = bin.len();
                let image = png(1, 1, &[*texel]);
                bin.extend_from_slice(&image);
                let held = view(&mut views, image_at, image.len());
                images.push(format!(r#"{{"bufferView":{held},"mimeType":"image/png"}}"#));
                textures.push(format!(r#"{{"sampler":0,"source":{}}}"#, images.len() - 1));
                materials.push(format!(
                    r#"{{"pbrMetallicRoughness":{{"baseColorTexture":{{"index":{}}}}},
                        "alphaMode":"MASK","doubleSided":true}}"#,
                    textures.len() - 1
                ));
                names = format!(r#","material":{}"#, materials.len() - 1);
            }

            if let Some(tint) = quad.tint {
                let tint_at = bin.len();
                for _ in 0..4 {
                    bin.extend_from_slice(&tint);
                }
                let held = view(&mut views, tint_at, 16);
                let slot = accessors.len();
                accessors.push(format!(
                    r#"{{"bufferView":{held},"componentType":5121,"count":4,
                        "type":"VEC4","normalized":true}}"#
                ));
                attributes.push_str(&format!(r#","COLOR_0":{slot}"#));
            }

            let indices_at = pad(&mut bin, &[0u32, 1, 2, 0, 2, 3]);
            let held = view(&mut views, indices_at, 24);
            let indices = accessors.len();
            accessors.push(format!(
                r#"{{"bufferView":{held},"componentType":5125,"count":6,"type":"SCALAR"}}"#
            ));
            primitives.push(format!(
                r#"{{"attributes":{{{attributes}}},"indices":{indices}{names}}}"#
            ));
        }

        let painting = if materials.is_empty() {
            String::new()
        } else {
            format!(
                r#""images":[{}],"samplers":[{{"wrapS":10497,"wrapT":10497}}],
                   "textures":[{}],"materials":[{}],"#,
                images.join(","),
                textures.join(","),
                materials.join(",")
            )
        };
        let json = format!(
            r#"{{"asset":{{"version":"2.0"}},
                "meshes":[{{"primitives":[{}]}}],
                "accessors":[{}],
                "bufferViews":[{}],
                {painting}
                "buffers":[{{"byteLength":{}}}]}}"#,
            primitives.join(","),
            accessors.join(","),
            views.join(","),
            bin.len()
        );
        container(&json, &bin)
    }

    pub(crate) fn push_floats(bin: &mut Vec<u8>, values: &[f32]) {
        for value in values {
            bin.extend_from_slice(&value.to_le_bytes());
        }
    }

    /// Append indices at a 4-byte boundary and report where they landed.
    pub(crate) fn pad(bin: &mut Vec<u8>, indices: &[u32]) -> usize {
        while bin.len() % 4 != 0 {
            bin.push(0);
        }
        let at = bin.len();
        for value in indices {
            bin.extend_from_slice(&value.to_le_bytes());
        }
        at
    }

    pub(crate) fn container(json: &str, bin: &[u8]) -> Vec<u8> {
        let mut text = json.as_bytes().to_vec();
        while text.len() % 4 != 0 {
            text.push(b' ');
        }
        let mut binary = bin.to_vec();
        while binary.len() % 4 != 0 {
            binary.push(0);
        }
        let mut out = Vec::new();
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&2u32.to_le_bytes());
        let total = 12 + 8 + text.len() + 8 + binary.len();
        out.extend_from_slice(&(total as u32).to_le_bytes());
        out.extend_from_slice(&(text.len() as u32).to_le_bytes());
        out.extend_from_slice(b"JSON");
        out.extend_from_slice(&text);
        out.extend_from_slice(&(binary.len() as u32).to_le_bytes());
        out.extend_from_slice(b"BIN\0");
        out.extend_from_slice(&binary);
        out
    }
}

#[cfg(test)]
mod tests {
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
        let parts =
            parse(&textured_quad(QUAD_UVS, 2, 1, &[RED, GREEN])).expect("textured quad parses");
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
}

/// One primitive per shape: reading all of them, and hiding one.
///
/// ⚠️ Split out only to keep this module under a thousand lines; `#[path]`
/// keeps it here.
#[cfg(test)]
#[path = "gltf_shape_tests.rs"]
mod shape_tests;
