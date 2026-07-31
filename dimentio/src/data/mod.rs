//! What `bleck` exported, and nothing else.
//!
//! Every module here reads a manifest `bleck` wrote and the files named in it —
//! PNGs, OBJs, effect tables. No game format is decoded at this layer, or at
//! any other: `bleck` owns TPL, U8, LZ77, setup files and evt bytecode, and is
//! tested against a real disc.
//!
//! ⚠️ The manifest is the contract, not the directory listing. Scanning a
//! folder for `*.png` or `*.obj` would work today and lose everything `bleck`
//! knows about a file — which disc file it came from, which container member,
//! which Maya shape, what its original format was. None of that survives a
//! filename.
//!
//! Each loader records why it produced nothing rather than returning an error,
//! because the window is already open by then and needs to say what to do next.

pub mod catalog;
pub mod effects;
pub mod gltf;
pub mod mesh;
pub mod texture;

#[cfg(test)]
pub mod scratch;

pub use catalog::Catalog;
pub use effects::Library as EffectLibrary;
pub use mesh::Library as ModelLibrary;
