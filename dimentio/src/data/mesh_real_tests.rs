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
    // ⛔ This asserted that *most* models are textured, which stopped being
    // true when `bleck` stopped painting one image across every shape of a
    // model (D229). A model with several shapes has one image per shape and
    // the binding is not decoded, so it exports bare on purpose.
    assert!(
        painted > 0 && bare > painted,
        "expected a textured minority; got {painted} textured, {bare} bare of {}",
        library.len()
    );
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
