//! Building the files this reader is pointed at, in the shape
//! `bleck.formats.gltf` writes them.
//!
//! ⚠️ Shared with `render::raster`'s texture tests and with the window's
//! layout tests, which is why it is `pub(crate)` rather than private: a second
//! set of fixtures would let the reader and the rasteriser be tested against
//! different files and agree with neither.

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
