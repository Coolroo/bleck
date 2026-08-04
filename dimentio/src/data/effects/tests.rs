//! The manifest reader, against the shapes `bleck effect export` really
//! writes — including one that predates half the fields, because an older
//! export must still load rather than being refused.

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
        let path =
            std::env::temp_dir().join(format!("dimentio-eff-{tag}-{}-{count}", std::process::id()));
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
    // ⚠️ The manifest still carries a `rows` key on older exports; an
    // unknown key must stay tolerated rather than refusing the file.
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

/// One draw, so a derivation can be asked about a single set of inputs.
fn a_draw(blend: u32, sampler: Option<i32>, translucent: bool) -> Draw {
    Draw {
        blend,
        translucent,
        sampler,
        ..Default::default()
    }
}

/// One sampler row declaring an alpha type and nothing else.
fn a_sampler(alpha_type: Option<u32>) -> SamplerDef {
    SamplerDef {
        alpha_type,
        ..Default::default()
    }
}

/// ✅ The three the sampler alone decides, at an alpha that forces nothing.
///
/// ⚠️ **255 is the control**, and it has to be: every input below forces mode 3,
/// so a derivation that always answered 3 would pass each of them and only this
/// would notice.
#[test]
fn the_samplers_alpha_type_decides_the_mode_when_nothing_overrides_it() {
    let ask =
        |kind: u32| a_draw(BLEND_DERIVED, Some(0), false).blend_mode(&[a_sampler(Some(kind))], 255);
    assert_eq!(ask(0), BLEND_OPAQUE);
    assert_eq!(ask(1), BLEND_CUTOUT);
    assert_eq!(ask(2), BLEND_TRANSLUCENT);
}

/// ⛔ **The descriptor bit alone forces alpha blending**, whatever the sampler
/// declares — `ori r0,r0,2` at `0x8005c960`. 211 draws set it, and `bleck`
/// masked it away until D283 because the attribute stride needs it gone.
#[test]
fn a_translucent_descriptor_bit_forces_alpha_blending_over_an_opaque_sampler() {
    let samplers = [a_sampler(Some(0))];
    assert_eq!(
        a_draw(BLEND_DERIVED, Some(0), false).blend_mode(&samplers, 255),
        BLEND_OPAQUE,
        "the control: without the bit this draw is opaque"
    );
    assert_eq!(
        a_draw(BLEND_DERIVED, Some(0), true).blend_mode(&samplers, 255),
        BLEND_TRANSLUCENT
    );
}

/// ⚠️ **Strictly between**, which is what makes this a runtime value rather than
/// a file one: 0 and 255 leave the sampler's own answer standing and everything
/// between them does not. 341 draws change mode the moment an instance fades.
#[test]
fn an_alpha_strictly_inside_the_range_forces_alpha_blending_and_the_ends_do_not() {
    let samplers = [a_sampler(Some(0))];
    let at = |alpha: u8| a_draw(BLEND_DERIVED, Some(0), false).blend_mode(&samplers, alpha);
    assert_eq!(at(255), BLEND_OPAQUE);
    assert_eq!(at(0), BLEND_OPAQUE);
    assert_eq!(at(254), BLEND_TRANSLUCENT);
    assert_eq!(at(1), BLEND_TRANSLUCENT);
}

/// ⛔ **A declared selector is not derived from.** 432 draws name 4, 5 or 6, and
/// running them through the derivation would turn every glow into plain alpha.
#[test]
fn a_declared_selector_survives_a_sampler_that_would_have_derived_otherwise() {
    let samplers = [a_sampler(Some(0))];
    for selector in [1, 2, 4, 5, 6] {
        assert_eq!(
            a_draw(selector, Some(0), true).blend_mode(&samplers, 128),
            selector,
            "selector {selector} was overwritten by the derivation"
        );
    }
}

/// ⚠️ **An export predating the field keeps plain alpha.** Reading a missing
/// `alpha_type` as 0 would turn 2,528 draws of every schema-4 export opaque —
/// the trap D280's node alpha and D281's UV scale each hit from the other side.
#[test]
fn a_sampler_with_no_recorded_alpha_type_keeps_the_plain_alpha_every_older_reader_used() {
    assert_eq!(
        a_draw(BLEND_DERIVED, Some(0), false).blend_mode(&[a_sampler(None)], 255),
        BLEND_TRANSLUCENT
    );
    assert_eq!(
        a_draw(BLEND_DERIVED, Some(0), false).blend_mode(&[], 255),
        BLEND_TRANSLUCENT,
        "an export with no sampler table at all"
    );
    assert_eq!(
        a_draw(BLEND_DERIVED, None, false).blend_mode(&[a_sampler(Some(0))], 255),
        BLEND_TRANSLUCENT,
        "a draw whose material names no texture"
    );
}

/// ⛔ **Selector 0 cannot reach additive** (D283). No record carries an alpha
/// type of 3, but `kind + 1` would turn one into mode 4 — a glow out of a
/// derivation that provably cannot produce one.
#[test]
fn an_alpha_type_no_record_carries_cannot_derive_an_additive_glow() {
    for kind in 0..4 {
        let mode = a_draw(BLEND_DERIVED, Some(0), false).blend_mode(&[a_sampler(Some(kind))], 255);
        assert!(
            (BLEND_OPAQUE..=BLEND_TRANSLUCENT).contains(&mode),
            "alpha type {kind} derived mode {mode}"
        );
    }
}
