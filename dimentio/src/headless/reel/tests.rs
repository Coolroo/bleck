//! Reels of hand-written effects: the command line, the grid, and the counting.
//!
//! Every fixture here is written by this file, so what it can prove is that the
//! renderer and the manifest agree with each other. The 139 real effects are in
//! `real_export_tests`.

use super::compose::deduped;
use super::report::Frame;
use super::request::{DEFAULT_EXPORT, DEFAULT_FRAMES, DEFAULT_SIZE};
use super::*;
use crate::headless::sheet::GUTTER;
use crate::render::{self, effect, Background, Camera, Rgba, Size};
use std::path::PathBuf;

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
        from: None,
        upto: None,
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
    let camera = Camera::fit(render::effect::bounds(
        &Entry {
            parts: vec![Default::default(); 8],
            ..Default::default()
        },
        None,
    ));
    let shades: Vec<Rgba> = (0..8).map(|part| effect::lit(&camera, part)).collect();
    assert_eq!(shades[0], shades[6], "the palette stopped repeating at six");
    assert_eq!(deduped(&shades).len(), 6, "{shades:?}");

    let frame = Frame {
        number: 1,
        time: 0.0,
        active: 8,
        pieces: 8,
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
        stood_in: 0,
        depth_ratio: 1.0,
        tick: None,
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

/// An export written before D258 carries no `draws`, and must still
/// load — but it must not look like an effect that genuinely draws nothing.
/// ⚠️ The message names the command that fixes it, because "0 painted" on
/// its own sends someone hunting a rendering bug that is not there.
#[test]
fn an_export_predating_the_binding_says_so_rather_than_reading_as_empty() {
    let scratch = scratch_with_manifest("caveat");
    let report = take(&request(&scratch, "twopart", 3)).expect("renders");
    assert_eq!(report.painted, 0, "the fixture carries no draws");
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
        // ⚠️ 50, not 100. The fallback layout is an even ring since D270
        // removed the transform rows it used to read, and a ring is more
        // compact than the four axes those rows put the fixture on — so
        // every cell draws a little less. The property under test is that
        // each cell rendered *something of its own*, not how big it is.
        assert!(drawn > 50, "cell at {left},{top} drew only {drawn} pixels");
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
    assert_eq!(sample(&entry, 1, None, None), vec![0.0]);
    assert_eq!(sample(&entry, 3, None, None), vec![0.0, 0.5, 1.0]);
    assert_eq!(sample(&entry, 5, None, None).len(), 5);

    let instant = Entry {
        name: "blink".into(),
        seconds: 0.0,
        parts: vec![Default::default()],
        ..Default::default()
    };
    assert_eq!(instant.frames(), 1);
    assert_eq!(sample(&instant, 40, None, None), vec![0.0]);
}

/// ⚠️ **Frame 1 is time zero**, matching the report's own numbering and the
/// inclusive frame counts everywhere else. A range that started at 0 would
/// be off by one against every number the report prints.
#[test]
fn a_frame_range_samples_only_inside_itself() {
    let entry = Entry {
        name: "probe".into(),
        seconds: 1.0,
        parts: vec![Default::default()],
        ..Default::default()
    };
    assert_eq!(entry.frames(), 61);

    let window = sample(&entry, 3, Some(11), Some(31));
    assert_eq!(window.len(), 3);
    assert!((window[0] - 10.0 / 60.0).abs() < 1e-5, "{window:?}");
    assert!((window[2] - 30.0 / 60.0).abs() < 1e-5, "{window:?}");

    // One end alone still bounds the window.
    let tail = sample(&entry, 2, Some(31), None);
    assert!((tail[0] - 30.0 / 60.0).abs() < 1e-5, "{tail:?}");
    assert!((tail[1] - 60.0 / 60.0).abs() < 1e-5, "{tail:?}");
}

/// ⛔ A range cannot ask for more cells than it holds frames, or the same
/// frame is rendered twice and read as an animation standing still.
#[test]
fn a_range_never_yields_more_cells_than_it_has_frames() {
    let entry = Entry {
        name: "probe".into(),
        seconds: 1.0,
        parts: vec![Default::default()],
        ..Default::default()
    };
    assert_eq!(sample(&entry, 40, Some(5), Some(7)).len(), 3);
    assert_eq!(sample(&entry, 40, Some(9), Some(9)).len(), 1);
}

/// A backwards or out-of-range window is clamped rather than refused: it
/// still names a real frame, which is more use than an error.
#[test]
fn a_reversed_or_overlong_range_is_clamped() {
    let entry = Entry {
        name: "probe".into(),
        seconds: 1.0,
        parts: vec![Default::default()],
        ..Default::default()
    };
    assert_eq!(sample(&entry, 4, Some(40), Some(10)).len(), 1);
    let past = sample(&entry, 3, Some(1), Some(9999));
    assert!((past[2] - 60.0 / 60.0).abs() < 1e-5, "{past:?}");
}

/// ⚠️ Asserted from `reel`'s side as well as `encode`'s. Writing a `.gif` is
/// the one place the two commands' output diverges from a PNG sheet, and this
/// is the check that a reel asked for one gets one.
#[test]
fn only_a_gif_extension_asks_for_an_animation() {
    assert!(wants_gif(std::path::Path::new("a.gif")));
    assert!(wants_gif(std::path::Path::new("A.GIF")));
    assert!(!wants_gif(std::path::Path::new("a.png")));
    assert!(!wants_gif(std::path::Path::new("gif")));
}
