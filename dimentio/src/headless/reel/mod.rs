//! `dimentio reel` — render one effect across its own timeline to a PNG and exit.
//!
//! The effect counterpart of `shot`. A shot is one instant from several angles;
//! a reel is one angle at several instants, because what there is to check about
//! an effect is *when* things happen. Both write one contact sheet through the
//! same software rasteriser, so a caller with no screen can look at either.
//!
//! ✅ **The artwork is real** (D258). A part's image is five sections past its
//! record, `bleck` resolves it into the export, and this binds it — `sweat`
//! reels as a blue droplet.
//!
//! ✅ **And so is the placement**, since D266. Each draw is posed by walking
//! its node chain and evaluating that node's curves at the frame - the game's
//! own scheme, transcribed from its evaluator - so a reel shows the parts
//! composed where the data puts them rather than on an invented ring.
//!
//! What it settles is that the data and the renderer agree — the parts the
//! manifest calls running are the parts that reach the frame, every part
//! declaring a picture gets one, and the frame changes as parts start and stop.
//!
//! # Shape
//!
//! `request` is the command line, `compose` renders the cells and counts what
//! landed, and `report` says what the numbers mean. Each reads only from the
//! ones before it; this file loads the export and joins the three up.

use std::process::ExitCode;

use crate::data::effects::{Entry, Library};
use crate::headless::encode::{wants_gif, write_gif, write_png, GIF_TICK_MS};

mod compose;
mod report;
mod request;

pub use report::Report;
pub use request::{parse, Request, USAGE};

/// How many near names an unknown effect is offered.
const SUGGESTIONS: usize = 6;

/// The rate the game counts effect frames at, so a frame number becomes a time.
const FRAME_RATE: f32 = 60.0;

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

    let sampled = sample(entry, request.frames, request.from, request.upto);
    let art = compose::resolve_art(entry, &request.export, library.textures());
    let built = compose::draw(
        entry,
        &sampled,
        &art,
        compose::Scene {
            meshes: library.meshes(),
            nodes: library.nodes(),
            curves: library.curves(),
        },
        request,
    );
    // ⚠️ The spacing between *sampled* frames, not one game frame — a reel of
    // 9 cells over 65 frames plays 8x faster than the game if each cell is
    // given one tick.
    let gap = if sampled.len() > 1 {
        ((sampled[1] - sampled[0]) * 1000.0).round().max(1.0) as u32
    } else {
        GIF_TICK_MS
    };
    let animated = wants_gif(&request.out);
    let tick = if animated {
        Some(write_gif(&request.out, &built.cells, gap)?)
    } else {
        write_png(&request.out, &built.sheet.pixels, built.sheet.size)?;
        None
    };
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
        stood_in: built.stood_in,
        depth_ratio: built.depth_ratio,
        tick,
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
fn sample(entry: &Entry, wanted: usize, from: Option<u32>, upto: Option<u32>) -> Vec<f32> {
    let last = entry.frames().max(1);
    // Frames are 1-based in the report, as the durations are, so frame 1 is
    // time zero.
    let first = from.unwrap_or(1).clamp(1, last);
    let final_ = upto.unwrap_or(last).clamp(first, last);
    let span = (final_ - first) as usize + 1;
    let count = wanted.clamp(1, span);
    let at = |frame: u32| (frame - 1) as f32 / FRAME_RATE;
    if count == 1 {
        return vec![at(first)];
    }
    (0..count)
        .map(|index| {
            let frame = first as f32 + (final_ - first) as f32 * index as f32 / (count - 1) as f32;
            (frame - 1.0) / FRAME_RATE
        })
        .collect()
}

#[cfg(test)]
mod tests;

/// The real export, when one happens to be on this machine.
///
/// ⚠️ `work/` is git-ignored, so these skip rather than fail on a fresh clone
/// or in CI. They exist because every fixture in `tests` is written by this
/// module's own code, and a hand-written manifest cannot catch what 139 real
/// effects do.
#[cfg(test)]
mod real_export_tests;
