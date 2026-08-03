//! The manifest: every model the export folder declares, and what `bleck`
//! recorded about each.
//!
//! ⚠️ The manifest is the contract, not the directory listing — the rule for
//! this whole layer, stated once in `data`'s module doc. A filename cannot say
//! which disc file the model came from or which Maya shape inside it produced
//! these triangles, and both are how a model is identified.
//!
//! ⚠️ Geometry is read on demand, not at load. The manifest is a few hundred
//! bytes per model; the meshes are not, and a folder of them would sit in
//! memory for the sake of the one that is on screen.

use serde::Deserialize;
use std::path::{Path, PathBuf};

use super::Problem;
use crate::data::morph::ClipEntry;

/// The file `bleck model export` writes alongside the meshes.
pub(super) const MANIFEST: &str = "models.json";

#[derive(Debug, Deserialize)]
struct Manifest {
    models: Vec<Entry>,
}

/// One exported model, as `bleck` described it.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Entry {
    /// Stable identifier: the disc file the model came from.
    pub name: String,
    /// The Maya shape within that file — one disc file holds several.
    #[serde(default)]
    pub shape: String,
    /// The OBJ, relative to the export folder. Made absolute on load.
    #[serde(rename = "file")]
    pub path: PathBuf,
    /// The disc file the model was read out of.
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub positions: usize,
    #[serde(default)]
    pub faces: usize,
    #[serde(default)]
    pub triangles: usize,
    /// Share of the file's vertices the exported faces actually reach.
    #[serde(default)]
    pub coverage: f32,
    /// ⚠️ Set when the export is one shape record out of a file that holds
    /// many, which is currently every model. The viewport shows exactly what
    /// the OBJ contains, so a fragment looks like a broken model unless the
    /// window says otherwise.
    #[serde(default)]
    pub fragment: bool,
    /// Images the exporter embedded, and primitives it gave a material to —
    /// both counted by `bleck` from the bytes it had just written (D245).
    ///
    /// ⚠️ **This is the only cross-end check on the material chain.** The
    /// fixtures are written by this crate's own tests and would agree with a
    /// reader that had it wrong; these two numbers were produced by the other
    /// program from the same file.
    ///
    /// Not shown in the window: the facts row reports what the mesh file
    /// actually decoded, because a manifest that over-reported was the whole
    /// failure of D245.
    #[serde(default)]
    #[allow(dead_code)]
    pub textures: usize,
    /// Distinct glTF materials the primitives name.
    ///
    /// ⚠️ **Not the same as `textures` any more** (D247). A two-layer shape's
    /// material reaches two images, so `textures` exceeds this on the four
    /// models that carry one — and this reader decodes per material, so this is
    /// the number `paints()` can be held to.
    #[serde(default)]
    #[allow(dead_code)]
    pub materials: usize,
    /// Materials declaring a second layer in `extras`.
    #[serde(default)]
    #[allow(dead_code)]
    pub masked: usize,
    #[serde(default)]
    #[allow(dead_code)]
    pub painted: usize,
    /// ⚠️ Set when `bleck --guess-textures` gave a multi-shape model image 0
    /// anyway. The image is almost certainly the wrong one, so a test asserting
    /// what a texture *looks like* must skip these (D229).
    #[serde(default)]
    pub texture_guessed: bool,
    /// Bounds as `bleck` measured them. Shown as facts; the camera fits itself
    /// to the bounds of the geometry actually parsed, so a wrong number here
    /// mis-labels a model rather than mis-framing it.
    #[serde(default)]
    pub min: [f32; 3],
    #[serde(default)]
    pub max: [f32; 3],
    /// Clips written into the `.glb`, so a list can say how many a model has
    /// without opening it.
    #[serde(default)]
    pub animations: usize,
    /// ⚠️ Clips the exporter's per-file budget left out. Reported, because a
    /// model that exported 3 of its 94 clips otherwise reads as a model with
    /// three animations.
    #[serde(default)]
    pub animations_dropped: usize,
    /// Every clip the file holds, written or not.
    #[serde(default)]
    pub clips: Vec<ClipEntry>,
}

impl Entry {
    /// Size in the terms that decide whether a model will draw usefully.
    pub fn describe(&self) -> String {
        format!("{} verts, {} tris", self.positions, self.triangles)
    }

    /// What a copy puts on the clipboard.
    ///
    /// ⚠️ The disc file's name, not the exported OBJ's path. `name` is what
    /// this model is called everywhere else; the OBJ is a temporary file on
    /// one machine.
    pub fn copy_text(&self) -> String {
        self.name.clone()
    }

    /// The disc file the model was read out of, for the exports that recorded
    /// one.
    pub fn source_text(&self) -> Option<String> {
        (!self.source.is_empty()).then(|| self.source.clone())
    }

    /// The extent `bleck` recorded, which says what units a model is in.
    pub fn extent(&self) -> String {
        format!(
            "{:.1} x {:.1} x {:.1}",
            self.max[0] - self.min[0],
            self.max[1] - self.min[1],
            self.max[2] - self.min[2]
        )
    }
}
/// Every model the export folder declares.
#[derive(Default)]
pub struct Library {
    entries: Vec<Entry>,
    problem: Option<Problem>,
}

impl Library {
    /// Read the manifest in `root`.
    ///
    /// A failure is recorded rather than returned, for the same reason as
    /// `Catalog::load`: the window is already open and needs to say what to do
    /// about it, which `Problem` carries and a `Result` would not.
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
            .models
            .into_iter()
            .map(|mut entry| {
                entry.path = root.join(&entry.path);
                entry
            })
            .collect();
        Self {
            entries,
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
    /// `problem()` and the match count instead, so only the tests call this.
    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn problem(&self) -> Option<&Problem> {
        self.problem.as_ref()
    }

    /// Indices matching a search, in manifest order. Shape names are searched
    /// as well as model names: one disc file holds several shapes, and the
    /// shape is what tells them apart.
    #[cfg(test)]
    pub fn matching(&self, search: &str) -> Vec<usize> {
        self.filtered(search, false)
    }

    /// Models matching the search, optionally only the whole ones.
    ///
    /// ⚠️ **A fragment does not look like missing data, it looks like a
    /// rendering fault** — a corner torn into the middle of an otherwise
    /// recognisable character. 732 of 864 exported models are fragments
    /// (D211), so hiding them is the difference between a viewer that looks
    /// broken and one that looks partial.
    pub fn filtered(&self, search: &str, whole_only: bool) -> Vec<usize> {
        let needle = search.to_lowercase();
        self.entries
            .iter()
            .enumerate()
            .filter(|(_, entry)| !whole_only || !entry.fragment)
            .filter(|(_, entry)| {
                needle.is_empty()
                    || entry.name.to_lowercase().contains(&needle)
                    || entry.shape.to_lowercase().contains(&needle)
            })
            .map(|(index, _)| index)
            .collect()
    }

    /// How many models the whole-only filter would keep.
    pub fn whole(&self) -> usize {
        self.entries.iter().filter(|entry| !entry.fragment).count()
    }
}
