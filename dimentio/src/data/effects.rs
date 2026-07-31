//! What `bleck effect export` wrote: the effect table, each effect's parts,
//! and the transform rows behind them. **This is the data layer** — the panels
//! that draw it are in `app::effects`.
//!
//! ⚠️ The manifest is the contract, not the directory listing — the rule for
//! this whole layer, stated once in `data`'s module doc. Nothing here reads
//! `effdata.dat`; `bleck` owns that format and is tested against a real disc.
//!
//! ⛔ **Which image a part draws is not decoded.** Six candidate fields have
//! been refuted, so this module deliberately offers no way to ask. `bank`
//! selects the effect system's *whole* image bank by disc file, which is the
//! only link between a part and an image that can be drawn honestly. Indexing
//! that bank by a part's index — or by any other field — would manufacture a
//! mapping that reads as a measured fact. See `docs/decision-log.md` D210.

use serde::Deserialize;
use std::path::{Path, PathBuf};

use super::catalog;

/// The file `bleck effect export` writes.
const MANIFEST: &str = "effects.json";

/// The rate the game counts animation frames at, and so the rate that turns a
/// part's frame count into the seconds shown beside it.
const FRAME_RATE: f32 = 60.0;

#[derive(Debug, Deserialize)]
struct Manifest {
    /// The disc file holding the effect system's images.
    #[serde(default)]
    textures: String,
    effects: Vec<Entry>,
}

/// One effect, as `bleck` described it.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Entry {
    /// The effect's own name, which is what the game's code calls it by.
    pub name: String,
    /// Position in the effect table.
    #[serde(default)]
    pub index: usize,
    /// How long the whole effect runs — the longest of its parts.
    #[serde(default)]
    pub seconds: f32,
    #[serde(default)]
    pub parts: Vec<Part>,
    #[serde(default)]
    pub rows: Vec<Row>,
}

impl Entry {
    /// The two numbers that decide whether an effect is worth opening.
    pub fn describe(&self) -> String {
        format!("{} part(s) · {:.2}s", self.parts.len(), self.seconds)
    }

    /// What a copy puts on the clipboard: the name the game's own code calls
    /// this effect by, which is what someone reading that code has to search
    /// for. Not the table position, which is meaningless on its own.
    pub fn copy_text(&self) -> String {
        self.name.clone()
    }

    /// Total frames, derived from the duration rather than read: the export
    /// records seconds per effect and frames only per part.
    pub fn frames(&self) -> u32 {
        frame_at(self.seconds)
    }

    /// The parts still running `time` seconds in, as indices into `parts`.
    pub fn active_at(&self, time: f32) -> Vec<usize> {
        self.parts
            .iter()
            .enumerate()
            .filter(|(_, part)| part.active_at(time))
            .map(|(index, _)| index)
            .collect()
    }
}

/// One part of an effect: a named sub-animation with its own duration.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Part {
    /// The suffix the game composes onto the effect's name — `A`, `B`, and so on.
    pub name: String,
    /// Effect name and part name joined, which is the name the game looks up.
    #[serde(default)]
    pub composed: String,
    /// Position in the part table, running across the whole file.
    #[serde(default)]
    pub index: usize,
    /// Duration in frames, counted inclusively at 60 Hz: 61 frames is one
    /// second, and a 1-frame part lasts zero.
    #[serde(default)]
    pub frames: u32,
    #[serde(default)]
    pub seconds: f32,
}

impl Part {
    /// Whether this part is still running `time` seconds into the effect.
    ///
    /// ⚠️ The end is inclusive because the frame count is. `seconds` names the
    /// part's last frame, not the frame after it, so an exclusive end would
    /// make every 1-frame part — of which the export holds many — never active
    /// at all, and a part would stop one frame early.
    pub fn active_at(&self, time: f32) -> bool {
        (0.0..=self.seconds).contains(&time)
    }

    pub fn describe(&self) -> String {
        format!("{} frames · {:.2}s", self.frames, self.seconds)
    }

    /// What a copy puts on the clipboard.
    ///
    /// ⚠️ The composed name, not the suffix. `name` is `A` or `C` on its own
    /// and names nothing outside the effect it belongs to; `composed` is what
    /// the game looks a part up by. An export that recorded no composed name
    /// falls back to the suffix, which is all there is.
    pub fn copy_text(&self) -> String {
        if self.composed.is_empty() {
            self.name.clone()
        } else {
            self.composed.clone()
        }
    }
}

/// One row of an effect's transform data: four floats, as stored.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Row {
    /// Position in the file's row table, which is shared across effects.
    #[serde(default)]
    pub index: usize,
    #[serde(default)]
    pub values: Vec<f32>,
}

impl Row {
    pub fn describe(&self) -> String {
        self.values
            .iter()
            .map(|value| format!("{value:>10.5}"))
            .collect::<Vec<_>>()
            .join(" ")
    }

    /// The row read as a vector. A length of 1 is what a rotation or scale row
    /// of a transform matrix looks like, so it says whether a row is being
    /// read the right way round without claiming what it transforms.
    pub fn magnitude(&self) -> f32 {
        self.values
            .iter()
            .map(|value| value * value)
            .sum::<f32>()
            .sqrt()
    }
}

/// The frame number `time` seconds in, counting the first frame as 1 — the
/// same inclusive convention the durations use.
pub fn frame_at(time: f32) -> u32 {
    (time.max(0.0) * FRAME_RATE).round() as u32 + 1
}

/// The timeline an effect scrubs along. Shared with the model viewport, which
/// plays a morph clip the same way; it lives in `transport`.
pub use super::transport::Playback;

/// Indices of the images that make up the effect system's bank.
///
/// ⛔ This is the whole bank in catalog order, and the order carries no
/// meaning beyond that. **No part is known to draw any particular one of
/// these.** Do not index the result by a part's index, frame count or table
/// position: every one of those has been tried and refuted (D210), and a
/// wrong pairing shown in a window looks exactly like a right one.
///
/// An export that names no bank selects nothing, rather than every image whose
/// source happens to be blank.
pub fn bank(entries: &[catalog::Entry], source: &str) -> Vec<usize> {
    if source.is_empty() {
        return Vec::new();
    }
    entries
        .iter()
        .enumerate()
        .filter(|(_, entry)| entry.source == source)
        .map(|(index, _)| index)
        .collect()
}

/// Why a folder produced no effects, so the window can say which.
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
                "No {MANIFEST} in {}.\nRun: bleck effect export --out {}",
                path.display(),
                path.display()
            ),
            Self::Unreadable(why) => format!("{MANIFEST} could not be read:\n{why}"),
        }
    }
}

/// Every effect the export folder declares, and the disc file its images
/// come from.
#[derive(Default)]
pub struct Library {
    entries: Vec<Entry>,
    textures: String,
    problem: Option<Problem>,
}

impl Library {
    /// Read the manifest in `root`.
    ///
    /// A failure is recorded rather than returned, for the same reason as
    /// `Catalog::load`: the window is already open and needs to be told what
    /// to do about it, which `Problem` carries and a `Result` would not.
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
        Self {
            entries: manifest.effects,
            textures: manifest.textures,
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

    /// The disc file the effect system's images live in, as the exporter
    /// recorded it. Empty when the manifest did not say.
    pub fn textures(&self) -> &str {
        &self.textures
    }

    pub fn problem(&self) -> Option<&Problem> {
        self.problem.as_ref()
    }

    /// Indices matching a search, in manifest order. Part names are searched
    /// as well as effect names, because the composed name is what appears in
    /// the game's own code and is often the only name someone has.
    pub fn matching(&self, search: &str) -> Vec<usize> {
        let needle = search.to_lowercase();
        self.entries
            .iter()
            .enumerate()
            .filter(|(_, entry)| {
                needle.is_empty()
                    || entry.name.to_lowercase().contains(&needle)
                    || entry
                        .parts
                        .iter()
                        .any(|part| part.composed.to_lowercase().contains(&needle))
            })
            .map(|(index, _)| index)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A directory of our own under the system temp dir, removed on drop, so
    /// the manifest tests touch the real filesystem without a dev-dependency.
    struct Scratch {
        path: PathBuf,
    }

    impl Scratch {
        fn new(tag: &str) -> Self {
            static NEXT: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
            let count = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let path = std::env::temp_dir()
                .join(format!("dimentio-eff-{tag}-{}-{count}", std::process::id()));
            std::fs::create_dir_all(&path).expect("scratch dir");
            Self { path }
        }

        fn write(&self, name: &str, text: &str) {
            std::fs::write(self.path.join(name), text).expect("scratch file");
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.path);
        }
    }

    /// The manifest as `bleck effect export` writes it today, keys and all —
    /// `chaos`, whose rows hold the 72° rotation, and `hit`.
    ///
    /// ⚠️ Unknown keys must stay tolerated. `models.json` gained three after
    /// its reader was written, and a stricter one would have refused every
    /// export the day they landed.
    const LIVE_MANIFEST: &str = r#"{"schema": 1,
      "textures": "files/eff/effdata.tpl",
      "effects": [
        {"name": "hit", "index": 1, "seconds": 0.4667,
         "parts": [{"name": "A", "composed": "hitA", "index": 2,
                    "frames": 29, "seconds": 0.4667}],
         "rows": [{"index": 497, "values": [0.0, 0.0, 1.0, 0.0]}]},
        {"name": "chaos", "index": 16, "seconds": 3.0,
         "parts": [{"name": "A", "composed": "chaosA", "index": 61,
                    "frames": 181, "seconds": 3.0},
                   {"name": "C", "composed": "chaosC", "index": 62,
                    "frames": 61, "seconds": 1.0}],
         "rows": [{"index": 498, "values": [0.30902, 0.95106, 0.0, 0.0]}],
         "something_added_later": [1, 2, 3]}
      ]}"#;

    fn library() -> Library {
        let scratch = Scratch::new("live");
        scratch.write("effects.json", LIVE_MANIFEST);
        Library::load(&scratch.path)
    }

    #[test]
    fn reads_the_manifest_the_exporter_writes_today() {
        let library = library();
        assert_eq!(library.problem(), None);
        assert_eq!(library.len(), 2);
        assert_eq!(library.textures(), "files/eff/effdata.tpl");

        let hit = &library.entries()[0];
        assert_eq!(hit.index, 1);
        assert_eq!(hit.parts.len(), 1);
        assert_eq!(hit.parts[0].composed, "hitA");
        assert_eq!(hit.parts[0].frames, 29);
        assert_eq!(hit.parts[0].describe(), "29 frames · 0.47s");
        assert_eq!(hit.describe(), "1 part(s) · 0.47s");
        assert_eq!(hit.rows[0].index, 497);
        assert_eq!(hit.rows[0].values, vec![0.0, 0.0, 1.0, 0.0]);
    }

    #[test]
    fn a_missing_manifest_names_the_folder_and_the_command() {
        let scratch = Scratch::new("bare");
        let library = Library::load(&scratch.path);
        assert_eq!(
            library.problem(),
            Some(&Problem::NoManifest(scratch.path.clone()))
        );
        let said = library.problem().expect("a problem").describe();
        assert!(said.contains("bleck effect export"), "{said}");
        assert!(said.contains(&scratch.path.display().to_string()), "{said}");
    }

    #[test]
    fn broken_json_is_reported_not_panicked() {
        let scratch = Scratch::new("broken");
        scratch.write("effects.json", "{\"effects\": [");
        let library = Library::load(&scratch.path);
        assert!(matches!(library.problem(), Some(Problem::Unreadable(_))));
        assert!(library.is_empty());
        assert_eq!(library.textures(), "");
    }

    #[test]
    fn search_matches_an_effect_or_one_of_its_part_names() {
        let library = library();
        assert_eq!(library.matching(""), vec![0, 1]);
        assert_eq!(library.matching("CHAOS"), vec![1]);
        assert_eq!(library.matching("chaosC"), vec![1]);
        assert!(library.matching("dimentio").is_empty());
    }

    /// The boundaries the timeline depends on. ⚠️ The end is inclusive: the
    /// duration names the part's last frame, not the one after it.
    #[test]
    fn a_part_is_active_from_zero_to_its_own_duration_inclusive() {
        let part = Part {
            seconds: 1.0,
            frames: 61,
            ..Default::default()
        };
        assert!(part.active_at(0.0), "the first frame");
        assert!(part.active_at(0.5), "halfway");
        assert!(part.active_at(1.0), "the last frame, not one past it");
        assert!(!part.active_at(1.0001), "past the end");
        assert!(!part.active_at(-0.1), "before the effect started");
    }

    /// 1-frame parts are common in the export — an exclusive end would make
    /// every one of them invisible at every time.
    #[test]
    fn a_single_frame_part_is_active_only_at_the_start() {
        let part = Part {
            seconds: 0.0,
            frames: 1,
            ..Default::default()
        };
        assert!(part.active_at(0.0));
        assert!(!part.active_at(0.001));
    }

    #[test]
    fn the_active_parts_are_the_ones_still_running() {
        let library = library();
        let chaos = &library.entries()[1];
        assert_eq!(chaos.active_at(0.0), vec![0, 1], "both, at the start");
        assert_eq!(chaos.active_at(1.0), vec![0, 1], "the shorter one's last");
        assert_eq!(chaos.active_at(2.0), vec![0], "the shorter one has ended");
        assert!(chaos.active_at(3.5).is_empty(), "past the whole effect");
    }

    /// 61 frames is one second, and the first frame is frame 1 — the same
    /// inclusive counting the durations use.
    #[test]
    fn frame_numbers_start_at_one_and_count_inclusively() {
        assert_eq!(frame_at(0.0), 1);
        assert_eq!(frame_at(1.0), 61);
        let library = library();
        let chaos = &library.entries()[1];
        assert_eq!(chaos.frames(), 181, "3s at 60Hz, counted inclusively");
    }

    /// ⚠️ The composed name, not the suffix. `A` names nothing outside the
    /// effect it belongs to; `chaosA` is what the game looks a part up by and
    /// what someone reading the game's code has to search for.
    #[test]
    fn a_part_copies_the_composed_name_rather_than_its_suffix() {
        let library = library();
        let chaos = &library.entries()[1];
        assert_eq!(chaos.copy_text(), "chaos");
        assert_eq!(chaos.parts[0].copy_text(), "chaosA");
        assert_ne!(chaos.parts[0].copy_text(), chaos.parts[0].name);
        assert_ne!(
            chaos.copy_text(),
            chaos.index.to_string(),
            "a table position names nothing on its own"
        );
    }

    /// An export that recorded no composed name leaves the suffix, which is
    /// all there is to copy.
    #[test]
    fn a_part_with_no_composed_name_falls_back_to_the_suffix() {
        let bare = Part {
            name: "A".to_owned(),
            composed: String::new(),
            ..Default::default()
        };
        assert_eq!(bare.copy_text(), "A");
    }

    #[test]
    fn a_transform_row_reports_its_length() {
        let row = Row {
            index: 498,
            values: vec![0.30902, 0.95106, 0.0, 0.0],
        };
        assert!((row.magnitude() - 1.0).abs() < 1e-4, "{}", row.magnitude());
        assert!(row.describe().contains("0.95106"), "{}", row.describe());
    }

    const TEXTURE_MANIFEST: &str = r#"{"schema": 1, "textures": [
      {"name": "files/eff/effdata.tpl#0", "file": "a.png", "format": "CMPR",
       "width": 8, "height": 32, "source": "files/eff/effdata.tpl"},
      {"name": "files/map/aa1_01.tpl#0", "file": "b.png", "format": "CMPR",
       "width": 64, "height": 64, "source": "files/map/aa1_01.tpl"},
      {"name": "files/eff/effdata.tpl#1", "file": "c.png", "format": "RGB5A3",
       "width": 16, "height": 16, "source": "files/eff/effdata.tpl"},
      {"name": "loose.png", "file": "d.png", "format": "I4",
       "width": 4, "height": 4}
    ]}"#;

    #[test]
    fn the_bank_is_only_the_effect_systems_own_disc_file() {
        let scratch = Scratch::new("bank");
        scratch.write("textures.json", TEXTURE_MANIFEST);
        let catalog = catalog::Catalog::load(&scratch.path);
        assert_eq!(catalog.len(), 4);

        let picked = bank(catalog.entries(), "files/eff/effdata.tpl");
        assert_eq!(picked, vec![0, 2]);
        for index in picked {
            assert_eq!(catalog.entries()[index].source, "files/eff/effdata.tpl");
        }
    }

    /// ⚠️ Some catalog entries carry no source at all. Matching on an empty
    /// name would sweep every one of them into the bank and label them as the
    /// effect system's images.
    #[test]
    fn an_unnamed_bank_selects_nothing_rather_than_every_sourceless_image() {
        let scratch = Scratch::new("nobank");
        scratch.write("textures.json", TEXTURE_MANIFEST);
        let catalog = catalog::Catalog::load(&scratch.path);
        assert!(bank(catalog.entries(), "").is_empty());
    }
}
