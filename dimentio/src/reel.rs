//! `dimentio reel` — render one effect across its own timeline to a PNG and exit.
//!
//! The effect counterpart of `shot`. A shot is one instant from several angles;
//! a reel is one angle at several instants, because what there is to check about
//! an effect is *when* things happen. Both write one contact sheet through the
//! same software rasteriser, so a caller with no screen can look at either.
//!
//! ⛔ **This sheet shows the timeline, not the artwork.** Which image a part
//! draws is not decoded — six candidate fields are refuted in
//! `docs/decision-log.md` D210, and the real reference is one hop further out
//! (D218). Every part is therefore drawn as a flat colour, and the layout is a
//! deterministic display choice rather than a decoded scene graph. The report
//! says so on every run, because a grid of coloured quads is exactly what
//! someone would mistake for a picture of the effect.
//!
//! What it *can* settle is whether the effect data and the renderer agree: that
//! the parts the manifest says are running at a time are the parts that reach
//! the frame, and that the frame changes when a part starts or stops.

use std::path::PathBuf;
use std::process::ExitCode;

use crate::data::catalog::Catalog;
use crate::data::effects::{frame_at, image_at, Entry, Library};
use crate::data::texture::Texture;
use crate::render::{self, effect, Background, Camera, Image, Piece, Rgba, Size, View};
use crate::shot::{
    blit, divided, grid_columns, measure, named_background, number, write_png, Coverage, Sheet,
    GUTTER, SIZE_LIMIT,
};

/// Cell edge when `--size` is not given. Smaller than a model shot's, because a
/// reel holds more cells and a part is a flat quad with no detail to lose.
const DEFAULT_SIZE: usize = 320;

const DEFAULT_FRAMES: usize = 9;

/// Bound on the cell count, for the same reason `shot` bounds its angles: a
/// mistyped `--frames` should be a message, not an allocation failure.
const FRAME_LIMIT: std::ops::RangeInclusive<usize> = 1..=64;

/// Where `bleck effect export --out` writes by default.
const DEFAULT_EXPORT: &str = "work/export";

/// How many near names an unknown effect is offered.
const SUGGESTIONS: usize = 6;

pub const USAGE: &str = "\
dimentio reel --effect <name> --out <file.png> [options]

  --effect <name>    which effect, as `bleck effect list` names it. Required.
  --out <file.png>   where to write. Required.
  --export <dir>     folder holding effects.json. Default work/export.
  --frames <n>       frames sampled across the effect, into one sheet. Default 9.
  --size <n>         edge of one frame, in pixels. Default 320.
  --background <s>   dark-grey | checkerboard | gradient. Default checkerboard.

Frames run left to right, top to bottom. The effect is drawn from one fixed
camera so the cells can be compared against each other.";

/// What a run was asked for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    pub effect: String,
    pub export: PathBuf,
    pub out: PathBuf,
    pub size: usize,
    pub frames: usize,
    pub background: Background,
}

/// One cell of the reel.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Frame {
    /// The game's own frame number, counted from 1 the way the durations are.
    pub number: u32,
    pub time: f32,
    /// Parts the manifest says are running at `time`.
    pub active: usize,
    /// How many of those carried a decoded image into this cell.
    pub painted: usize,
    /// How many of the **unpainted** parts can be told apart by colour.
    ///
    /// ⚠️ **Two separate ceilings, and both bite.** A painted part is drawn in
    /// its texture's colours, so its flat palette shade is not in the frame and
    /// searching for it would report it missing. And the palette holds only six
    /// colours before repeating, so a seventh unpainted part is drawn in the
    /// first one's shade. `visible` is measured against this rather than
    /// against `active`, which would report a fault on every textured effect.
    pub distinct: usize,
    /// How many of those distinct colours were actually found in the cell.
    ///
    /// ⚠️ Below `distinct` means a part did not reach the frame. That is
    /// usually occlusion — one quad in front of another, which the shared depth
    /// buffer is right to do — and only sometimes a fault. It is reported
    /// rather than judged.
    pub visible: usize,
    /// Share of the cell the effect covers, 0..1.
    pub drawn: f32,
}

/// What the run found, in the terms a caller with no screen can act on.
#[derive(Debug, Clone, PartialEq)]
pub struct Report {
    pub name: String,
    pub index: usize,
    pub parts: usize,
    pub seconds: f32,
    /// The effect's whole length in frames, which bounds how many can be shown.
    pub length: u32,
    pub sheet: Size,
    pub frames: Vec<Frame>,
    /// Consecutive cell pairs whose pixels differ at all.
    pub changes: usize,
    /// Parts that carried a real image anywhere in the reel.
    ///
    /// ⚠️ **Counted from the meshes, not written down as zero.** It is zero
    /// today because no part-to-image binding is decoded, and it will start
    /// reporting the truth the day one is, with nothing here to remember to
    /// change. A hardcoded zero would quietly outlive the limitation.
    pub painted: usize,
}

impl Report {
    /// Whether every part the manifest called running reached its own cell.
    ///
    /// ⚠️ Measured against `distinct`, not `active` — see `Frame::distinct`.
    /// Against `active` this would report a fault for any effect with more than
    /// six parts, every time, on no evidence.
    pub fn parts_all_arrived(&self) -> bool {
        self.frames
            .iter()
            .all(|frame| frame.visible >= frame.distinct)
    }

    /// Whether the reel shows the effect doing anything over time.
    ///
    /// ⚠️ A one-part effect changes nothing between its first frame and its
    /// last, and that is correct rather than broken — the parts only start and
    /// stop, because no per-frame motion is decoded. So this is reported, not
    /// asserted, and a `false` for a single-part effect means nothing.
    pub fn moves(&self) -> bool {
        self.changes > 0
    }

    pub fn lines(&self) -> Vec<String> {
        let mut said = vec![
            format!(
                "{} — {} part(s), {:.2}s, {} frame(s) long",
                self.name, self.parts, self.seconds, self.length
            ),
            format!(
                "{} frame(s) sampled into {}x{}",
                self.frames.len(),
                self.sheet.width,
                self.sheet.height
            ),
        ];
        said.extend(self.frames.iter().map(|frame| {
            // The ceiling is only worth naming when it bites; on the great
            // majority of effects it equals the active count and saying so
            // every line would bury the numbers that vary.
            let unpainted = frame.active - frame.painted;
            // Only worth a column when there is something in it. On a fully
            // textured effect "0 of 0 plain found" is noise in every row.
            let plain = if unpainted == 0 {
                String::new()
            } else if frame.distinct < unpainted {
                format!(
                    ", {} of {} plain found ({} tellable apart)",
                    frame.visible, unpainted, frame.distinct
                )
            } else {
                format!(", {} of {} plain found", frame.visible, unpainted)
            };
            format!(
                "  frame {:>4} at {:>6.3}s — {} active, {} painted{}, {:.1}% drawn",
                frame.number,
                frame.time,
                frame.active,
                frame.painted,
                plain,
                frame.drawn * 100.0
            )
        }));
        said.push(format!(
            "{} of {} frame pair(s) differ{}",
            self.changes,
            self.frames.len().saturating_sub(1),
            // ⚠️ Said, not judged. A one-part effect is identical from its
            // first frame to its last and is working perfectly.
            if self.moves() || self.frames.len() < 2 {
                ""
            } else {
                " — nothing changes across the reel"
            }
        ));
        // ⚠️ Never claim a clean check that was not made. A fully textured
        // effect has no part findable by its flat colour, so "every active part
        // reached its frame" would be true of a reel that drew nothing.
        let checkable: usize = self.frames.iter().map(|frame| frame.distinct).sum();
        said.push(if checkable == 0 {
            "no part is identifiable by colour here, so arrival was not checked \
             — the drawn percentages are the only evidence"
                .to_owned()
        } else if self.parts_all_arrived() {
            "every part identifiable by colour reached its frame".to_owned()
        } else {
            "some parts did not reach their frame — occluded, or missing".to_owned()
        });
        said.push(self.caveat());
        said
    }

    /// ⚠️ Printed on every run, deliberately. The images are measured and the
    /// **placement is not**, and a sheet that shows real artwork in invented
    /// positions is far more convincing than one drawn in flat colours — so the
    /// half that is still a display choice has to be said out loud every time.
    fn caveat(&self) -> String {
        if self.painted == 0 {
            return format!(
                "no part of {} carries an image — either they genuinely draw none, or this \
                 export predates the part-to-image binding (D258); re-run `bleck effect export`",
                self.name
            );
        }
        format!(
            "{} of {} part(s) drew a decoded image (D258). ⛔ Where the quads sit is still a \
             display choice, not a decoded scene graph — the node transforms are read but not \
             applied, so do not read a position here as where the game puts it.",
            self.painted, self.parts
        )
    }
}

/// Run `reel`, given the arguments after the subcommand.
pub fn run(args: &[String]) -> ExitCode {
    if args.iter().any(|arg| arg == "-h" || arg == "--help") {
        println!("{USAGE}");
        return ExitCode::SUCCESS;
    }
    let request = match parse(args) {
        Ok(request) => request,
        Err(why) => {
            eprintln!("dimentio reel: {why}\n\n{USAGE}");
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
            eprintln!("dimentio reel: {why}");
            ExitCode::FAILURE
        }
    }
}

/// Read the command line. Long flags only, matching `shot`.
pub fn parse(args: &[String]) -> Result<Request, String> {
    let mut effect = None;
    let mut out = None;
    let mut export = PathBuf::from(DEFAULT_EXPORT);
    let mut size = DEFAULT_SIZE;
    let mut frames = DEFAULT_FRAMES;
    let mut background = Background::Checkerboard;

    let mut rest = args.iter();
    while let Some(arg) = rest.next() {
        let mut value = || {
            rest.next()
                .cloned()
                .ok_or_else(|| format!("{arg} needs a value"))
        };
        match arg.as_str() {
            "--effect" => effect = Some(value()?),
            "--out" => out = Some(PathBuf::from(value()?)),
            "--export" => export = PathBuf::from(value()?),
            "--size" => size = number(arg, &value()?)?,
            "--frames" => frames = number(arg, &value()?)?,
            "--background" => background = named_background(&value()?)?,
            flag if flag.starts_with("--") => return Err(format!("unknown option {flag}")),
            extra => return Err(format!("unexpected argument {extra}")),
        }
    }

    let effect = effect.ok_or("--effect is required; `bleck effect list` names them")?;
    let out = out.ok_or("--out is required; there is nowhere to write to")?;
    if !SIZE_LIMIT.contains(&size) {
        return Err(format!(
            "--size {size} is outside {}..={}",
            SIZE_LIMIT.start(),
            SIZE_LIMIT.end()
        ));
    }
    if !FRAME_LIMIT.contains(&frames) {
        return Err(format!(
            "--frames {frames} is outside {}..={}",
            FRAME_LIMIT.start(),
            FRAME_LIMIT.end()
        ));
    }
    Ok(Request {
        effect,
        export,
        out,
        size,
        frames,
        background,
    })
}

/// Load, render every sampled frame, write the sheet.
pub fn take(request: &Request) -> Result<Report, String> {
    let library = Library::load(&request.export);
    if let Some(problem) = library.problem() {
        return Err(problem.describe());
    }
    let entry = library
        .entries()
        .iter()
        .find(|entry| entry.name == request.effect)
        .ok_or_else(|| unknown(&library, &request.effect))?;
    if entry.parts.is_empty() {
        return Err(format!(
            "{} has no parts, so there is nothing to draw",
            entry.name
        ));
    }

    let sampled = sample(entry, request.frames);
    let art = resolve_art(entry, &request.export, library.textures());
    let built = draw(entry, &sampled, &art, request);
    write_png(&request.out, &built.sheet.pixels, built.sheet.size)?;
    Ok(Report {
        name: entry.name.clone(),
        index: entry.index,
        parts: entry.parts.len(),
        seconds: entry.seconds,
        length: entry.frames(),
        sheet: built.sheet.size,
        frames: built.frames,
        changes: built.changes,
        painted: built.painted,
    })
}

/// What an unknown name is answered with.
///
/// ⚠️ The names offered are the *library's*, never the one asked for. An
/// earlier test in this repo passed because the error message quoted the search
/// term back and the assertion found it there, so nothing was resolving and the
/// suite was green (D-era lesson, kept as a comment because it cost a day).
fn unknown(library: &Library, wanted: &str) -> String {
    let near: Vec<&str> = library
        .matching(wanted)
        .into_iter()
        .filter_map(|index| library.entries().get(index))
        .map(|entry| entry.name.as_str())
        .filter(|name| *name != wanted)
        .take(SUGGESTIONS)
        .collect();
    if near.is_empty() {
        return format!(
            "no effect named {wanted:?}; the export holds {} — `bleck effect list` names them",
            library.len()
        );
    }
    format!(
        "no effect named {wanted:?}; near names: {}",
        near.join(", ")
    )
}

/// The times to render, evenly across the effect and including both ends.
///
/// ⚠️ **Never more cells than the effect has frames.** Asking for nine views of
/// a one-frame effect would lay out nine identical pictures, and a reader
/// counting them would see an animation that is not there.
fn sample(entry: &Entry, wanted: usize) -> Vec<f32> {
    let count = wanted.clamp(1, entry.frames().max(1) as usize);
    if count == 1 {
        return vec![0.0];
    }
    (0..count)
        .map(|index| entry.seconds * index as f32 / (count - 1) as f32)
        .collect()
}

/// The sheet and everything measured while filling it.
struct Built {
    sheet: Sheet,
    frames: Vec<Frame>,
    changes: usize,
    painted: usize,
}

/// Decode the image each part of `entry` draws, from the texture catalog
/// beside the effect manifest.
///
/// ⚠️ A picture that cannot be read leaves its part unpainted rather than
/// failing the run. The report counts what actually arrived, so a missing PNG
/// shows up as a lower `painted` rather than as a crash or a silent flat quad
/// indistinguishable from a part that genuinely draws nothing.
fn resolve_art(entry: &Entry, root: &std::path::Path, source: &str) -> Vec<Option<Texture>> {
    let catalog = Catalog::load(root);
    entry
        .parts
        .iter()
        .map(|part| {
            let picture = part.pictures.first()?;
            let at = image_at(catalog.entries(), source, picture.image)?;
            let found = catalog.entries().get(at)?;
            Texture::decode(&std::fs::read(&found.path).ok()?).ok()
        })
        .collect()
}

fn draw(entry: &Entry, times: &[f32], art: &[Option<Texture>], request: &Request) -> Built {
    let cell = Size::new(request.size, request.size);
    let columns = grid_columns(times.len());
    let rows = times.len().div_ceil(columns);
    let span = |count: usize| count * request.size + count.saturating_sub(1) * GUTTER;
    let size = Size::new(span(columns), span(rows));

    let mut sheet = Sheet {
        size,
        pixels: divided(size),
        coverage: Coverage::default(),
    };
    // One camera for the whole reel. Refitting per frame would rescale the view
    // as parts stop, so a part ending would look like the rest moving.
    let camera = Camera::fit(effect::bounds(entry));
    let view = View {
        camera,
        background: request.background,
    };

    let mut frames = Vec::with_capacity(times.len());
    let mut changes = 0;
    let mut painted = vec![false; entry.parts.len()];
    let mut previous: Option<Image> = None;

    for (index, &time) in times.iter().enumerate() {
        let quads = effect::quads(entry, time, &camera, Some(effect::Art { images: art }));
        for quad in &quads {
            if let Some(seen) = painted.get_mut(quad.part) {
                *seen |= !quad.mesh.paints().is_empty();
            }
        }
        let pieces: Vec<Piece<'_>> = quads
            .iter()
            .map(|quad| Piece {
                mesh: &quad.mesh,
                flat: quad.colour,
            })
            .collect();
        let image = render::scene(&pieces, &view, cell);

        let coverage = measure(image.as_rgba(), cell, request.background);
        let present = shades(&image, request.background);
        // Only the unpainted quads can be found by their flat colour; a
        // textured one is drawn in its image's colours instead.
        let plain: Vec<Rgba> = quads
            .iter()
            .filter(|quad| quad.mesh.paints().is_empty())
            .map(|quad| effect::lit(&camera, quad.part))
            .collect();
        let wanted = deduped(&plain);
        frames.push(Frame {
            number: frame_at(time),
            time,
            active: quads.len(),
            painted: quads.len() - plain.len(),
            distinct: wanted.len(),
            visible: wanted
                .iter()
                .filter(|colour| present.contains(colour))
                .count(),
            drawn: coverage.share(),
        });
        if previous
            .as_ref()
            .is_some_and(|before| before.as_rgba() != image.as_rgba())
        {
            changes += 1;
        }

        sheet.coverage.add(coverage);
        blit(
            &mut sheet,
            &image,
            (index % columns) * (request.size + GUTTER),
            (index / columns) * (request.size + GUTTER),
        );
        previous = Some(image);
    }

    Built {
        sheet,
        frames,
        changes,
        painted: painted.iter().filter(|seen| **seen).count(),
    }
}

/// `colours` with repeats removed, in first-seen order.
///
/// ⚠️ Kept as its own function so a test can show the counting above can
/// return *less* than it was given. Measured against a render alone, a
/// `visible` that simply echoed `active` would agree with every frame and look
/// like a confirmation.
fn deduped(colours: &[Rgba]) -> Vec<Rgba> {
    let mut seen: Vec<Rgba> = Vec::new();
    for colour in colours {
        if !seen.contains(colour) {
            seen.push(*colour);
        }
    }
    seen
}

/// Every distinct colour in `image` that is not the backdrop.
///
/// ⚠️ Compared against the backdrop *at each pixel*, not against one colour:
/// the checkerboard has two, and treating either as part of the effect would
/// report a full frame every time.
fn shades(image: &Image, background: Background) -> Vec<Rgba> {
    let size = image.size();
    let mut seen: Vec<Rgba> = Vec::new();
    for y in 0..size.height {
        for x in 0..size.width {
            let pixel = image.pixel(x, y);
            if pixel != background.pixel(x, y, size) && !seen.contains(&pixel) {
                seen.push(pixel);
            }
        }
    }
    seen
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A folder no other test writes into, removed when the test ends.
    struct Scratch(PathBuf);

    impl Scratch {
        fn new(name: &str) -> Self {
            static NEXT: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
            let count = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let at = std::env::temp_dir().join(format!(
                "dimentio-reel-{name}-{}-{count}",
                std::process::id()
            ));
            let _ = std::fs::remove_dir_all(&at);
            std::fs::create_dir_all(&at).expect("scratch folder");
            Self(at)
        }

        fn file(&self, name: &str) -> PathBuf {
            self.0.join(name)
        }

        fn manifest(&self, text: &str) -> &Self {
            std::fs::write(self.0.join("effects.json"), text).expect("manifest");
            self
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

    /// Two effects: one whose second part stops halfway, and a single-frame one.
    /// The rows point along different axes so no two quads can overlap and hide
    /// what a count is measuring.
    const MANIFEST: &str = r#"{"schema": 1,
      "textures": "files/eff/effdata.tpl",
      "effects": [
        {"name": "twopart", "index": 0, "seconds": 2.0,
         "parts": [{"name": "A", "composed": "twopartA", "index": 0,
                    "frames": 121, "seconds": 2.0},
                   {"name": "B", "composed": "twopartB", "index": 1,
                    "frames": 31, "seconds": 0.5}],
         "rows": [{"index": 0, "values": [1.0, 0.0, 0.0, 0.0]},
                  {"index": 1, "values": [0.0, 1.0, 0.0, 0.0]}]},
        {"name": "blink", "index": 1, "seconds": 0.0,
         "parts": [{"name": "A", "composed": "blinkA", "index": 2,
                    "frames": 1, "seconds": 0.0}],
         "rows": []},
        {"name": "hollow", "index": 2, "seconds": 0.0, "parts": [], "rows": []}
      ]}"#;

    fn scratch_with_manifest(name: &str) -> Scratch {
        let scratch = Scratch::new(name);
        scratch.manifest(MANIFEST);
        scratch
    }

    fn request(scratch: &Scratch, effect: &str, frames: usize) -> Request {
        Request {
            effect: effect.to_owned(),
            export: scratch.0.clone(),
            out: scratch.file(&format!("{effect}.png")),
            size: 64,
            frames,
            background: Background::DarkGrey,
        }
    }

    #[test]
    fn the_defaults_are_a_nine_frame_sheet_from_the_usual_export() {
        let parsed = parse(&words("--effect chaos --out reel.png")).expect("parses");
        assert_eq!(parsed.effect, "chaos");
        assert_eq!(parsed.out, PathBuf::from("reel.png"));
        assert_eq!(parsed.export, PathBuf::from(DEFAULT_EXPORT));
        assert_eq!(parsed.size, DEFAULT_SIZE);
        assert_eq!(parsed.frames, DEFAULT_FRAMES);
        assert_eq!(parsed.background, Background::Checkerboard);
    }

    #[test]
    fn every_option_is_read() {
        let parsed = parse(&words(
            "--effect hit --out a/b.png --export e/f --size 48 --frames 4 --background gradient",
        ))
        .expect("parses");
        assert_eq!(parsed.effect, "hit");
        assert_eq!(parsed.export, PathBuf::from("e/f"));
        assert_eq!(parsed.size, 48);
        assert_eq!(parsed.frames, 4);
        assert_eq!(parsed.background, Background::Gradient);
    }

    #[test]
    fn a_command_line_that_cannot_work_is_refused_before_anything_is_read() {
        for line in [
            "",
            "--effect chaos",
            "--out reel.png",
            "--effect chaos --out reel.png --size 0",
            "--effect chaos --out reel.png --frames 0",
            "--effect chaos --out reel.png --frames 999",
            "--effect chaos --out reel.png --background white",
            "--effect chaos --out reel.png --colour red",
            "--effect",
            "chaos --out reel.png",
        ] {
            assert!(parse(&words(line)).is_err(), "{line:?} was accepted");
        }
    }

    #[test]
    fn a_missing_export_names_the_command_that_writes_one() {
        let scratch = Scratch::new("noexport");
        let why = take(&request(&scratch, "chaos", 4)).expect_err("no manifest");
        assert!(why.contains("bleck effect export"), "{why}");
    }

    /// ⚠️ The suggestion must come from the library, not from the search term.
    /// A message that quotes the input back would satisfy a careless assertion
    /// while resolving nothing.
    #[test]
    fn an_unknown_effect_suggests_names_the_export_really_holds() {
        let scratch = scratch_with_manifest("unknown");
        let why = take(&request(&scratch, "twopar", 4)).expect_err("no such effect");
        assert!(why.contains("twopart"), "{why}");

        let missing = take(&request(&scratch, "dimentio", 4)).expect_err("no such effect");
        assert!(missing.contains("3"), "the count is not in {missing:?}");
        assert!(
            !missing.contains("twopart"),
            "an unrelated name was offered: {missing}"
        );
    }

    #[test]
    fn an_effect_with_no_parts_is_an_error_and_not_a_blank_sheet() {
        let scratch = scratch_with_manifest("hollow");
        let asked = request(&scratch, "hollow", 4);
        let why = take(&asked).expect_err("nothing to draw");
        assert!(why.contains("no parts"), "{why}");
        assert!(!asked.out.exists(), "a failed run still wrote a file");
    }

    #[test]
    fn a_reel_is_a_grid_of_frames_across_the_whole_duration() {
        let scratch = scratch_with_manifest("grid");
        let report = take(&request(&scratch, "twopart", 4)).expect("renders");
        assert_eq!(report.name, "twopart");
        assert_eq!(report.parts, 2);
        assert_eq!(report.frames.len(), 4);
        assert_eq!(report.sheet, Size::new(64 * 2 + GUTTER, 64 * 2 + GUTTER));

        let times: Vec<f32> = report.frames.iter().map(|frame| frame.time).collect();
        assert_eq!(times, vec![0.0, 2.0 / 3.0, 4.0 / 3.0, 2.0]);
        assert_eq!(report.frames[0].number, 1, "frames count from one");
        assert_eq!(report.frames[3].number, 121, "2s at 60Hz, inclusive");
    }

    /// The measurement the whole command exists for: the parts the manifest
    /// says are running are the parts that reach the frame, and the count falls
    /// when the short part ends.
    /// The measurement the whole command exists for: the parts the manifest
    /// says are running are the parts that reach the frame, and the count falls
    /// when the short part ends.
    ///
    /// ⚠️ **The 0.5s part is still running at exactly 0.5s.** A duration names
    /// a part's last frame rather than the frame after it, so five samples over
    /// two seconds give `2, 2, 1, 1, 1` and not `2, 1, 1, 1, 1`. Writing the
    /// exclusive answer here is what this test caught first.
    #[test]
    fn the_parts_drawn_match_the_parts_the_manifest_calls_running() {
        let scratch = scratch_with_manifest("counts");
        let report = take(&request(&scratch, "twopart", 5)).expect("renders");
        let times: Vec<f32> = report.frames.iter().map(|frame| frame.time).collect();
        assert_eq!(times, vec![0.0, 0.5, 1.0, 1.5, 2.0]);
        let active: Vec<usize> = report.frames.iter().map(|frame| frame.active).collect();
        assert_eq!(active, vec![2, 2, 1, 1, 1], "the short part's last frame");

        for frame in &report.frames {
            assert_eq!(
                frame.visible, frame.distinct,
                "at {:.3}s {} parts were tellable apart and {} were drawn",
                frame.time, frame.distinct, frame.visible
            );
            assert!(frame.drawn > 0.0, "nothing drew at {:.3}s", frame.time);
        }
        // Two parts really do cover more of the cell than one, so the count
        // falling is visible in the pixels and not only in the manifest.
        assert!(
            report.frames[1].drawn > report.frames[2].drawn,
            "losing a part did not shrink the drawn area: {:?}",
            report.frames
        );
        assert!(report.parts_all_arrived());
        assert!(report.moves(), "the frames never changed");
        assert!(report.changes >= 1);
    }

    /// ⚠️ **The control for the test above**, which would be vacuous if
    /// `visible` were simply `active` under another name. The counting is a
    /// plain set intersection, so it is shown here returning *less* than it was
    /// given — which is the direction a render on this layout never produces.
    ///
    /// ⛔ An earlier version of this test tried to force the drop by stacking
    /// two parts on one line of sight. `Camera::fit` returns a three-quarter
    /// view, so they did not overlap and the test failed. Reaching for the
    /// occlusion again would mean hard-coding the fit's angles here, and it
    /// would break silently the day the fit changed.
    #[test]
    fn visible_is_counted_from_the_pixels_and_not_from_the_manifest() {
        let red = Rgba::new(200, 40, 40);
        let green = Rgba::new(40, 200, 40);
        let blue = Rgba::new(40, 40, 200);

        let wanted = deduped(&[red, green, blue]);
        assert_eq!(wanted.len(), 3);
        let present = [red, blue];
        let found = wanted.iter().filter(|c| present.contains(c)).count();
        assert_eq!(found, 2, "a colour that never drew was counted anyway");

        // Nothing on screen counts as nothing found, rather than as everything.
        assert_eq!(wanted.iter().filter(|c| [].contains(c)).count(), 0);
    }

    /// ⚠️ The palette repeats after six, so a seventh part is drawn in the
    /// first one's shade and the pixels cannot separate them. `distinct` is
    /// that ceiling, and the verdict is measured against it — otherwise every
    /// effect with seven parts would report a fault on no evidence.
    #[test]
    fn parts_beyond_the_palette_lower_the_ceiling_rather_than_failing() {
        let camera = Camera::fit(render::effect::bounds(&Entry {
            parts: vec![Default::default(); 8],
            ..Default::default()
        }));
        let shades: Vec<Rgba> = (0..8).map(|part| effect::lit(&camera, part)).collect();
        assert_eq!(shades[0], shades[6], "the palette stopped repeating at six");
        assert_eq!(deduped(&shades).len(), 6, "{shades:?}");

        let frame = Frame {
            number: 1,
            time: 0.0,
            active: 8,
            painted: 0,
            distinct: 6,
            visible: 6,
            drawn: 0.1,
        };
        let report = Report {
            name: "crowded".to_owned(),
            index: 0,
            parts: 8,
            seconds: 1.0,
            length: 61,
            sheet: Size::new(64, 64),
            frames: vec![frame],
            changes: 0,
            painted: 0,
        };
        assert!(
            report.parts_all_arrived(),
            "eight parts in a six-colour palette read as a fault"
        );
        assert!(
            report.lines().iter().any(|l| l.contains("tellable apart")),
            "the ceiling was not reported: {:?}",
            report.lines()
        );
    }

    /// ⚠️ Nine views of a one-frame effect would be nine identical pictures,
    /// and a reader counting cells would see an animation that is not there.
    #[test]
    fn a_single_frame_effect_is_shown_once_however_many_frames_were_asked_for() {
        let scratch = scratch_with_manifest("blink");
        let report = take(&request(&scratch, "blink", 9)).expect("renders");
        assert_eq!(report.length, 1);
        assert_eq!(report.frames.len(), 1);
        assert_eq!(report.frames[0].time, 0.0);
        assert_eq!(report.changes, 0, "one cell cannot differ from itself");
        assert!(report.frames[0].drawn > 0.0, "the one frame drew nothing");
        assert!(!report.moves());
    }

    /// An export written before D258 carries no `pictures`, and must still
    /// load — but it must not look like an effect that genuinely draws nothing.
    /// ⚠️ The message names the command that fixes it, because "0 painted" on
    /// its own sends someone hunting a rendering bug that is not there.
    #[test]
    fn an_export_predating_the_binding_says_so_rather_than_reading_as_empty() {
        let scratch = scratch_with_manifest("caveat");
        let report = take(&request(&scratch, "twopart", 3)).expect("renders");
        assert_eq!(report.painted, 0, "the fixture carries no pictures");
        let last = report.lines().pop().expect("a caveat line");
        assert!(last.contains("bleck effect export"), "{last}");
        assert!(last.contains("D258"), "{last}");
    }

    #[test]
    fn the_png_is_readable_and_is_not_one_colour() {
        let scratch = scratch_with_manifest("png");
        let mut asked = request(&scratch, "twopart", 4);
        asked.out = scratch.file("deep/reel.png");
        let report = take(&asked).expect("renders");

        let decoded = image::open(&asked.out)
            .expect("the PNG reads back")
            .to_rgba8();
        assert_eq!(decoded.width(), report.sheet.width as u32);
        assert_eq!(decoded.height(), report.sheet.height as u32);
        let first = decoded.as_raw()[..4].to_vec();
        assert!(
            decoded.as_raw().chunks(4).any(|pixel| pixel != first),
            "the PNG is a single colour"
        );
    }

    /// Every cell is drawn, not one cell copied across the grid — the same
    /// check the model sheet makes, for the same reason.
    #[test]
    fn each_cell_of_the_sheet_holds_its_own_render() {
        let scratch = scratch_with_manifest("cells");
        let report = take(&request(&scratch, "twopart", 4)).expect("renders");
        let decoded = image::open(scratch.file("twopart.png"))
            .expect("the PNG reads back")
            .to_rgba8();
        let sky = Background::DarkGrey.pixel(0, 0, Size::new(64, 64));

        for (left, top) in [(0, 0), (66, 0), (0, 66), (66, 66)] {
            let drawn = (top..top + 64)
                .flat_map(|y| (left..left + 64).map(move |x| (x, y)))
                .filter(|&(x, y)| {
                    let pixel = decoded.get_pixel(x, y).0;
                    [pixel[0], pixel[1], pixel[2]] != [sky.r, sky.g, sky.b]
                })
                .count();
            assert!(drawn > 100, "cell at {left},{top} drew only {drawn} pixels");
        }
        assert_eq!(report.frames.len(), 4);
    }

    #[test]
    fn the_sample_times_span_the_effect_and_never_exceed_its_length() {
        let entry = Entry {
            name: "probe".into(),
            seconds: 1.0,
            parts: vec![Default::default()],
            ..Default::default()
        };
        assert_eq!(sample(&entry, 1), vec![0.0]);
        assert_eq!(sample(&entry, 3), vec![0.0, 0.5, 1.0]);
        assert_eq!(sample(&entry, 5).len(), 5);

        let instant = Entry {
            name: "blink".into(),
            seconds: 0.0,
            parts: vec![Default::default()],
            ..Default::default()
        };
        assert_eq!(instant.frames(), 1);
        assert_eq!(sample(&instant, 40), vec![0.0]);
    }
}

/// The real export, when one happens to be on this machine.
///
/// ⚠️ `work/` is git-ignored, so these skip rather than fail on a fresh clone
/// or in CI. They exist because every fixture above is written by this file's
/// own tests, and a hand-written manifest cannot catch what 139 real effects do.
#[cfg(test)]
mod real_export_tests {
    use super::*;
    use std::path::Path;

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
        assert!(caveat.contains("display choice"), "{caveat}");
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
        for entry in library.entries() {
            let out = folder.join("sweep.png");
            let asked = Request {
                effect: entry.name.clone(),
                export: export.clone(),
                out: out.clone(),
                size: 48,
                frames: 3,
                background: Background::DarkGrey,
            };
            match take(&asked) {
                Ok(report) => {
                    assert!(
                        report.frames[0].drawn > 0.0,
                        "{} drew nothing at its first frame",
                        entry.name
                    );
                    // A part carrying a picture must reach a decoded image:
                    // that is the export and the catalog agreeing.
                    let declared = entry
                        .parts
                        .iter()
                        .filter(|part| !part.pictures.is_empty())
                        .count();
                    assert_eq!(
                        report.painted, declared,
                        "{}: {declared} part(s) declare a picture, {} were painted",
                        entry.name, report.painted
                    );
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
        // ⚠️ The control on the assertion above: if every effect declared no
        // pictures, `painted == declared` would hold everywhere at zero and
        // the sweep would pass having verified nothing.
        assert!(
            textured > 100,
            "only {textured} of {reeled} effects painted anything — the export \
             probably predates the binding"
        );
    }
}
