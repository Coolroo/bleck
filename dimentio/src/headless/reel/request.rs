//! What `dimentio reel` was asked for, and reading it off the command line.
//!
//! Nothing here loads or draws anything: a `Request` is the whole of the
//! command line, checked, so a line that cannot work is refused before an
//! export is opened.

use std::path::PathBuf;

use crate::headless::args::{named_background, number, size_refusal, SIZE_LIMIT};
use crate::render::Background;

/// Cell edge when `--size` is not given. Smaller than a model shot's, because a
/// reel holds more cells and a part is a flat quad with no detail to lose.
pub(super) const DEFAULT_SIZE: usize = 320;

pub(super) const DEFAULT_FRAMES: usize = 9;

/// Bound on the cell count, for the same reason `shot` bounds its angles: a
/// mistyped `--frames` should be a message, not an allocation failure.
const FRAME_LIMIT: std::ops::RangeInclusive<usize> = 1..=64;

/// Where `bleck effect export --out` writes by default.
pub(super) const DEFAULT_EXPORT: &str = "work/export";

pub const USAGE: &str = "\
dimentio reel --effect <name> --out <file.png> [options]

  --effect <name>    which effect, as `bleck effect list` names it. Required.
  --out <file.png>   where to write. Required.
  --export <dir>     folder holding effects.json. Default work/export.
  --frames <n>       frames sampled across the range. Default 9.
  --from <n>         first game frame to sample, 1-based. Default 1.
  --to <n>           last game frame to sample. Default the effect's last.
  --size <n>         edge of one frame, in pixels. Default 320.
  --background <s>   dark-grey | checkerboard | gradient. Default checkerboard.

Write to a .gif and the frames become a looping animation instead of a sheet.

Frames run left to right, top to bottom. The effect is drawn from one fixed
camera so the cells can be compared against each other.

An effect that draws nothing at frame 1 is usually not broken: scales rise from
zero, so 44% of draws are flat there. Try --from 10.";

/// What a run was asked for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    pub effect: String,
    pub export: PathBuf,
    pub out: PathBuf,
    pub size: usize,
    pub frames: usize,
    pub background: Background,
    /// The game frames to sample between, inclusive. `None` is the whole
    /// timeline, which is what every existing caller gets.
    ///
    /// ⚠️ **Frame 0 is often the least informative one** (D266): 44% of draws
    /// are flat there and 26 effects draw nothing at all, so "the first frames"
    /// is frequently the wrong window to look at. `item_fire` needs frame 10.
    pub from: Option<u32>,
    pub upto: Option<u32>,
}

/// Read the command line. Long flags only, matching `shot`.
pub fn parse(args: &[String]) -> Result<Request, String> {
    let mut effect = None;
    let mut out = None;
    let mut export = PathBuf::from(DEFAULT_EXPORT);
    let mut size = DEFAULT_SIZE;
    let mut frames = DEFAULT_FRAMES;
    let mut background = Background::Checkerboard;
    let mut from = None;
    let mut upto = None;

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
            "--from" => from = Some(number(arg, &value()?)? as u32),
            "--to" => upto = Some(number(arg, &value()?)? as u32),
            "--background" => background = named_background(&value()?)?,
            flag if flag.starts_with("--") => return Err(format!("unknown option {flag}")),
            extra => return Err(format!("unexpected argument {extra}")),
        }
    }

    let effect = effect.ok_or("--effect is required; `bleck effect list` names them")?;
    let out = out.ok_or("--out is required; there is nowhere to write to")?;
    if !SIZE_LIMIT.contains(&size) {
        return Err(size_refusal(size));
    }
    if !FRAME_LIMIT.contains(&frames) {
        return Err(format!(
            "--frames {frames} is outside {}..={}",
            FRAME_LIMIT.start(),
            FRAME_LIMIT.end()
        ));
    }
    Ok(Request {
        from,
        upto,
        effect,
        export,
        out,
        size,
        frames,
        background,
    })
}
