//! `dimentio shot` — render a model to a PNG file and exit.
//!
//! The window is not involved. `render` rasterises into a `Vec<u8>` with no
//! GPU, driver or display, so the same code that fills the viewport fills a
//! file, and a caller with no screen can look at what it built.
//!
//! ⚠️ **Several angles into one image, not one file each.** Most defects in an
//! exported model are visible from one direction only — a stray shape off to
//! the side, a surface that vanishes when its back is turned, a face left
//! untextured. Four files means four looks, and the one not opened is the one
//! that showed it.
//!
//! ⚠️ **The backdrop is never white.** A texture that decodes to near-white and
//! a texture that failed to decode look the same against a white page, and
//! telling those apart is most of what this is for.

use std::f32::consts::TAU;
use std::io::BufWriter;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use image::codecs::png::PngEncoder;
use image::{ExtendedColorType, ImageEncoder};

use crate::data::mesh::Mesh;
use crate::render::{self, Background, Camera, Image, Rgba, Size, View};

/// Cell edge when `--size` is not given. Large enough to read a face on,
/// small enough that four of them stay under a megapixel.
const DEFAULT_SIZE: usize = 512;

const DEFAULT_ANGLES: usize = 4;

/// Bounds on both counts. A typo in `--size` would otherwise ask for an
/// allocation no machine has, and the failure would be a kill, not a message.
const SIZE_LIMIT: std::ops::RangeInclusive<usize> = 16..=4096;
const ANGLE_LIMIT: std::ops::RangeInclusive<usize> = 1..=16;

/// Pixels between cells of the contact sheet, in a colour neither background
/// uses, so where one view ends and the next begins is never in doubt.
const GUTTER: usize = 2;
const DIVIDER: Rgba = Rgba::new(120, 124, 132);

/// How far above the horizon every view of the sheet looks from. Straight on
/// hides the top of a model completely, and a model's top is where an
/// exporter's mistakes collect.
const SHEET_PITCH: f32 = 0.35;

/// Under this a frame's colours are one surface tint at different
/// brightnesses — a flat-shaded model, or a textured one whose images did not
/// arrive. See `Coverage::spread`.
///
/// Measured across 60 whole models of a real export: the 30 carrying no image
/// spread at most 0.007, and the 30 carrying one spread at least 0.023, with
/// one exception either side of nothing. This sits between them (D253).
const FLAT_SPREAD: f32 = 0.015;

pub const USAGE: &str = "\
dimentio shot <model.glb> --out <file.png> [options]

  --out <file.png>   where to write. Required.
  --size <n>         edge of one view, in pixels. Default 512.
  --angles <n>       views around the model, into one contact sheet. Default 4.
  --clip <n>         morph clip to pose, by index. Default 0.
  --frame <n>        keyframe of that clip to hold. Default: the rest pose.
  --background <s>   dark-grey | checkerboard | gradient. Default checkerboard.

With no arguments at all, dimentio opens its window instead.";

/// What a run was asked for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    pub model: PathBuf,
    pub out: PathBuf,
    pub size: usize,
    pub angles: usize,
    pub clip: usize,
    /// Which keyframe of `clip` to hold. `None` leaves the model at rest,
    /// which is what a model carrying no animation can do.
    pub frame: Option<usize>,
    pub background: Background,
}

/// What the run found, in the terms a caller with no screen can act on.
#[derive(Debug, Clone, PartialEq)]
pub struct Report {
    pub sheet: Size,
    pub angles: usize,
    pub triangles: usize,
    pub shapes: usize,
    pub images: usize,
    /// The clip and keyframe held, or `None` for the rest pose.
    pub posed: Option<Held>,
    /// Share of the sheet the model covers, 0..1.
    pub drawn: f32,
    pub spread: f32,
    pub detail: f32,
}

impl Report {
    /// Whether the drawn pixels carry more than one surface tint.
    ///
    /// ⚠️ This is the check the tool exists to make. A model whose textures
    /// failed to decode still renders, still fills the frame, and still looks
    /// like a model — flat-shaded — so nothing about the picture alone says
    /// whether an image reached it.
    ///
    /// ⛔ **It no longer means "an image reached it"** (D251). 41 models name
    /// no image and are drawn entirely with vertex colour: `e_big_nok` carries
    /// ten distinct tints and no texture whatever. Spread says the frame is not
    /// one flat colour, which is a weaker and true statement; `images` is the
    /// one read from the file and is what the verdict uses.
    ///
    /// ⛔ **`Coverage::detail` is deliberately not part of this**, twice over.
    /// Read the refutation there before adding it back.
    pub fn colours_vary(&self) -> bool {
        self.spread > FLAT_SPREAD
    }

    pub fn lines(&self) -> Vec<String> {
        let pose = match &self.posed {
            Some(held) => format!(
                "clip {} \"{}\", frame {} of {} at {:.3}s",
                held.clip, held.name, held.frame, held.keys, held.time
            ),
            None => "rest pose".to_owned(),
        };
        vec![
            format!(
                "{} triangle(s), {} shape(s), {} image(s)",
                self.triangles, self.shapes, self.images
            ),
            pose,
            format!(
                "{} angle(s) into {}x{}",
                self.angles, self.sheet.width, self.sheet.height
            ),
            format!("model covers {:.1}% of the sheet", self.drawn * 100.0),
            format!(
                "colour spread {:.3}, neighbour step {:.3} — {}",
                self.spread,
                self.detail,
                match (self.images > 0, self.colours_vary()) {
                    (true, _) => "an image reached it",
                    (false, true) => "no image: drawn with vertex colour",
                    (false, false) => "no image, and one flat tint",
                }
            ),
        ]
    }
}

/// The pose a frame was rendered at.
#[derive(Debug, Clone, PartialEq)]
pub struct Held {
    pub clip: usize,
    pub name: String,
    pub frame: usize,
    pub keys: usize,
    pub time: f32,
}

/// Run `shot`, given the arguments after the subcommand.
pub fn run(args: &[String]) -> ExitCode {
    if args.iter().any(|arg| arg == "-h" || arg == "--help") {
        println!("{USAGE}");
        return ExitCode::SUCCESS;
    }
    let request = match parse(args) {
        Ok(request) => request,
        Err(why) => {
            eprintln!("dimentio shot: {why}\n\n{USAGE}");
            return ExitCode::from(2);
        }
    };
    match take(&request) {
        Ok(report) => {
            for line in report.lines() {
                println!("{line}");
            }
            println!("wrote {}", request.out.display());
            ExitCode::SUCCESS
        }
        Err(why) => {
            eprintln!("dimentio shot: {why}");
            ExitCode::FAILURE
        }
    }
}

/// Read the command line. Long flags only: a one-letter alias saves four
/// characters in a line an agent writes once and a human reads later.
pub fn parse(args: &[String]) -> Result<Request, String> {
    let mut model: Option<PathBuf> = None;
    let mut out: Option<PathBuf> = None;
    let mut size = DEFAULT_SIZE;
    let mut angles = DEFAULT_ANGLES;
    let mut clip = 0;
    let mut frame = None;
    let mut background = Background::Checkerboard;

    let mut rest = args.iter();
    while let Some(arg) = rest.next() {
        let mut value = || {
            rest.next()
                .cloned()
                .ok_or_else(|| format!("{arg} needs a value"))
        };
        match arg.as_str() {
            "--out" => out = Some(PathBuf::from(value()?)),
            "--size" => size = number(arg, &value()?)?,
            "--angles" => angles = number(arg, &value()?)?,
            "--clip" => clip = number(arg, &value()?)?,
            "--frame" => frame = Some(number(arg, &value()?)?),
            "--background" => background = named_background(&value()?)?,
            flag if flag.starts_with("--") => return Err(format!("unknown option {flag}")),
            path if model.is_none() => model = Some(PathBuf::from(path)),
            extra => return Err(format!("unexpected argument {extra}")),
        }
    }

    let model = model.ok_or("no model given")?;
    let out = out.ok_or("--out is required; there is nowhere to write to")?;
    if !SIZE_LIMIT.contains(&size) {
        return Err(format!(
            "--size {size} is outside {}..={}",
            SIZE_LIMIT.start(),
            SIZE_LIMIT.end()
        ));
    }
    if !ANGLE_LIMIT.contains(&angles) {
        return Err(format!(
            "--angles {angles} is outside {}..={}",
            ANGLE_LIMIT.start(),
            ANGLE_LIMIT.end()
        ));
    }
    Ok(Request {
        model,
        out,
        size,
        angles,
        clip,
        frame,
        background,
    })
}

fn number(flag: &str, text: &str) -> Result<usize, String> {
    text.parse()
        .map_err(|_| format!("{flag} wants a whole number, not {text:?}"))
}

/// A background by name, matched against the labels the window shows, with
/// spaces written as dashes. Reusing them keeps the two ways of choosing a
/// backdrop from drifting apart.
fn named_background(name: &str) -> Result<Background, String> {
    let wanted = name.trim().to_lowercase().replace(' ', "-");
    render::BACKGROUNDS
        .into_iter()
        .find(|background| background.label().replace(' ', "-") == wanted)
        .ok_or_else(|| {
            let known: Vec<String> = render::BACKGROUNDS
                .iter()
                .map(|background| background.label().replace(' ', "-"))
                .collect();
            format!("unknown background {name:?}; try {}", known.join(", "))
        })
}

/// Load, pose, render and write. The whole command, minus the printing.
pub fn take(request: &Request) -> Result<Report, String> {
    let mut mesh = Mesh::load(&request.model).map_err(|problem| problem.describe())?;
    if mesh.is_empty() {
        return Err(format!(
            "{} holds no triangles, so there is nothing to look at",
            request.model.display()
        ));
    }
    let posed = match request.frame {
        Some(frame) => Some(hold(&mut mesh, request.clip, frame)?),
        None => None,
    };
    let sheet = draw(&mesh, request);
    write_png(&request.out, &sheet.pixels, sheet.size)?;
    Ok(Report {
        sheet: sheet.size,
        angles: request.angles,
        triangles: mesh.faces().len(),
        shapes: mesh.shapes().len(),
        images: mesh.paints().len(),
        posed,
        drawn: sheet.coverage.share(),
        spread: sheet.coverage.spread,
        detail: sheet.coverage.detail,
    })
}

/// Displace the geometry to one keyframe of one clip.
///
/// ⚠️ **A missing clip or frame is an error, not a fallback.** Rendering the
/// rest pose when an animation frame was asked for produces a believable image
/// of the wrong thing, which is worse than no image at all.
fn hold(mesh: &mut Mesh, clip: usize, frame: usize) -> Result<Held, String> {
    let animation = mesh
        .animation()
        .ok_or("this model carries no morph animation, so --frame has nothing to hold")?;
    let clips = animation.clips();
    let chosen = clips
        .get(clip)
        .ok_or_else(|| format!("no clip {clip}; this model has {}", clips.len()))?;
    let key = chosen.keys.get(frame).ok_or_else(|| {
        format!(
            "no frame {frame} in clip {clip} \"{}\"; it has {} keyframe(s)",
            chosen.name,
            chosen.keys.len()
        )
    })?;
    let held = Held {
        clip,
        name: chosen.name.clone(),
        frame,
        keys: chosen.keys.len(),
        time: key.time,
    };
    mesh.pose(clip, held.time);
    Ok(held)
}

/// A contact sheet under construction, and what has been drawn into it.
struct Sheet {
    size: Size,
    pixels: Vec<u8>,
    coverage: Coverage,
}

/// How much of a frame the model reached, and how varied its colours were.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct Coverage {
    pub drawn: usize,
    pub total: usize,
    /// Spread of the drawn pixels' colour away from their own average, with
    /// brightness divided out.
    ///
    /// ⚠️ **Brightness is divided out on purpose.** Shading already varies a
    /// flat surface from ambient to full, so a plain spread of RGB values
    /// cannot tell a lit grey model from a painted one. Dividing each pixel by
    /// its own luminance leaves only the tint, which a flat-shaded model holds
    /// constant and a textured one does not.
    pub spread: f32,
    /// Mean brightness step between side-by-side pixels of the model, over 255.
    ///
    /// ⛔ **Reported, never judged.** It was meant to catch what `spread`
    /// cannot — an image that decoded to near-white — and two measurements on
    /// the real export took it out of the verdict (D253). Small facets read as
    /// texels: the untextured `e_bari_bari` steps 0.099. Magnification reads as
    /// smooth: `OFF_doorL`, a sharp kanji across a quarter of the frame, steps
    /// 0.006, which is what a bare cube steps. It is a second view of the same
    /// pixels, and nothing may be concluded from it alone.
    pub detail: f32,
}

impl Coverage {
    pub fn share(self) -> f32 {
        if self.total == 0 {
            return 0.0;
        }
        self.drawn as f32 / self.total as f32
    }

    fn add(&mut self, other: Self) {
        // Both measures are averaged by the pixels behind them, so a view that
        // drew almost nothing cannot swing the sheet's figures. A flat card is
        // invisible from two of four angles, and those two must not count.
        let drawn = self.drawn + other.drawn;
        if drawn > 0 {
            let mean = |mine: f32, theirs: f32| {
                (mine * self.drawn as f32 + theirs * other.drawn as f32) / drawn as f32
            };
            self.spread = mean(self.spread, other.spread);
            self.detail = mean(self.detail, other.detail);
        }
        self.drawn = drawn;
        self.total += other.total;
    }
}

/// Measure a rendered frame against the backdrop it was drawn on.
///
/// Takes the bytes rather than the `Image` so a test can hand it a frame it
/// built itself, which is the only way to check that the measures rise as well
/// as fall.
pub fn measure(pixels: &[u8], size: Size, background: Background) -> Coverage {
    let mut tints: Vec<[f32; 2]> = Vec::new();
    let mut steps = 0.0f32;
    let mut pairs = 0usize;
    for y in 0..size.height {
        let mut previous: Option<f32> = None;
        for x in 0..size.width {
            let at = (y * size.width + x) * 4;
            let Some(pixel) = pixels.get(at..at + 3) else {
                break;
            };
            let behind = background.pixel(x, y, size);
            if [pixel[0], pixel[1], pixel[2]] == [behind.r, behind.g, behind.b] {
                previous = None;
                continue;
            }
            let (r, g, b) = (
                f32::from(pixel[0]),
                f32::from(pixel[1]),
                f32::from(pixel[2]),
            );
            let luminance = (r + g + b) / 3.0;
            tints.push([(r - g) / luminance.max(1.0), (g - b) / luminance.max(1.0)]);
            if let Some(left) = previous {
                steps += (luminance - left).abs();
                pairs += 1;
            }
            previous = Some(luminance);
        }
    }
    Coverage {
        drawn: tints.len(),
        total: size.pixels(),
        spread: scatter(&tints),
        detail: if pairs == 0 {
            0.0
        } else {
            steps / pairs as f32 / 255.0
        },
    }
}

/// Root-mean-square distance of a set of points from its own centre.
fn scatter(points: &[[f32; 2]]) -> f32 {
    if points.is_empty() {
        return 0.0;
    }
    let count = points.len() as f32;
    let mut centre = [0.0f32; 2];
    for point in points {
        centre[0] += point[0] / count;
        centre[1] += point[1] / count;
    }
    let sum: f32 = points
        .iter()
        .map(|point| {
            let (dx, dy) = (point[0] - centre[0], point[1] - centre[1]);
            dx * dx + dy * dy
        })
        .sum();
    (sum / count).sqrt()
}

/// Render every angle and lay them out in a grid.
///
/// ⚠️ **Evenly spaced from the front, not four hand-picked poses.** Named
/// poses would stop meaning anything the moment `--angles` was not 4, and the
/// axis-aligned views are the ones worth having: a flat shape that disappears
/// edge-on is a fact about the model.
fn draw(mesh: &Mesh, request: &Request) -> Sheet {
    let cell = Size::new(request.size, request.size);
    let columns = grid_columns(request.angles);
    let rows = request.angles.div_ceil(columns);
    let span = |count: usize| count * request.size + count.saturating_sub(1) * GUTTER;
    let size = Size::new(span(columns), span(rows));

    let mut sheet = Sheet {
        size,
        pixels: divided(size),
        coverage: Coverage::default(),
    };
    let fitted = Camera::fit(mesh.bounds());
    for index in 0..request.angles {
        let mut camera = fitted;
        // One angle keeps the fitted three-quarter view: a single frame should
        // be the informative one, not a flat front elevation.
        if request.angles > 1 {
            camera.yaw = TAU * index as f32 / request.angles as f32;
            camera.pitch = SHEET_PITCH;
        }
        let view = View {
            camera,
            background: request.background,
        };
        let image = render::render(mesh, &view, cell);
        sheet
            .coverage
            .add(measure(image.as_rgba(), cell, request.background));
        let column = index % columns;
        let row = index / columns;
        blit(
            &mut sheet,
            &image,
            column * (request.size + GUTTER),
            row * (request.size + GUTTER),
        );
    }
    sheet
}

/// As square a grid as the count allows, widest side first.
fn grid_columns(angles: usize) -> usize {
    let mut columns = 1;
    while columns * columns < angles {
        columns += 1;
    }
    columns.max(1)
}

fn divided(size: Size) -> Vec<u8> {
    [DIVIDER.r, DIVIDER.g, DIVIDER.b, 255].repeat(size.pixels())
}

fn blit(sheet: &mut Sheet, image: &Image, left: usize, top: usize) {
    let cell = image.size();
    let source = image.as_rgba();
    for y in 0..cell.height {
        let into = ((top + y) * sheet.size.width + left) * 4;
        let from = y * cell.width * 4;
        let run = cell.width * 4;
        let Some(target) = sheet.pixels.get_mut(into..into + run) else {
            return;
        };
        target.copy_from_slice(&source[from..from + run]);
    }
}

/// Write RGBA8 out as a PNG, creating the folder above it if it is missing.
fn write_png(path: &Path, pixels: &[u8], size: Size) -> Result<(), String> {
    if let Some(folder) = path
        .parent()
        .filter(|folder| !folder.as_os_str().is_empty())
    {
        std::fs::create_dir_all(folder)
            .map_err(|why| format!("could not create {}: {why}", folder.display()))?;
    }
    let file = std::fs::File::create(path)
        .map_err(|why| format!("could not write {}: {why}", path.display()))?;
    PngEncoder::new(BufWriter::new(file))
        .write_image(
            pixels,
            size.width as u32,
            size.height as u32,
            ExtendedColorType::Rgba8,
        )
        .map_err(|why| format!("could not encode {}: {why}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

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
            let at =
                std::env::temp_dir().join(format!("dimentio-shot-{name}-{}", std::process::id()));
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
    fn an_unreadable_model_is_an_error_and_not_an_empty_png() {
        let scratch = Scratch::new("missing");
        let out = scratch.file("shot.png");
        let request = Request {
            model: scratch.file("nothing-here.glb"),
            out: out.clone(),
            size: 32,
            angles: 1,
            clip: 0,
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
                    if colour
                        != Background::Checkerboard.pixel(x - left, y - top, Size::new(64, 64))
                    {
                        drawn += 1;
                    }
                }
            }
            assert!(drawn > 200, "cell at {left},{top} drew only {drawn} pixels");
        }
    }

    fn cube_coverage() -> Coverage {
        let view = View {
            camera: Camera::fit(cube_mesh().bounds()),
            background: Background::DarkGrey,
        };
        let size = Size::new(128, 128);
        let image = render::render(&cube_mesh(), &view, size);
        measure(image.as_rgba(), size, Background::DarkGrey)
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

    /// A frame filled by hand, so a measure can be shown to rise as well as
    /// fall. `paint` is called for every pixel and returns its colour.
    fn frame(size: Size, paint: impl Fn(usize, usize) -> Rgba) -> Vec<u8> {
        let mut pixels = Vec::with_capacity(size.pixels() * 4);
        for y in 0..size.height {
            for x in 0..size.width {
                let colour = paint(x, y);
                pixels.extend_from_slice(&[colour.r, colour.g, colour.b, 255]);
            }
        }
        pixels
    }

    /// ⚠️ The other half of the control. A `measure` that returned zero for
    /// everything would pass the bare-cube test above and call every model in
    /// the export untextured — which is the failure this tool is meant to
    /// detect, arriving in the detector itself.
    #[test]
    fn both_measures_rise_on_a_frame_that_really_is_painted() {
        let size = Size::new(64, 64);
        let hues = frame(size, |x, y| {
            Rgba::new(
                ((x * 53 + y * 7) % 256) as u8,
                ((x * 11 + y * 97) % 256) as u8,
                ((x * 29 + y * 61) % 256) as u8,
            )
        });
        let measured = measure(&hues, size, Background::DarkGrey);
        assert_eq!(measured.drawn, size.pixels());
        assert!(measured.spread > FLAT_SPREAD, "spread {}", measured.spread);
        assert!(measured.detail > 0.05, "detail {}", measured.detail);

        // Grey, and smooth: one tint, and neighbours that agree. This is what
        // an image decoding to near-white would look like.
        let pale = frame(size, |_, y| {
            let level = 230 + (y / 32) as u8;
            Rgba::new(level, level, level)
        });
        let washed = measure(&pale, size, Background::DarkGrey);
        assert!(washed.spread < FLAT_SPREAD, "spread {}", washed.spread);
        assert!(washed.detail < 0.01, "detail {}", washed.detail);
    }

    /// A pixel that happens to match the backdrop is not counted as drawn, and
    /// the run of neighbours is broken there rather than measured across the
    /// gap.
    #[test]
    fn the_backdrop_is_not_measured_as_part_of_the_model() {
        let size = Size::new(8, 8);
        let sky = Background::DarkGrey;
        let bare = frame(size, |x, y| sky.pixel(x, y, size));
        let measured = measure(&bare, size, sky);
        assert_eq!(measured.drawn, 0);
        assert_eq!(measured.total, size.pixels());
        assert_eq!(measured.share(), 0.0);
        assert_eq!(measured.spread, 0.0);
        assert_eq!(measured.detail, 0.0);
    }

    /// The other half of that control, without a textured fixture to hand: the
    /// measure itself must rise when the colours actually vary. Without this a
    /// `spread` stuck at zero would still pass the test above.
    #[test]
    fn the_measure_rises_with_colour_and_not_with_brightness() {
        let shaded: Vec<[f32; 2]> = (1..=16)
            .map(|step| {
                let intensity = step as f32 / 16.0;
                let (r, g, b) = (214.0 * intensity, 208.0 * intensity, 196.0 * intensity);
                let luminance = ((r + g + b) / 3.0).max(1.0);
                [(r - g) / luminance, (g - b) / luminance]
            })
            .collect();
        assert!(
            scatter(&shaded) < 1e-3,
            "one tint scattered {}",
            scatter(&shaded)
        );

        let painted: Vec<[f32; 2]> = [
            (220.0, 30.0, 40.0),
            (20.0, 200.0, 60.0),
            (30.0, 40.0, 210.0),
            (200.0, 200.0, 40.0),
        ]
        .into_iter()
        .map(|(r, g, b): (f32, f32, f32)| {
            let luminance = ((r + g + b) / 3.0).max(1.0);
            [(r - g) / luminance, (g - b) / luminance]
        })
        .collect();
        assert!(
            scatter(&painted) > FLAT_SPREAD,
            "four hues scattered only {}",
            scatter(&painted)
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

    #[test]
    fn the_grid_stays_as_square_as_the_count_allows() {
        assert_eq!(grid_columns(1), 1);
        assert_eq!(grid_columns(2), 2);
        assert_eq!(grid_columns(4), 2);
        assert_eq!(grid_columns(6), 3);
        assert_eq!(grid_columns(9), 3);
        assert_eq!(grid_columns(16), 4);
    }
}
