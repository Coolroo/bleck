//! The unit tests for `mesh.rs`.
//!
//! ⚠️ Split out only to keep that module under a thousand lines, the same way
//! `mesh_real_tests.rs` was. `#[path]` in `mesh.rs` keeps the module where it
//! was, so these still read `super::*`.

use super::*;
use crate::data::scratch::Scratch;

const TRIANGLE: &str = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";

#[test]
fn parses_positions_and_faces() {
    let mesh = Mesh::parse(TRIANGLE).expect("triangle parses");
    assert_eq!(mesh.positions().len(), 3);
    assert_eq!(mesh.faces(), [Face { a: 0, b: 1, c: 2 }]);
    assert_eq!(mesh.positions()[1], Vec3::new(1.0, 0.0, 0.0));
}

#[test]
fn ignores_lines_the_format_does_not_promise() {
    let text = "# a comment\nmtllib none.mtl\nvn 0 0 1\nvt 0 0\no thing\n";
    let mesh = Mesh::parse(&format!("{text}{TRIANGLE}")).expect("extras are skipped");
    assert_eq!(mesh.faces().len(), 1);
}

#[test]
fn accepts_slash_forms_and_negative_indices() {
    let mesh =
        Mesh::parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1/1 -2/2 -1\n").expect("index forms parse");
    assert_eq!(mesh.faces(), [Face { a: 0, b: 1, c: 2 }]);
}

#[test]
fn fans_a_quad_into_two_triangles() {
    let mesh = Mesh::parse("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n").expect("quad parses");
    assert_eq!(
        mesh.faces(),
        [Face { a: 0, b: 1, c: 2 }, Face { a: 0, b: 2, c: 3 }]
    );
}

fn manifest_row(name: &str, source: &str) -> Entry {
    Entry {
        name: name.to_owned(),
        shape: "kuriboShape".to_owned(),
        path: PathBuf::from("0001.obj"),
        source: source.to_owned(),
        positions: 3,
        faces: 1,
        triangles: 1,
        coverage: 1.0,
        fragment: false,
        texture_guessed: false,
        min: [0.0; 3],
        max: [1.0; 3],
        ..Default::default()
    }
}

/// ⚠️ The name, not the OBJ. The exported file is a temporary on one
/// machine, so a clipboard full of those paths names nothing anyone else
/// can look up.
#[test]
fn a_model_copies_its_name_and_the_disc_file_behind_it() {
    let shown = manifest_row("files/a/e_kuribo.dat", "files/a/e_kuribo.dat");
    assert_eq!(shown.copy_text(), "files/a/e_kuribo.dat");
    assert_eq!(shown.source_text(), Some("files/a/e_kuribo.dat".to_owned()));
    assert_ne!(
        shown.copy_text(),
        shown.path.display().to_string(),
        "the export's own file is not what names this model"
    );
    assert_ne!(shown.copy_text(), shown.shape, "nor is the Maya shape");
}

/// A "Copy source path" that put nothing on the clipboard reads as a copy
/// that failed.
#[test]
fn a_model_with_no_source_offers_nothing_for_it() {
    assert_eq!(manifest_row("files/a/loose.dat", "").source_text(), None);
}

#[test]
fn rejects_an_index_past_the_end() {
    let flaw = Mesh::parse("v 0 0 0\nf 1 2 3\n").expect_err("index 2 does not exist");
    assert_eq!(flaw.line, 2);
    assert!(flaw.why.contains("outside"), "{}", flaw.why);
}

#[test]
fn rejects_a_short_vertex() {
    let flaw = Mesh::parse("v 1 2\n").expect_err("two numbers is not a point");
    assert_eq!(flaw.line, 1);
}

#[test]
fn empty_text_is_an_empty_mesh_not_an_error() {
    let mesh = Mesh::parse("").expect("nothing is not a failure");
    assert!(mesh.is_empty());
    assert_eq!(mesh.bounds(), Bounds::default());
}

#[test]
fn bounds_span_every_point() {
    let mesh = Mesh::parse("v -2 0 1\nv 4 3 -5\nv 0 0 0\nf 1 2 3\n").expect("parses");
    assert_eq!(mesh.bounds().min, Vec3::new(-2.0, 0.0, -5.0));
    assert_eq!(mesh.bounds().max, Vec3::new(4.0, 3.0, 1.0));
    assert_eq!(mesh.bounds().centre(), Vec3::new(1.0, 1.5, -2.0));
}

/// ⚠️ Real exports do this constantly: 733 of 864 models carry positions
/// no face refers to. Bounding them all frames empty space, and the model
/// ends up too small to see.
#[test]
fn bounds_ignore_positions_no_face_refers_to() {
    let mesh = Mesh::parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 900 900 900\nf 1 2 3\n").expect("parses");
    assert_eq!(mesh.positions().len(), 4);
    assert_eq!(mesh.bounds().max, Vec3::new(1.0, 1.0, 0.0));
}

/// With nothing drawn there is nothing to frame, so every point counts —
/// which keeps a mesh of loose vertices from claiming a zero-size box at
/// the origin it has no points near.
#[test]
fn bounds_fall_back_to_every_point_when_there_are_no_faces() {
    let mesh = Mesh::parse("v 5 5 5\nv 7 9 5\n").expect("parses");
    assert!(mesh.is_empty());
    assert_eq!(mesh.bounds().min, Vec3::new(5.0, 5.0, 5.0));
    assert_eq!(mesh.bounds().max, Vec3::new(7.0, 9.0, 5.0));
}

const MANIFEST_TEXT: &str = r#"{"models": [
  {"name": "p_wii_mario", "shape": "R_Arm_skinShape", "file": "p_wii_mario.obj",
   "positions": 3, "faces": 1, "triangles": 1,
   "min": [-30.0, -14.7, 0.0], "max": [10.8, 58.7, 3.2]}
]}"#;

/// The manifest as `bleck model export` writes it today, keys and all.
/// ⚠️ Unknown keys must stay tolerated: `schema`, `coverage` and
/// `fragment` all arrived after this reader was written, and a stricter
/// one would have refused every export the day they landed.
const LIVE_MANIFEST: &str = r#"{"schema": 1, "models": [
  {"name": "p_big_mario", "shape": "zentaiShape", "file": "p_big_mario.obj",
   "source": "files/a/p_big_mario", "positions": 2255, "faces": 3529,
   "triangles": 3529, "coverage": 0.0013, "fragment": true,
   "min": [-73.5, -1.2, -36.0], "max": [73.5, 147.0, 36.0],
   "something_added_later": [1, 2, 3]}
]}"#;

#[test]
fn reads_the_manifest_the_exporter_writes_today() {
    let scratch = Scratch::new("live");
    scratch.write("models.json", LIVE_MANIFEST);
    let library = Library::load(&scratch.path);
    assert_eq!(library.problem(), None);
    let entry = &library.entries()[0];
    assert_eq!(entry.source, "files/a/p_big_mario");
    assert!(entry.fragment);
    assert_eq!(entry.coverage, 0.0013);
}

/// The face form the exporter emits now that it carries normals, mixed
/// with corners that have none.
#[test]
fn accepts_the_position_double_slash_normal_form() {
    let mesh = Mesh::parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 1\nf 1//1 2//1 3\n")
        .expect("the exporter's own output parses");
    assert_eq!(mesh.faces(), [Face { a: 0, b: 1, c: 2 }]);
}

#[test]
fn reads_the_manifest_and_absolutises_paths() {
    let scratch = Scratch::new("manifest");
    scratch.write("models.json", MANIFEST_TEXT);
    scratch.write("p_wii_mario.obj", TRIANGLE);

    let library = Library::load(&scratch.path);
    assert_eq!(library.problem(), None);
    assert_eq!(library.len(), 1);
    let entry = &library.entries()[0];
    assert_eq!(entry.shape, "R_Arm_skinShape");
    assert_eq!(entry.path, scratch.path.join("p_wii_mario.obj"));
    assert_eq!(entry.describe(), "3 verts, 1 tris");
    assert_eq!(entry.extent(), "40.8 x 73.4 x 3.2");
    assert!(!entry.fragment, "the manifest did not claim one");

    let mesh = Mesh::load(&entry.path).expect("the mesh beside it loads");
    assert_eq!(mesh.faces().len(), 1);
}

/// The whole path a model takes through this program: an export folder on
/// disk, through the manifest, through the OBJ, to lit pixels. Each step
/// has its own test above; this is the one that fails if they stop
/// fitting together.
#[test]
fn an_export_folder_reaches_the_rasteriser() {
    let scratch = Scratch::new("endtoend");
    scratch.write(
        "models.json",
        r#"{"models": [{"name": "p_wii_mario", "shape": "zentaiShape",
             "file": "sub/p_wii_mario.obj", "positions": 4, "faces": 2,
             "triangles": 2, "min": [-1,-1,-1], "max": [1,1,1]}]}"#,
    );
    std::fs::create_dir_all(scratch.path.join("sub")).expect("subfolder");
    std::fs::write(
        scratch.path.join("sub/p_wii_mario.obj"),
        "v -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\nf 1 2 3\nf 1 3 4\n",
    )
    .expect("mesh file");

    let library = Library::load(&scratch.path);
    let entry = &library.entries()[library.matching("zentai")[0]];
    let mesh = Mesh::load(&entry.path).expect("mesh loads");

    let view = crate::render::View {
        camera: crate::render::Camera::fit(mesh.bounds()),
        background: crate::render::Background::DarkGrey,
    };
    let size = crate::render::Size::new(120, 120);
    let image = crate::render::render(&mesh, &view, size);

    let sky = crate::render::Background::DarkGrey.pixel(0, 0, size);
    let drawn = (0..size.height)
        .flat_map(|y| (0..size.width).map(move |x| (x, y)))
        .filter(|&(x, y)| image.pixel(x, y) != sky)
        .count();
    assert!(drawn > 500, "only {drawn} pixels of the square were drawn");
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
    assert!(said.contains("bleck model export"), "{said}");
    assert!(said.contains(&scratch.path.display().to_string()), "{said}");
}

#[test]
fn broken_json_is_reported_not_panicked() {
    let scratch = Scratch::new("broken");
    scratch.write("models.json", "{\"models\": [");
    let library = Library::load(&scratch.path);
    assert!(matches!(library.problem(), Some(Problem::Unreadable(_))));
    assert!(library.is_empty());
}

#[test]
fn a_missing_mesh_file_names_itself() {
    let scratch = Scratch::new("gone");
    let path = scratch.path.join("absent.obj");
    let problem = Mesh::load(&path).expect_err("nothing is there to read");
    assert_eq!(problem, Problem::NoMesh(path.clone()));
    assert!(problem.describe().contains("absent.obj"), "{problem:?}");
}

#[test]
fn a_broken_mesh_file_reports_its_line() {
    let scratch = Scratch::new("badobj");
    scratch.write("bad.obj", "v 0 0 0\nv 1 0 0\nf 1 2 9\n");
    let path = scratch.path.join("bad.obj");
    let problem = Mesh::load(&path).expect_err("index 9 does not exist");
    assert!(problem.describe().contains(":3:"), "{}", problem.describe());
}

#[test]
fn search_matches_name_or_shape() {
    let scratch = Scratch::new("search");
    scratch.write("models.json", MANIFEST_TEXT);
    let library = Library::load(&scratch.path);
    assert_eq!(library.matching(""), vec![0]);
    assert_eq!(library.matching("MARIO"), vec![0]);
    assert_eq!(library.matching("r_arm"), vec![0]);
    assert!(library.matching("luigi").is_empty());
}
