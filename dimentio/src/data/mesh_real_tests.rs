//! Loading the real export, when one happens to be on this machine.
//!
//! ⚠️ Split out of `mesh.rs` only to keep that module under a thousand
//! lines. `#[path]` in `mesh.rs` keeps the module where it was, so these
//! still read `super::*` and are still `data::mesh::real_export_tests`.

use super::*;

fn export() -> Option<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()?
        .join("work")
        .join("export");
    root.join(MANIFEST).is_file().then_some(root)
}

#[test]
fn every_mesh_the_manifest_names_actually_loads() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let entries = library.entries();
    assert!(!entries.is_empty(), "the manifest named nothing");

    let mut loaded = 0;
    let mut failed = Vec::new();
    for entry in entries {
        match Mesh::load(&entry.path) {
            Ok(mesh) if !mesh.is_empty() => loaded += 1,
            Ok(_) => failed.push(format!("{}: no triangles", entry.name)),
            Err(problem) => failed.push(format!("{}: {}", entry.name, problem.describe())),
        }
    }
    assert!(
        failed.is_empty(),
        "{} failed, e.g. {:?}",
        failed.len(),
        &failed[..failed.len().min(3)]
    );
    assert_eq!(loaded, entries.len());
}

#[test]
fn a_real_mesh_carries_the_triangles_the_manifest_promised() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    for entry in library.entries().iter().take(20) {
        let mesh = Mesh::load(&entry.path).expect("mesh");
        assert_eq!(
            mesh.faces().len(),
            entry.triangles,
            "{} disagrees with its manifest",
            entry.name
        );
    }
}

/// ⚠️ **The fixture next door is two primitives written by this crate's own
/// test.** Only a file `bleck` wrote can show the two ends agreeing on a real
/// model, and `e_lui_robo` has 92 shapes where the fixture has two.
#[test]
fn a_real_models_shapes_partition_its_faces() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let mut many = 0;
    for entry in library.entries().iter().take(60) {
        let mesh = Mesh::load(&entry.path).expect("mesh");
        let shapes = mesh.shapes();
        assert!(!shapes.is_empty(), "{} carries no shape at all", entry.name);
        assert_eq!(shapes[0].first, 0, "{}", entry.name);
        let mut at = 0;
        for shape in shapes {
            assert_eq!(shape.first, at, "{} has a gap in its shapes", entry.name);
            assert!(shape.count > 0, "{} has an empty shape", entry.name);
            at += shape.count;
        }
        assert_eq!(at, mesh.faces().len(), "{}", entry.name);
        if shapes.len() > 1 {
            many += 1;
        }
    }
    assert!(
        many > 0,
        "every model read as a single shape — the export predates the split"
    );
}

/// Hiding a shape has to take triangles off a real model, not merely flip a
/// flag: the whole point is that a stray shape can be looked away from.
#[test]
fn hiding_a_shape_of_a_real_model_draws_fewer_triangles() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let mut checked = 0;
    for entry in library.entries() {
        let mut mesh = Mesh::load(&entry.path).expect("mesh");
        if mesh.shapes().len() < 2 {
            continue;
        }
        let before = mesh.faces().len();
        let dropped = mesh.shapes()[0].count;
        mesh.set_shape_visible(0, false);
        assert_eq!(mesh.faces().len(), before - dropped, "{}", entry.name);
        mesh.show_all_shapes();
        assert_eq!(mesh.faces().len(), before, "{}", entry.name);
        checked += 1;
        if checked == 10 {
            break;
        }
    }
    assert!(checked > 0, "no model in the export carried several shapes");
}

/// ⚠️ **The fixture cannot catch this.** `animated_quad` is written by this
/// crate's own test module and would agree with a reader that had the
/// animation chain wrong; only a file `bleck` wrote can disagree.
#[test]
fn the_clips_the_manifest_names_are_the_clips_the_mesh_carries() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    if library.entries().iter().all(|entry| entry.animations == 0) {
        eprintln!("this export predates per-clip manifest entries; skipped");
        return;
    }

    let mut checked = 0;
    for entry in library.entries() {
        let promised: Vec<&str> = entry
            .clips
            .iter()
            .filter(|clip| clip.written)
            .map(|clip| clip.name.as_str())
            .collect();
        if promised.is_empty() {
            continue;
        }
        let mesh = Mesh::load(&entry.path).expect("mesh");
        let animation = mesh
            .animation()
            .unwrap_or_else(|| panic!("{} promised clips and carries none", entry.name));
        let carried: Vec<&str> = animation
            .clips()
            .iter()
            .map(|clip| clip.name.as_str())
            .collect();
        assert_eq!(
            promised, carried,
            "{} disagrees with its manifest",
            entry.name
        );
        assert_eq!(promised.len(), entry.animations, "{}", entry.name);
        checked += 1;
        if checked == 20 {
            break;
        }
    }
    assert!(checked >= 5, "only {checked} model(s) carried a clip");
}

/// A real clip has to reach the geometry, not merely parse. Several models,
/// because one that happens to open with a near-empty pose would prove nothing.
#[test]
fn a_real_clip_displaces_a_real_model() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let mut moved = 0;
    let mut looked = 0;
    for entry in library.entries() {
        if entry.animations == 0 {
            continue;
        }
        let mut mesh = Mesh::load(&entry.path).expect("mesh");
        let rest = mesh.rest_positions().to_vec();
        let span = mesh
            .animation()
            .and_then(|animation| animation.clips().first())
            .map_or(0.0, |clip| clip.seconds());
        mesh.pose(0, span / 2.0);
        looked += 1;
        if mesh.positions() != rest {
            moved += 1;
        }
        if looked == 25 {
            break;
        }
    }
    assert!(looked > 0, "no model in the export declared a clip");
    assert!(
        moved * 2 > looked,
        "only {moved} of {looked} clips moved anything"
    );
}

/// ⚠️ Most of the export is textured — a run that finds none of them is
/// the bug this was written for, not a quiet pass. The fixtures elsewhere
/// are written by this crate's own tests and would agree with a reader
/// that had the material chain wrong.
#[test]
fn the_textured_models_are_the_single_shape_minority() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let mut painted = 0;
    let mut bare = 0;
    for entry in library.entries() {
        let mesh = Mesh::load(&entry.path).expect("mesh");
        match mesh.surface() {
            Some(surface) => {
                assert!(surface.texture.width() > 0, "{}", entry.name);
                assert_eq!(surface.uvs.len(), mesh.positions().len(), "{}", entry.name);
                painted += 1;
            }
            None => bare += 1,
        }
    }
    // ⛔ **This must not assume which flags produced the export.** It once
    // asserted most models are textured, which D229 reversed; then a textured
    // minority, which `--guess-textures` reverses back. Either export is
    // legitimate, so assert only what holds for both.
    assert!(
        painted > 0,
        "no model was textured at all, of {}",
        library.len()
    );
    assert_eq!(painted + bare, library.len());
}

/// The whole point, measured on real data: a textured model reaches the
/// frame as several colours, an untextured one as flat grey.
#[test]
fn a_textured_model_reaches_the_frame_as_more_than_one_colour() {
    let Some(root) = export() else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let library = Library::load(&root);
    let size = crate::render::Size::new(160, 160);
    let sky = crate::render::Background::DarkGrey.pixel(0, 0, size);

    let mut checked = 0;
    for entry in library.entries() {
        // ⛔ A guessed texture is image 0 painted on a shape that does not
        // own it, and can legitimately be one flat colour -- so it cannot
        // answer "was the texture sampled" (D229).
        if entry.texture_guessed {
            continue;
        }
        let mesh = Mesh::load(&entry.path).expect("mesh");
        if mesh.surface().is_none() || mesh.faces().len() < 200 {
            continue;
        }
        let view = crate::render::View {
            camera: crate::render::Camera::fit(mesh.bounds()),
            background: crate::render::Background::DarkGrey,
        };
        let image = crate::render::render(&mesh, &view, size);
        let mut seen: Vec<crate::render::Rgba> = Vec::new();
        for y in 0..size.height {
            for x in 0..size.width {
                let pixel = image.pixel(x, y);
                if pixel != sky && !seen.contains(&pixel) && seen.len() < 8 {
                    seen.push(pixel);
                }
            }
        }
        assert!(
            seen.len() > 1,
            "{} drew {} distinct colour(s) — the texture was not sampled",
            entry.name,
            seen.len()
        );
        checked += 1;
        if checked == 12 {
            break;
        }
    }
    assert!(
        checked > 0,
        "no textured model in the export was big enough"
    );
}
