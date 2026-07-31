//! What `bleck` exported, read from the manifest it writes beside the PNGs.
//!
//! ⚠️ The manifest is the contract, not the directory listing. Scanning for
//! `*.png` would work today and lose everything `bleck` knows about an image —
//! which disc file it came from, which container member, what its original
//! format was. None of that survives a filename.

use serde::Deserialize;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

/// The file `bleck texture export` writes alongside the images.
const MANIFEST: &str = "textures.json";

#[derive(Debug, Deserialize)]
struct Manifest {
    textures: Vec<Entry>,
}

/// One exported image, as `bleck` described it.
#[derive(Debug, Deserialize, Clone)]
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
    /// The disc file it came from.
    #[serde(default)]
    pub source: String,
    /// The archive member, when the TPL was inside one.
    #[serde(default)]
    pub member: String,
}

impl Entry {
    /// `file://` URI, which is how egui's loader addresses a local image.
    pub fn uri(&self) -> String {
        format!("file://{}", self.path.display())
    }

    /// What the image is stored *as*, which a filename cannot say.
    pub fn describe(&self) -> String {
        format!("{}x{} {}", self.width, self.height, self.format)
    }
}

/// Why a folder produced nothing, so the window can say which.
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
                "No {MANIFEST} in {}.\nRun: bleck texture export --out {}",
                path.display(),
                path.display()
            ),
            Self::Unreadable(why) => format!("{MANIFEST} could not be read:\n{why}"),
        }
    }
}

#[derive(Default)]
pub struct Catalog {
    entries: Vec<Entry>,
    formats: BTreeSet<String>,
    problem: Option<Problem>,
}

impl Catalog {
    /// Read the manifest in `root`.
    ///
    /// A failure is recorded rather than returned: the window is already open,
    /// and the user needs to be told *what* to do about it, which `Problem`
    /// carries and a `Result` would not.
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

        let entries: Vec<Entry> = manifest
            .textures
            .into_iter()
            .map(|mut entry| {
                entry.path = root.join(&entry.path);
                entry
            })
            .collect();
        let formats = entries.iter().map(|e| e.format.clone()).collect();
        Self {
            entries,
            formats,
            problem: None,
        }
    }

    pub fn entries(&self) -> &[Entry] {
        &self.entries
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Paired with `len` because clippy asks for it; the UI branches on
    /// `problem()` and `root` instead, so nothing calls this yet.
    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Every format present, so the filter offers only what is actually here.
    pub fn formats(&self) -> impl Iterator<Item = &String> {
        self.formats.iter()
    }

    pub fn problem(&self) -> Option<&Problem> {
        self.problem.as_ref()
    }

    /// Indices matching a search and an optional format, in catalog order.
    pub fn matching(&self, search: &str, format: Option<&str>) -> Vec<usize> {
        let needle = search.to_lowercase();
        self.entries
            .iter()
            .enumerate()
            .filter(|(_, entry)| {
                format.is_none_or(|want| entry.format == want)
                    && (needle.is_empty() || entry.name.to_lowercase().contains(&needle))
            })
            .map(|(index, _)| index)
            .collect()
    }
}
