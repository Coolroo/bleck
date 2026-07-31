//! Reading the binary glTF `bleck model export` writes: the JSON chunk
//! describes accessors, the BIN chunk holds them.
//!
//! `POSITION`, `TEXCOORD_0`, the index accessor and the embedded PNG are read.
//! Normals and morph targets are present in the file and ignored here — the
//! rasteriser shades from face normals and draws one pose, so reading them
//! would cost memory for nothing.
//!
//! ⚠️ **A missing texture is not a failure.** 277 of 864 real models carry no
//! image and no `TEXCOORD_0`, and they must still load and draw flat-shaded.
//! Everything about the material is therefore optional at every step, and a
//! chain that breaks anywhere yields an untextured mesh rather than an error.

use super::mesh::{Face, Parts, Uv, Vec3};
use super::texture::Texture;

/// The four bytes every binary glTF opens with.
pub(crate) const MAGIC: &[u8] = b"glTF";

/// glTF component types, for the index accessor. Indices are written as
/// `UNSIGNED_INT`, but a reader that only understood one would break on any
/// other exporter's file for no reason.
const UNSIGNED_BYTE: u64 = 5121;
const UNSIGNED_SHORT: u64 = 5123;
const UNSIGNED_INT: u64 = 5125;

/// Read a `.glb` into the parts a `Mesh` is built from.
pub(crate) fn parse(raw: &[u8]) -> Result<Parts, String> {
    let chunks = split_chunks(raw)?;
    let json: serde_json::Value =
        serde_json::from_slice(chunks.json).map_err(|why| format!("glTF JSON: {why}"))?;
    let bin = chunks.bin;

    let primitive = json["meshes"][0]["primitives"][0].clone();
    let position = primitive["attributes"]["POSITION"]
        .as_u64()
        .ok_or("no POSITION attribute")? as usize;
    let indices = primitive["indices"].as_u64().ok_or("no indices")? as usize;

    let positions = read_vec3(&json, bin, position)?;
    let corners = read_indices(&json, bin, indices)?;
    let faces = corners
        .chunks_exact(3)
        .map(|corner| Face {
            a: corner[0],
            b: corner[1],
            c: corner[2],
        })
        .collect::<Vec<_>>();

    let uvs = primitive["attributes"]["TEXCOORD_0"]
        .as_u64()
        .and_then(|index| read_vec2(&json, bin, index as usize).ok());
    let paint = material(&json, bin, &primitive);

    Ok(Parts {
        positions,
        faces,
        uvs,
        texture: paint.texture,
        masked: paint.masked,
    })
}

/// The two chunks a `.glb` is made of.
struct Chunks<'a> {
    json: &'a [u8],
    bin: &'a [u8],
}

/// Split a `.glb` into its JSON and binary chunks.
///
/// ⚠️ Each chunk is padded to four bytes and the header length **includes**
/// the padding, so the next chunk starts at the declared length, not at the
/// end of the meaningful data.
fn split_chunks(raw: &[u8]) -> Result<Chunks<'_>, String> {
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

/// What the primitive's material asks for: an image, and whether its alpha is
/// a cut-out or decoration.
struct Paint {
    texture: Option<Texture>,
    masked: bool,
}

/// Follow primitive → material → texture → image → buffer view, and decode the
/// PNG at the end of it.
///
/// ⚠️ A decode failure yields no texture rather than an error, so one model
/// with a broken image cannot take the whole export down. The real-export test
/// is what catches an image the decoder has stopped understanding.
fn material(json: &serde_json::Value, bin: &[u8], primitive: &serde_json::Value) -> Paint {
    let Some(index) = primitive["material"].as_u64() else {
        return Paint {
            texture: None,
            masked: false,
        };
    };
    let material = &json["materials"][index as usize];
    let texture = material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
        .as_u64()
        .and_then(|texture| json["textures"][texture as usize]["source"].as_u64())
        .and_then(|image| json["images"][image as usize]["bufferView"].as_u64())
        .and_then(|view| view_bytes(json, bin, view as usize).ok())
        .and_then(|bytes| Texture::decode(bytes).ok());
    Paint {
        texture,
        masked: material["alphaMode"].as_str() == Some("MASK"),
    }
}

/// The bytes one buffer view covers.
fn view_bytes<'a>(
    json: &serde_json::Value,
    bin: &'a [u8],
    index: usize,
) -> Result<&'a [u8], String> {
    let view = &json["bufferViews"][index];
    let offset = view["byteOffset"].as_u64().unwrap_or(0) as usize;
    let length = view["byteLength"]
        .as_u64()
        .ok_or("view has no byteLength")? as usize;
    if offset + length > bin.len() {
        return Err("a buffer view runs past the binary chunk".into());
    }
    Ok(&bin[offset..offset + length])
}

/// One accessor's bytes, and how many elements it declares.
struct Elements<'a> {
    bytes: &'a [u8],
    count: usize,
}

fn accessor_bytes<'a>(
    json: &serde_json::Value,
    bin: &'a [u8],
    index: usize,
) -> Result<Elements<'a>, String> {
    let accessor = &json["accessors"][index];
    let count = accessor["count"].as_u64().ok_or("accessor has no count")? as usize;
    let view = accessor["bufferView"]
        .as_u64()
        .ok_or("accessor has no bufferView")? as usize;
    let skip = accessor["byteOffset"].as_u64().unwrap_or(0) as usize;
    let bytes = view_bytes(json, bin, view)?;
    let bytes = bytes.get(skip..).ok_or("accessor starts past its view")?;
    Ok(Elements { bytes, count })
}

/// Read one 32-bit float out of a little-endian accessor.
fn float(bytes: &[u8], at: usize) -> f32 {
    f32::from_le_bytes(bytes[at..at + 4].try_into().unwrap())
}

fn read_vec3(json: &serde_json::Value, bin: &[u8], index: usize) -> Result<Vec<Vec3>, String> {
    let read = accessor_bytes(json, bin, index)?;
    if read.bytes.len() < read.count * 12 {
        return Err("POSITION accessor is shorter than its count".into());
    }
    Ok((0..read.count)
        .map(|i| {
            let at = i * 12;
            Vec3::new(
                float(read.bytes, at),
                float(read.bytes, at + 4),
                float(read.bytes, at + 8),
            )
        })
        .collect())
}

fn read_vec2(json: &serde_json::Value, bin: &[u8], index: usize) -> Result<Vec<Uv>, String> {
    let read = accessor_bytes(json, bin, index)?;
    if read.bytes.len() < read.count * 8 {
        return Err("TEXCOORD_0 accessor is shorter than its count".into());
    }
    Ok((0..read.count)
        .map(|i| {
            let at = i * 8;
            Uv::new(float(read.bytes, at), float(read.bytes, at + 4))
        })
        .collect())
}

fn read_indices(json: &serde_json::Value, bin: &[u8], index: usize) -> Result<Vec<usize>, String> {
    let kind = json["accessors"][index]["componentType"]
        .as_u64()
        .ok_or("index accessor has no componentType")?;
    let read = accessor_bytes(json, bin, index)?;
    let width = match kind {
        UNSIGNED_BYTE => 1,
        UNSIGNED_SHORT => 2,
        UNSIGNED_INT => 4,
        other => return Err(format!("index componentType {other} is not an integer")),
    };
    if read.bytes.len() < read.count * width {
        return Err("index accessor is shorter than its count".into());
    }
    Ok((0..read.count)
        .map(|i| {
            let at = i * width;
            match width {
                1 => read.bytes[at] as usize,
                2 => u16::from_le_bytes(read.bytes[at..at + 2].try_into().unwrap()) as usize,
                _ => u32::from_le_bytes(read.bytes[at..at + 4].try_into().unwrap()) as usize,
            }
        })
        .collect())
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

    fn push_floats(bin: &mut Vec<u8>, values: &[f32]) {
        for value in values {
            bin.extend_from_slice(&value.to_le_bytes());
        }
    }

    /// Append indices at a 4-byte boundary and report where they landed.
    fn pad(bin: &mut Vec<u8>, indices: &[u32]) -> usize {
        while bin.len() % 4 != 0 {
            bin.push(0);
        }
        let at = bin.len();
        for value in indices {
            bin.extend_from_slice(&value.to_le_bytes());
        }
        at
    }

    fn container(json: &str, bin: &[u8]) -> Vec<u8> {
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
    use super::fixtures::{bare_triangle, textured_quad, QUAD_UVS};
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
        assert!(parts.texture.is_none());
        assert!(!parts.masked);
        assert!(parts.into_mesh().surface().is_none());
    }

    #[test]
    fn texcoords_the_image_and_the_alpha_mode_are_all_read() {
        let parts =
            parse(&textured_quad(QUAD_UVS, 2, 1, &[RED, GREEN])).expect("textured quad parses");
        assert_eq!(parts.positions.len(), 4);
        assert_eq!(parts.faces.len(), 2);
        assert!(parts.masked, "alphaMode MASK was not read");

        let uvs = parts.uvs.as_ref().expect("TEXCOORD_0");
        assert_eq!(uvs.len(), 4);
        assert_eq!((uvs[0].u, uvs[0].v), (0.0, 1.0));
        assert_eq!((uvs[2].u, uvs[2].v), (1.0, 0.0));

        let texture = parts.texture.as_ref().expect("embedded png");
        assert_eq!(texture.width(), 2);
        assert_eq!(texture.height(), 1);
        assert_eq!(texture.sample(0.25, 0.5), RED);
        assert_eq!(texture.sample(0.75, 0.5), GREEN);
    }

    /// The image sits in the same BIN chunk as the geometry, at an offset the
    /// document declares. Reading the wrong view yields geometry bytes, which
    /// the PNG decoder rejects — so this is the test that the chain
    /// material → texture → image → bufferView is walked correctly.
    #[test]
    fn the_texture_survives_a_round_trip_through_a_file_on_disk() {
        let scratch = Scratch::new("glb-textured");
        scratch.write("quad.glb", textured_quad(QUAD_UVS, 2, 1, &[RED, GREEN]));
        let mesh = Mesh::load(&scratch.path.join("quad.glb")).expect("textured quad loads");
        let surface = mesh.surface().expect("a surface");
        assert_eq!(surface.texture.sample(0.75, 0.5), GREEN);
        assert_eq!(surface.uvs.len(), mesh.positions().len());
    }
}
