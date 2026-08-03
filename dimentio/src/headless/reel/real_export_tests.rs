//! Reels of the export on this machine, when there is one.
//!
//! ⚠️ `work/` is git-ignored, so these skip rather than fail on a fresh clone
//! or in CI.

use super::*;
use crate::render::Background;
use std::path::{Path, PathBuf};

fn export() -> Option<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()?
        .join("work")
        .join("export");
    root.join("effects.json").is_file().then_some(root)
}

fn out_dir() -> PathBuf {
    let at = std::env::temp_dir().join(format!("dimentio-reel-real-{}", std::process::id()));
    std::fs::create_dir_all(&at).expect("scratch folder");
    at
}

/// `chaos` is the effect the five-fold ring was measured on in game (D172,
/// D173), and it has parts of two different lengths — so its reel is the
/// one where a part ending must actually show up.
#[test]
fn chaos_reels_across_its_parts_ending() {
    let Some(export) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let out = out_dir().join("chaos.png");
    let report = take(&Request {
        effect: "chaos".to_owned(),
        export,
        out: out.clone(),
        size: 96,
        frames: 6,
        background: Background::DarkGrey,
        from: None,
        upto: None,
    })
    .expect("chaos renders");

    assert_eq!(report.parts, 4);
    assert_eq!(report.frames.len(), 6);
    assert!(out.is_file());
    assert_eq!(report.frames[0].active, 4, "all four run at the start");
    assert!(
        report.frames.last().expect("a last frame").active < 4,
        "no part ever ended: {:?}",
        report.frames
    );
    assert!(report.moves(), "the reel never changed");

    // ⚠️ This assertion was `painted == 0` until D258, and flipped because
    // the meshes changed rather than because the number was edited: all
    // four of chaos's parts resolve through the five-hop chain to images
    // 23, 15, 24 and 14 of `effdata.tpl`.
    assert_eq!(report.painted, 4, "chaos lost its decoded images");
    assert!(report.frames[0].painted > 0, "nothing was textured at 0s");
    let caveat = report.lines().pop().expect("a caveat");
    assert!(caveat.contains("posed as its own geometry"), "{caveat}");
    let _ = std::fs::remove_file(out);
}

/// Every real effect reels without panicking, and the ones with parts draw
/// something at their first frame. ⚠️ The count is asserted so that an
/// export that silently lost its effects cannot pass as a clean sweep.
#[test]
fn every_real_effect_with_parts_reels() {
    let Some(export) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&export);
    let folder = out_dir();
    let (mut reeled, mut empty, mut textured) = (0, 0, 0);
    let (mut shown, mut claimed) = (0usize, 0usize);
    let mut deep: Vec<String> = Vec::new();
    for entry in library.entries() {
        let out = folder.join("sweep.png");
        let asked = Request {
            effect: entry.name.clone(),
            export: export.clone(),
            out: out.clone(),
            // ⚠️ 128, not 48. Much of the bank is sparse art, and at
            // 64 a quad can sample only transparent texels — item_thunder
            // blanks there and draws here (D259). A sweep at a size that
            // loses sprites would assert against its own artefact.
            size: 128,
            frames: 3,
            background: Background::DarkGrey,
            from: None,
            upto: None,
        };
        match take(&asked) {
            Ok(report) => {
                // ⚠️ **Somewhere in the reel, not at frame 0.** Now that
                // parts are posed, an effect whose scale rises from zero
                // draws nothing at its first frame — 44% of draws are flat
                // there — and demanding otherwise would assert against the
                // data. What must hold is that the effect appears at *some*
                // point in its own timeline.
                if !report.frames.iter().any(|frame| frame.drawn > 0.0) {
                    assert!(
                        // Three documented reasons, all reported to the
                        // reader: geometry too deep to frame (D264), never
                        // posed above zero scale (D266), or sparse art that
                        // missed every pixel at this --size (D259).
                        report.too_deep()
                            || report.never_posed()
                            || report.blank_frame().is_some(),
                        "{} drew nothing anywhere in its reel, and the                              report gives no reason",
                        entry.name
                    );
                    deep.push(entry.name.clone());
                }
                // A part carrying a picture must reach a decoded image:
                // that is the export and the catalog agreeing.
                let declared = entry
                    .parts
                    .iter()
                    .filter(|part| part.draws.iter().any(|d| d.image().is_some()))
                    .count();
                // ⚠️ **At most**, not exactly. A part flat at every
                // sampled frame never draws, so it never paints — that is
                // its own animation, not a missing image. Painting *more*
                // parts than declare an image would still be a fault.
                assert!(
                    report.painted <= declared,
                    "{}: {declared} part(s) declare an image, {} painted",
                    entry.name,
                    report.painted
                );
                shown += report.painted;
                claimed += declared;
                textured += usize::from(report.painted > 0);
                reeled += 1;
            }
            Err(why) => {
                assert!(why.contains("no parts"), "{}: {why}", entry.name);
                empty += 1;
            }
        }
        let _ = std::fs::remove_file(out);
    }
    assert!(reeled > 100, "only {reeled} effects reeled ({empty} empty)");
    // ⛔ The teeth the per-effect check lost. Relaxing to `<=` would pass a
    // renderer that painted nothing at all, so the corpus has to show that
    // the great majority of parts declaring an image really do draw one.
    assert!(
        shown * 10 >= claimed * 8,
        "only {shown} of {claimed} declared part(s) ever painted"
    );
    // ✅ Empty: with the bounds measured per axis rather than as a radius,
    // every effect in the export draws at its first frame — including the
    // one whose geometry is 92x deeper than wide, which the report still
    // flags so a reader knows why it is a sliver (D264).
    // ⚠️ A handful of effects sample flat at every frame of a 3-frame reel
    // — their scales rise later. Pinned loosely so a renderer that stopped
    // drawing altogether still fails loudly.
    assert!(
        deep.len() < 12,
        "{} effects drew nothing: {deep:?}",
        deep.len()
    );
    // ⚠️ The control on the assertion above: if every effect declared no
    // images, `painted == declared` would hold everywhere at zero and
    // the sweep would pass having verified nothing.
    assert!(
        textured > 100,
        "only {textured} of {reeled} effects painted anything — the export \
         probably predates the binding"
    );
}
