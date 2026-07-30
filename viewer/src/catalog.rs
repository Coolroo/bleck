//! What `bleck` exported, read from the manifest it writes beside the PNGs.
//!
//! ⚠️ The manifest is the contract, not the directory listing. Scanning for
//! `*.png` would work today and lose everything `bleck` knows about an image —
//! which disc file it came from, which container member, what its original
//! format was, and which mods edit it. None of that survives a filename.

use serde::Deserialize;
use std::path::{Path, PathBuf};

/// The file `bleck texture export` writes alongside the images.
const MANIFEST: &str = "textures.json";

#[derive(Debug, Deserialize)]
struct Manifest {
    textures: Vec<Entry>,
}

/// One exported image, as `bleck` described it.
#[derive(Debug, Deserialize)]
pub struct Entry {
    /// Stable identifier: the disc path, plus the member and index within it.
    pub name: String,
    /// The PNG, relative to the export folder. Made absolute on load.
    #[serde(rename = "file")]
    pub path: PathBuf,
    /// The GameCube format it was stored in — CMPR, RGB5A3, I4 and so on.
    #[serde(default)]
    pub format: String,
    #[serde(default)]
    pub width: u32,
    #[serde(default)]
    pub height: u32,
}

#[derive(Default)]
pub struct Catalog {
    entries: Vec<Entry>,
}

impl Catalog {
    /// Read the manifest in `root`. A missing or unreadable one yields an empty
    /// catalog rather than an error: the window is already open, and "no
    /// textures loaded" is a state the UI shows properly.
    pub fn load(root: &Path) -> Self {
        let Ok(text) = std::fs::read_to_string(root.join(MANIFEST)) else {
            return Self::default();
        };
        let Ok(manifest) = serde_json::from_str::<Manifest>(&text) else {
            return Self::default();
        };
        let entries = manifest
            .textures
            .into_iter()
            .map(|mut entry| {
                entry.path = root.join(&entry.path);
                entry
            })
            .collect();
        Self { entries }
    }

    pub fn entries(&self) -> &[Entry] {
        &self.entries
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }
}
