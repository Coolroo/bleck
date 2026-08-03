//! The real export, when one happens to be on this machine.
//!
//! ⚠️ `work/` is git-ignored, so these skip rather than fail on a fresh clone
//! or in CI. They exist because every fixture in `tests` is written by this
//! crate: an effect built there cannot catch a real one whose rows are all
//! zero, whose parts outnumber its rows, or which carries no parts at all.

use super::tests::{covered, shades, shot};
use super::*;
use crate::data::effects::Library;
use std::path::{Path, PathBuf};

fn export() -> Option<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()?
        .join("work")
        .join("export");
    root.join("effects.json").is_file().then_some(root)
}

#[test]
fn every_real_effect_draws_at_its_first_frame_and_stops_after_its_last() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    assert!(!library.entries().is_empty(), "the manifest named nothing");

    let mut drawn = 0;
    for entry in library.entries() {
        if entry.parts.is_empty() {
            assert_eq!(covered(&shot(entry, 0.0, None)), 0, "{}", entry.name);
            continue;
        }
        assert!(
            covered(&shot(entry, 0.0, None)) > 100,
            "{} drew nothing at its first frame",
            entry.name
        );
        assert_eq!(
            covered(&shot(entry, entry.seconds + 0.5, None)),
            0,
            "{} was still drawing past its last frame",
            entry.name
        );
        drawn += 1;
    }
    assert!(drawn > 100, "only {drawn} effects drew");
}

/// `chaos` is the effect the five-fold ring was measured on, and two of its
/// four rows are the same direction — so it is also the case the outward
/// spread exists for. Four parts, four separate quads.
#[test]
fn chaos_draws_four_separate_parts() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let entry = library
        .entries()
        .iter()
        .find(|entry| entry.name == "chaos")
        .expect("chaos is in every export");
    assert_eq!(entry.parts.len(), 4);

    let places: Vec<Vec3> = (0..4).map(|part| placement(entry, part, 1.0)).collect();
    for (one, place) in places.iter().enumerate() {
        for (two, other) in places.iter().enumerate().skip(one + 1) {
            assert!(
                (*place - *other).length() > 2.0 * HALF,
                "parts {one} and {two} overlap at {place:?} and {other:?}"
            );
        }
    }
    assert_eq!(shades(&shot(entry, 0.0, None)).len(), 4);
}
