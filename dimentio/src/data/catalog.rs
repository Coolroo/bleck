//! The texture manifest `bleck texture export` writes, and the PNGs it names.
//!
//! ⚠️ The manifest is the contract, not the directory listing — the rule for
//! this whole layer, stated once in `data`'s module doc. Scanning for `*.png`
//! would work today and lose everything `bleck` knows about an image: which
//! disc file it came from, which container member, what its original format
//! was. None of that survives a filename.

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

    /// What a copy puts on the clipboard.
    ///
    /// ⚠️ The stable identifier, not the exported PNG's path. `name` is what
    /// this image is called everywhere else — in `bleck`'s own output, in a
    /// manifest, in a bug report — and the PNG is a temporary file on one
    /// machine.
    pub fn copy_text(&self) -> String {
        self.name.clone()
    }

    /// The disc file behind the image, for the exports that recorded one.
    pub fn source_text(&self) -> Option<String> {
        (!self.source.is_empty()).then(|| self.source.clone())
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

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(name: &str, source: &str) -> Entry {
        Entry {
            name: name.to_owned(),
            path: PathBuf::from("0001.png"),
            format: "CMPR".to_owned(),
            width: 64,
            height: 64,
            source: source.to_owned(),
            member: String::new(),
        }
    }

    /// ⚠️ The name, not the PNG. The exported file is a temporary on one
    /// machine, so a clipboard full of those paths names nothing anyone else
    /// can look up.
    #[test]
    fn a_texture_copies_its_name_and_the_disc_file_behind_it() {
        let shown = entry("files/eff/effdata.tpl#0", "files/eff/effdata.tpl");
        assert_eq!(shown.copy_text(), "files/eff/effdata.tpl#0");
        assert_eq!(
            shown.source_text(),
            Some("files/eff/effdata.tpl".to_owned())
        );
        assert_ne!(
            shown.copy_text(),
            shown.path.display().to_string(),
            "the export's own file is not what names this image"
        );
    }

    /// Some catalog rows carry no source at all, and a "Copy source path" that
    /// put nothing on the clipboard reads as a copy that failed.
    #[test]
    fn a_texture_with_no_source_offers_nothing_for_it() {
        assert_eq!(entry("loose.png#0", "").source_text(), None);
    }

    /// Disc paths are plain ASCII and go to the clipboard as they are stored.
    /// Nothing is escaped, quoted or trimmed on the way.
    #[test]
    fn a_name_is_copied_exactly_as_the_manifest_holds_it() {
        let odd = entry("files/map/aa1_01.tpl#12 (dup)", "files/map/aa1_01.tpl");
        assert_eq!(odd.copy_text(), "files/map/aa1_01.tpl#12 (dup)");
        assert_eq!(odd.source_text().as_deref(), Some("files/map/aa1_01.tpl"));
    }
}
