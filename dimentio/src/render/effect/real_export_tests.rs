//! The real export, when one happens to be on this machine.
//!
//! ⚠️ `work/` is git-ignored, so these skip rather than fail on a fresh clone
//! or in CI. They exist because every fixture in `tests` is written by this
//! crate: an effect built there cannot catch a real one whose rows are all
//! zero, whose parts outnumber its rows, or which carries no parts at all.

use super::tests::{covered, shades, shot};
use super::*;
use crate::data::effects::Library;
use crate::data::texture::Sampling;
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
    let mut transparent = 0;
    for entry in library.entries() {
        if entry.parts.is_empty() {
            assert_eq!(covered(&shot(entry, 0.0, None)), 0, "{}", entry.name);
            continue;
        }
        // ⚠️ **Both directions, decided by the manifest.** A draw whose
        // material register carries alpha 0 at frame 0 paints nothing there, so
        // an effect whose every draw does must come out empty — and every other
        // effect must still fill its first frame.
        //
        // ⛔ **At frame 0, not "for its whole life".** D280 read `spindash`'s
        // `(255, 255, 255, 0)` as a permanently transparent effect; the
        // register is its curve's *starting* value and the alpha reaches 255 by
        // mid-life (D281). What the register decides is this one frame.
        if !entry
            .parts
            .iter()
            .flat_map(|part| &part.draws)
            .any(|draw| draw.tint().alpha > 0)
        {
            assert_eq!(
                covered(&shot(entry, 0.0, None)),
                0,
                "{} has no draw with any alpha and was drawn anyway",
                entry.name
            );
            transparent += 1;
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
    // ⚠️ Pinned, because the branch above is only evidence while something
    // takes it. At zero it would assert nothing and still read as a pass.
    assert_eq!(
        transparent, 1,
        "the export no longer holds exactly one wholly transparent effect"
    );
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

/// ⛔ **D280's reading of `spindash` is refuted** (D281). Its material register
/// is `(255, 255, 255, 0)` and was taken for the export's one wholly
/// transparent effect — "applying the data and reporting the consequence". The
/// register is only the *starting* value: a tag-3 curve raises the alpha to 255
/// by the middle of its 91 frames and returns it to 0. Reading the register
/// alone renders a spin-dash puff as nothing at all.
#[test]
fn spindash_is_dark_at_its_first_frame_and_lit_by_its_own_material_curve() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let entry = library
        .entries()
        .iter()
        .find(|entry| entry.name == "spindash")
        .expect("spindash is in every export");
    let draw = &entry.parts[0].draws[0];
    assert_eq!(draw.tint().alpha, 0, "the static register is no longer 0");

    let row = library
        .materials()
        .get(draw.material().expect("spindash names a material"))
        .expect("the material table holds it");
    assert!(
        !row.curves.is_empty(),
        "spindash's material carries no curve, so D280's reading stands"
    );
    assert_eq!(row.at(library.curves(), 0.0).alpha, 0, "frame 0 is dark");
    let peak = (0..entry.frames())
        .map(|frame| row.at(library.curves(), frame as f32).alpha)
        .max()
        .unwrap_or(0);
    assert!(peak > 200, "the curve only reached alpha {peak}");
}

/// The three claims on section 10 that D278 measured, seen from the manifest:
/// every draw naming a material or a sampler resolves, and enough of them carry
/// a curve run that dropping either evaluator would be visible.
#[test]
fn every_draw_resolves_its_material_and_its_sampler() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    assert_eq!(library.materials().len(), 524, "section 5 is 524 records");
    assert_eq!(library.samplers().len(), 350, "section 4 is 350 records");

    let mut named = 0;
    let mut textured = 0;
    for draw in library
        .entries()
        .iter()
        .flat_map(|entry| &entry.parts)
        .flat_map(|part| &part.draws)
    {
        let at = draw.material().expect("every draw names a material");
        assert!(at < library.materials().len(), "material {at} is not in the                 table, so the export and the reader disagree");
        named += 1;
        if let Some(sampler) = draw.sampler() {
            assert!(
                sampler < library.samplers().len(),
                "sampler {sampler}                     is not in the table"
            );
            assert_eq!(
                library.samplers()[sampler].image,
                Some(draw.image),
                "the sampler row names a different image from the draw"
            );
            textured += 1;
        } else {
            assert!(draw.image().is_none(), "a draw with no sampler still                     named an image, so one of the two hops is wrong");
        }
    }
    assert_eq!(named, 2_960, "section 8 is 2,960 draws");
    assert!(textured > 2_000, "only {textured} draws reached a texture");

    // ⚠️ The teeth: the tables have to *animate*, not merely exist. 97 of 524
    // materials and 103 of 350 textures carry a run (D278), and an export that
    // wrote the records but dropped the runs would pass everything above.
    let animated = |curves: usize| curves > 0;
    assert_eq!(
        library
            .materials()
            .iter()
            .filter(|m| animated(m.curves.len()))
            .count(),
        97
    );
    assert_eq!(
        library
            .samplers()
            .iter()
            .filter(|s| animated(s.curves.len()))
            .count(),
        103
    );
}

/// ⛔ **The failure mode D278 named**, measured on the real export rather than
/// on a fixture: an effect whose pose is byte-identical across two frames while
/// its colour or UV data moves must not render as a still.
#[test]
fn a_frozen_pose_still_changes_the_frame_where_the_data_moves() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let entry = library
        .entries()
        .iter()
        .find(|entry| entry.name == "map_derkness")
        .expect("map_derkness is in every export");
    let art = Art {
        images: &[],
        meshes: library.meshes(),
        nodes: library.nodes(),
        curves: library.curves(),
        materials: library.materials(),
        samplers: library.samplers(),
    };
    // Two times in the tail D278 measured as frozen: 361 of this effect's 601
    // frames hold the same pose.
    let camera = Camera::fit(bounds(entry, Some(art)));
    let posed = |time: f32| {
        let drawn = quads(entry, time, &camera, Some(art));
        drawn
            .pieces
            .iter()
            .map(|quad| quad.mesh.positions().to_vec())
            .collect::<Vec<Vec<Vec3>>>()
    };
    // ⚠️ **The control, and the reason this test exists at all.** Before D281
    // the ground sheet was skipped for having a singular transform, so the tail
    // drew nothing and there was nothing to be frozen.
    assert!(
        !posed(5.0).is_empty(),
        "the frozen tail drew nothing at all, so nothing here measures the       renderer"
    );
    assert_eq!(
        posed(5.0),
        posed(8.0),
        "the pose moved, so this proves nothing about the other evaluators"
    );

    let sampled = |time: f32| {
        entry
            .parts
            .iter()
            .flat_map(|part| &part.draws)
            .filter_map(|draw| draw.sampler())
            .filter_map(|at| library.samplers().get(at))
            .map(|row| row.at(library.curves(), time * 60.0))
            .collect::<Vec<Sampling>>()
    };
    assert_ne!(
        sampled(5.0),
        sampled(8.0),
        "the UV transform stood still through a frozen pose, which is exactly \
         the frozen tail that reads as a finished animation"
    );
}
