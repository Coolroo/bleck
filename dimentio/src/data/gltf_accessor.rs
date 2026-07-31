//! Reading one glTF accessor out of the BIN chunk, dense or sparse.
//!
//! ⚠️ **Three shapes, and all of them are real files.** An accessor may name a
//! buffer view and read straight out of it; it may name none at all, which the
//! specification defines as zeros; and it may carry a `sparse` block that
//! overrides some of those elements with values stored elsewhere. `bleck`
//! writes the first for a target that moves most of a primitive, the second for
//! one that moves none of it, and the third for one that moves a few — and
//! `--dense-morphs` writes only the first two.
//!
//! ⚠️ **The sparse indices decide where the values land, and nothing checks
//! it.** Applying the values in order instead reads back as a mesh that
//! animates the wrong vertices, which looks like a decode bug in the geometry.
//!
//! Split out of `gltf.rs` to keep that module under a thousand lines.

use super::mesh::{Uv, Vec3};

/// glTF component types. Indices are written as the narrowest that fits, and a
/// reader that only understood one would break on any other exporter's file.
pub(crate) const UNSIGNED_BYTE: u64 = 5121;
pub(crate) const UNSIGNED_SHORT: u64 = 5123;
pub(crate) const UNSIGNED_INT: u64 = 5125;

/// The bytes one buffer view covers.
pub(crate) fn view_bytes<'a>(
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

/// Where a block of accessor data begins: a buffer view, and an offset into it.
fn block_bytes<'a>(
    json: &serde_json::Value,
    bin: &'a [u8],
    block: &serde_json::Value,
) -> Result<&'a [u8], String> {
    let view = block["bufferView"]
        .as_u64()
        .ok_or("an accessor block has no bufferView")? as usize;
    let skip = block["byteOffset"].as_u64().unwrap_or(0) as usize;
    view_bytes(json, bin, view)?
        .get(skip..)
        .ok_or_else(|| "an accessor block starts past its view".to_owned())
}

fn accessor_bytes<'a>(
    json: &serde_json::Value,
    bin: &'a [u8],
    index: usize,
) -> Result<Elements<'a>, String> {
    let accessor = &json["accessors"][index];
    let count = accessor["count"].as_u64().ok_or("accessor has no count")? as usize;
    Ok(Elements {
        bytes: block_bytes(json, bin, accessor)?,
        count,
    })
}

/// Read one 32-bit float out of a little-endian accessor.
fn float(bytes: &[u8], at: usize) -> f32 {
    f32::from_le_bytes(bytes[at..at + 4].try_into().unwrap())
}

/// How wide one index of this component type is.
fn integer_width(kind: u64) -> Result<usize, String> {
    match kind {
        UNSIGNED_BYTE => Ok(1),
        UNSIGNED_SHORT => Ok(2),
        UNSIGNED_INT => Ok(4),
        other => Err(format!("componentType {other} is not an integer")),
    }
}

/// One unsigned integer of `width` bytes, little-endian.
fn integer(bytes: &[u8], at: usize, width: usize) -> usize {
    match width {
        1 => bytes[at] as usize,
        2 => u16::from_le_bytes(bytes[at..at + 2].try_into().unwrap()) as usize,
        _ => u32::from_le_bytes(bytes[at..at + 4].try_into().unwrap()) as usize,
    }
}

/// Three floats per element, out of a run of bytes.
fn vec3s(bytes: &[u8], count: usize) -> Result<Vec<Vec3>, String> {
    if bytes.len() < count * 12 {
        return Err("a VEC3 accessor is shorter than its count".into());
    }
    Ok((0..count)
        .map(|i| {
            let at = i * 12;
            Vec3::new(float(bytes, at), float(bytes, at + 4), float(bytes, at + 8))
        })
        .collect())
}

/// Overwrite the elements a `sparse` block names with the values it carries.
///
/// ⚠️ **The index array is not decoration.** It says which element each value
/// belongs to, and a reader that applied them in order would displace the first
/// *n* vertices of every primitive instead of the ones the pose names — a file
/// that loads, animates, and moves the wrong geometry.
///
/// A `count` of zero is accepted and does nothing. `bleck` never writes one —
/// the specification's schema puts a minimum of 1 on it — but reading it as
/// "no deviations" costs nothing and is what the field means.
fn apply_sparse(
    json: &serde_json::Value,
    bin: &[u8],
    sparse: &serde_json::Value,
    values: &mut [Vec3],
) -> Result<(), String> {
    let Some(count) = sparse["count"].as_u64() else {
        return Ok(());
    };
    let count = count as usize;
    if count == 0 {
        return Ok(());
    }
    let block = &sparse["indices"];
    let width = integer_width(
        block["componentType"]
            .as_u64()
            .ok_or("sparse indices have no componentType")?,
    )?;
    let bytes = block_bytes(json, bin, block)?;
    if bytes.len() < count * width {
        return Err("a sparse index array is shorter than its count".into());
    }
    let deltas = vec3s(block_bytes(json, bin, &sparse["values"])?, count)?;
    for (element, delta) in (0..count).zip(deltas) {
        let at = integer(bytes, element * width, width);
        let slot = values
            .get_mut(at)
            .ok_or("a sparse index is past the end of its accessor")?;
        *slot = delta;
    }
    Ok(())
}

/// One `VEC3` accessor: positions, or a morph target's deltas.
///
/// ⚠️ **An accessor with no `bufferView` is zeros, not an error.** That is how
/// a pose that leaves a primitive alone is written, and it is the shape the
/// specification defines for a missing view.
pub(crate) fn read_vec3(
    json: &serde_json::Value,
    bin: &[u8],
    index: usize,
) -> Result<Vec<Vec3>, String> {
    let accessor = &json["accessors"][index];
    let count = accessor["count"].as_u64().ok_or("accessor has no count")? as usize;
    let mut values = match accessor["bufferView"].as_u64() {
        Some(view) => vec3s(
            view_bytes(json, bin, view as usize)?
                .get(accessor["byteOffset"].as_u64().unwrap_or(0) as usize..)
                .ok_or("accessor starts past its view")?,
            count,
        )?,
        None => vec![Vec3::ZERO; count],
    };
    apply_sparse(json, bin, &accessor["sparse"], &mut values)?;
    Ok(values)
}

pub(crate) fn read_vec2(
    json: &serde_json::Value,
    bin: &[u8],
    index: usize,
) -> Result<Vec<Uv>, String> {
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

/// One `SCALAR` float accessor — keyframe times, and the weights they carry.
pub(crate) fn read_scalars(
    json: &serde_json::Value,
    bin: &[u8],
    index: usize,
) -> Result<Vec<f32>, String> {
    let read = accessor_bytes(json, bin, index)?;
    if read.bytes.len() < read.count * 4 {
        return Err("a scalar accessor is shorter than its count".into());
    }
    Ok((0..read.count).map(|i| float(read.bytes, i * 4)).collect())
}

pub(crate) fn read_indices(
    json: &serde_json::Value,
    bin: &[u8],
    index: usize,
) -> Result<Vec<usize>, String> {
    let width = integer_width(
        json["accessors"][index]["componentType"]
            .as_u64()
            .ok_or("index accessor has no componentType")?,
    )?;
    let read = accessor_bytes(json, bin, index)?;
    if read.bytes.len() < read.count * width {
        return Err("index accessor is shorter than its count".into());
    }
    Ok((0..read.count)
        .map(|i| integer(read.bytes, i * width, width))
        .collect())
}

/// The same pose written three ways, and the mesh each of them draws.
///
/// ⚠️ Split out only to keep this module under a thousand lines; `#[path]`
/// keeps it here.
#[cfg(test)]
#[path = "gltf_sparse_tests.rs"]
mod sparse_tests;
