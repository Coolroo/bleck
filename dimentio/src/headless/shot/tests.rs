//! `shot`'s own tests: the command line, the sheet it lays out, and the
//! verdict it prints. The grid arithmetic and the colour measures are tested
//! next to the code that owns them, in `super::super::sheet`.

use super::*;
use crate::render::Rgba;
use std::path::Path;

/// A cube of side 2 about the origin, in the OBJ the mesh reader also
/// accepts — so the tests need no exported `.glb` and no disc.
const CUBE: &str = "\
v -1 -1 -1
v 1 -1 -1
v 1 1 -1
v -1 1 -1
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 1 2 3
f 1 3 4
f 5 6 7
f 5 7 8
f 1 2 6
f 1 6 5
f 2 3 7
f 2 7 6
f 3 4 8
f 3 8 7
f 4 1 5
f 4 5 8
";

fn cube_mesh() -> Mesh {
    Mesh::parse(CUBE).expect("the cube parses")
}

/// A folder no other test writes into, removed when the test ends.
struct Scratch(PathBuf);

impl Scratch {
    fn new(name: &str) -> Self {
        let at = std::env::temp_dir().join(format!("dimentio-shot-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&at);
        std::fs::create_dir_all(&at).expect("scratch folder");
        Self(at)
    }

    fn file(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn words(line: &str) -> Vec<String> {
    line.split_whitespace().map(str::to_owned).collect()
}

fn cube_file(scratch: &Scratch) -> PathBuf {
    let path = scratch.file("cube.obj");
    std::fs::write(&path, CUBE).expect("wrote the cube");
    path
}

#[test]
fn the_defaults_are_a_four_angle_sheet_on_a_checkerboard() {
    let request = parse(&words("model.glb --out shot.png")).expect("parses");
    assert_eq!(request.model, PathBuf::from("model.glb"));
    assert_eq!(request.out, PathBuf::from("shot.png"));
    assert_eq!(request.size, DEFAULT_SIZE);
    assert_eq!(request.angles, DEFAULT_ANGLES);
    assert_eq!(request.clip, 0);
    assert_eq!(request.frame, None);
    assert_eq!(request.background, Background::Checkerboard);
}

#[test]
fn every_option_is_read() {
    let request = parse(&words(
        "m.glb --out a/b.png --size 64 --angles 2 --clip 3 --frame 5 --background dark-grey",
    ))
    .expect("parses");
    assert_eq!(request.size, 64);
    assert_eq!(request.angles, 2);
    assert_eq!(request.clip, 3);
    assert_eq!(request.frame, Some(5));
    assert_eq!(request.background, Background::DarkGrey);
}

#[test]
fn a_command_line_that_cannot_work_is_refused_before_anything_is_read() {
    for line in [
        "",
        "model.glb",
        "model.glb --out",
        "model.glb --out o.png --size huge",
        "model.glb --out o.png --size 0",
        "model.glb --out o.png --angles 99",
        "model.glb --out o.png --background white",
        "model.glb --out o.png --colour red",
        "one.glb two.glb --out o.png",
    ] {
        assert!(parse(&words(line)).is_err(), "{line:?} was accepted");
    }
}

#[test]
fn a_backwards_sweep_is_refused_by_name() {
    let parsed = parse(&words("m.glb --out a.gif --frame 9 --to 2")).expect("parses");
    assert_eq!(parsed.frame, Some(9));
    assert_eq!(parsed.upto, Some(2));
}

#[test]
fn an_unreadable_model_is_an_error_and_not_an_empty_png() {
    let scratch = Scratch::new("missing");
    let out = scratch.file("shot.png");
    let request = Request {
        model: scratch.file("nothing-here.glb"),
        out: out.clone(),
        size: 32,
        angles: 1,
        clip: 0,
        upto: None,
        frame: None,
        background: Background::Checkerboard,
    };
    assert!(take(&request).is_err());
    assert!(!out.exists(), "a failed run still wrote a file");
}

#[test]
fn a_frame_of_a_model_with_no_animation_is_refused() {
    let scratch = Scratch::new("noanim");
    let request = Request {
        model: cube_file(&scratch),
        out: scratch.file("shot.png"),
        size: 32,
        angles: 1,
        clip: 0,
        upto: None,
        frame: Some(0),
        background: Background::Checkerboard,
    };
    let why = take(&request).expect_err("a cube has no clips");
    assert!(why.contains("no morph animation"), "{why}");
}

#[test]
fn a_sheet_is_a_grid_of_cells_with_the_model_drawn_in_each() {
    let scratch = Scratch::new("sheet");
    let request = Request {
        model: cube_file(&scratch),
        out: scratch.file("shot.png"),
        size: 64,
        angles: 4,
        clip: 0,
        upto: None,
        frame: None,
        background: Background::Checkerboard,
    };
    let report = take(&request).expect("renders");
    let edge = 64 * 2 + GUTTER;
    assert_eq!(report.sheet, Size::new(edge, edge));
    assert_eq!(report.triangles, 12);
    assert!(
        (0.05..0.60).contains(&report.drawn),
        "the cube covered {} of the sheet",
        report.drawn
    );
    assert!(report.posed.is_none());

    let sheet = draw(&cube_mesh(), &request);
    assert_eq!(sheet.pixels.len(), edge * edge * 4);
    // Each cell drew something: a grid that rendered once and copied it
    // three times would pass a whole-sheet coverage check.
    for (left, top) in [(0, 0), (66, 0), (0, 66), (66, 66)] {
        let mut drawn = 0;
        for y in top..top + 64 {
            for x in left..left + 64 {
                let at = (y * edge + x) * 4;
                let colour =
                    Rgba::new(sheet.pixels[at], sheet.pixels[at + 1], sheet.pixels[at + 2]);
                if colour != Background::Checkerboard.pixel(x - left, y - top, Size::new(64, 64)) {
                    drawn += 1;
                }
            }
        }
        assert!(drawn > 200, "cell at {left},{top} drew only {drawn} pixels");
    }
}

fn cube_coverage() -> sheet::Coverage {
    let view = View {
        camera: Camera::fit(cube_mesh().bounds()),
        background: Background::DarkGrey,
    };
    let size = Size::new(128, 128);
    let image = render::render(&cube_mesh(), &view, size);
    sheet::measure(image.as_rgba(), size, Background::DarkGrey)
}

/// ⚠️ The point of the whole tool: a bare model must not read as a painted
/// one. A cube carries no image, and the shading swings its brightness from
/// ambient to full without that counting as colour.
#[test]
fn a_bare_model_reads_as_one_tint() {
    let measured = cube_coverage();
    assert!(measured.drawn > 1000, "the cube barely drew");
    assert!(
        measured.spread < FLAT_SPREAD,
        "a plain cube spread {}",
        measured.spread
    );
    // Six large facets: neighbours agree everywhere but the six edges.
    assert!(
        measured.detail < 0.01,
        "a plain cube showed {} detail",
        measured.detail
    );
}

#[test]
fn the_png_is_readable_and_is_not_one_colour() {
    let scratch = Scratch::new("png");
    let out = scratch.file("deep/shot.png");
    let request = Request {
        model: cube_file(&scratch),
        out: out.clone(),
        size: 48,
        angles: 2,
        clip: 0,
        upto: None,
        frame: None,
        background: Background::Checkerboard,
    };
    take(&request).expect("renders");

    let decoded = image::open(&out).expect("the PNG reads back").to_rgba8();
    assert_eq!(decoded.width(), 48 * 2 + GUTTER as u32);
    assert_eq!(decoded.height(), 48);
    let first = decoded.as_raw()[..4].to_vec();
    assert!(
        decoded.as_raw().chunks(4).any(|pixel| pixel != first),
        "the PNG is a single colour"
    );
}

/// A model out of the export on this machine, found through the manifest
/// rather than by joining a path — the exported layout has moved once
/// already, and a hand-built path that stops matching skips silently.
fn exported(name: &str) -> Option<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()?
        .join("work")
        .join("export");
    let library = crate::data::mesh::Library::load(&root);
    library
        .entries()
        .iter()
        .find(|entry| entry.name == name && !entry.fragment)
        .map(|entry| entry.path.clone())
        .filter(|path| path.is_file())
}

/// One view of a real model, at a size a test can afford.
fn shot_of(scratch: &Scratch, model: PathBuf, out: &str) -> Report {
    take(&Request {
        model,
        out: scratch.file(out),
        size: 192,
        angles: 1,
        clip: 0,
        upto: None,
        frame: None,
        background: Background::Checkerboard,
    })
    .expect("renders")
}

/// ⚠️ **The control.** A tool that emits a plausible image for a model
/// whose textures did not arrive is worse than no tool, so the two cases
/// are rendered side by side and must not report the same thing.
/// `e_lui_robo` carries 15 images; `e_big_nok` carries none.
///
/// ⛔ **Colour spread is no longer what separates them** (D251). This test
/// asserted the bare model was one flat tint, and `e_big_nok` has ten —
/// painted entirely by vertex colour, which is how the game draws a model
/// that names no image. The count read from the file is what separates
/// them now, and the spread is asserted the other way round.
#[test]
fn a_painted_model_and_a_bare_one_do_not_report_the_same_thing() {
    let (Some(painted), Some(bare)) = (exported("e_lui_robo"), exported("e_big_nok")) else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let scratch = Scratch::new("control");
    let robot = shot_of(&scratch, painted, "robot.png");
    let cragnon = shot_of(&scratch, bare, "cragnon.png");

    for (what, report) in [("robot", &robot), ("cragnon", &cragnon)] {
        assert!(report.drawn > 0.01, "{what} barely drew: {}", report.drawn);
    }
    assert!(robot.images > 0 && cragnon.images == 0);
    assert!(
        robot.colours_vary(),
        "a 15-image model read as one tint: spread {}",
        robot.spread
    );
    assert!(
        cragnon.colours_vary(),
        "a vertex-coloured model came out one flat tint: spread {}",
        cragnon.spread
    );
    assert!(
        robot
            .lines()
            .last()
            .is_some_and(|line| line.contains("an image reached it")),
        "the verdict stopped naming the painted model: {:?}",
        robot.lines()
    );
    assert!(
        cragnon
            .lines()
            .last()
            .is_some_and(|line| line.contains("no image")),
        "the verdict called a bare model painted: {:?}",
        cragnon.lines()
    );
}

/// ⛔ **Why the verdict is colour and not detail.** `e_bari_bari` carries
/// no image and `MOBJ_tik_r_hatena_block` carries one, and the untextured
/// model is the more detailed of the two — its facets are small enough to
/// read as texels. Colour still separates them the right way round.
///
/// This is a standing check on the reasoning, not on the code: if the
/// numbers ever swap, the refutation in `Coverage::detail` is stale.
#[test]
fn detail_puts_an_untextured_model_above_a_textured_one() {
    let (Some(bare), Some(painted)) =
        (exported("e_bari_bari"), exported("MOBJ_tik_r_hatena_block"))
    else {
        eprintln!("no work/export on this machine; skipped");
        return;
    };
    let scratch = Scratch::new("refute");
    let spiny = shot_of(&scratch, bare, "spiny.png");
    let block = shot_of(&scratch, painted, "block.png");
    assert!(
        spiny.detail > block.detail,
        "detail separated them after all: {} against {}",
        spiny.detail,
        block.detail
    );
    assert!(!spiny.colours_vary() && block.colours_vary());
}
