//! `dimentio shot` — render a model to a PNG file and exit.
//!
//! The window is not involved. `render` rasterises into a `Vec<u8>` with no
//! GPU, driver or display, so the same code that fills the viewport fills a
//! file, and a caller with no screen can look at what it built.
//!
//! The grid, the measurements and the file writing are `super::sheet` and
//! `super::encode`; what is here is the model half — which angles to render,
//! which keyframe to hold, and what the numbers mean for a model.

use std::f32::consts::TAU;
use std::path::PathBuf;
use std::process::ExitCode;

use super::args::{named_background, number, size_refusal, SIZE_LIMIT};
use super::encode::{wants_gif, write_gif, write_png, GIF_TICK_MS};
use super::sheet::{self, Sheet, FLAT_SPREAD, GUTTER};
use crate::data::mesh::Mesh;
use crate::render::{self, Background, Camera, Image, Size, View};

/// Cell edge when `--size` is not given. Large enough to read a face on,
/// small enough that four of them stay under a megapixel.
const DEFAULT_SIZE: usize = 512;

const DEFAULT_ANGLES: usize = 4;

/// Bound on the view count, for the same reason `SIZE_LIMIT` bounds the edge: a
/// mistyped `--angles` should be a message, not an allocation failure.
const ANGLE_LIMIT: std::ops::RangeInclusive<usize> = 1..=16;

/// How far above the horizon every view of the sheet looks from. Straight on
/// hides the top of a model completely, and a model's top is where an
/// exporter's mistakes collect.
const SHEET_PITCH: f32 = 0.35;

pub const USAGE: &str = "\
dimentio shot <model.glb> --out <file.png> [options]

  --out <file.png>   where to write. Required.
  --size <n>         edge of one view, in pixels. Default 512.
  --angles <n>       views around the model, into one contact sheet. Default 4.
  --clip <n>         morph clip to pose, by index. Default 0.
  --frame <n>        keyframe of that clip to hold. Default: the rest pose.
  --to <n>           sweep keyframes --frame..--to instead of angles. One cell
                     each, from one fixed view. Write to .gif to animate.
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
    /// Last keyframe of a sweep. ⚠️ When set, the cells are **keyframes rather
    /// than angles** and the view is held still — a model turning *and*
    /// animating at once shows neither clearly.
    pub upto: Option<usize>,
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
    /// Keyframes rendered, when `--to` asked for a sweep instead of angles.
    pub swept: Option<usize>,
    /// The GIF frame delay actually used, in milliseconds, when one was
    /// written. ⚠️ A GIF's unit is a centisecond, so the rate is coarse.
    pub tick: Option<u32>,
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
            // ⚠️ Says which it actually did. A sweep still fills a grid, and
            // reporting "4 angle(s)" over 8 keyframes described the wrong run.
            match (self.swept, self.tick) {
                (Some(keys), Some(tick)) => format!(
                    "{keys} keyframe(s) as a looping GIF at {tick}ms each ({:.1} fps)",
                    1000.0 / tick as f32
                ),
                (Some(keys), None) => format!(
                    "{keys} keyframe(s) into {}x{}",
                    self.sheet.width, self.sheet.height
                ),
                (None, Some(tick)) => format!("one frame as a GIF at {tick}ms"),
                (None, None) => format!(
                    "{} angle(s) into {}x{}",
                    self.angles, self.sheet.width, self.sheet.height
                ),
            },
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
    let mut upto = None;
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
            "--to" => upto = Some(number(arg, &value()?)?),
            "--background" => background = named_background(&value()?)?,
            flag if flag.starts_with("--") => return Err(format!("unknown option {flag}")),
            path if model.is_none() => model = Some(PathBuf::from(path)),
            extra => return Err(format!("unexpected argument {extra}")),
        }
    }

    let model = model.ok_or("no model given")?;
    let out = out.ok_or("--out is required; there is nowhere to write to")?;
    if !SIZE_LIMIT.contains(&size) {
        return Err(size_refusal(size));
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
        upto,
        clip,
        frame,
        background,
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
    let swept = match (request.frame, request.upto) {
        (Some(first), Some(last)) => sweep(&mut mesh, request, first, last)?,
        _ => Vec::new(),
    };
    let count = swept;
    let sheet = if count.is_empty() {
        draw(&mesh, request)
    } else {
        sheet::tile(&count, request.size, request.background)
    };
    let tick = if wants_gif(&request.out) {
        let cells = if count.is_empty() {
            vec![render::render(
                &mesh,
                &View {
                    camera: Camera::fit(mesh.visible_bounds()),
                    background: request.background,
                },
                Size::new(request.size, request.size),
            )]
        } else {
            count.clone()
        };
        // One keyframe per tick. ⚠️ Clip key times are not read here, so this
        // is an even cadence rather than the clip's own timing.
        Some(write_gif(&request.out, &cells, GIF_TICK_MS * 4)?)
    } else {
        write_png(&request.out, &sheet.pixels, sheet.size)?;
        None
    };

    Ok(Report {
        sheet: sheet.size,
        angles: request.angles,
        swept: (!count.is_empty()).then_some(count.len()),
        tick,
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

/// Render every angle and lay them out in a grid.
///
/// ⚠️ **Evenly spaced from the front, not four hand-picked poses.** Named
/// poses would stop meaning anything the moment `--angles` was not 4, and the
/// axis-aligned views are the ones worth having: a flat shape that disappears
/// edge-on is a fact about the model.
fn draw(mesh: &Mesh, request: &Request) -> Sheet {
    let cell = Size::new(request.size, request.size);
    let columns = sheet::grid_columns(request.angles);
    let rows = request.angles.div_ceil(columns);
    let mut sheet = Sheet::blank(request.size, columns, rows);
    let fitted = Camera::fit(mesh.visible_bounds());
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
            .add(sheet::measure(image.as_rgba(), cell, request.background));
        let column = index % columns;
        let row = index / columns;
        sheet::blit(
            &mut sheet,
            &image,
            column * (request.size + GUTTER),
            row * (request.size + GUTTER),
        );
    }
    sheet
}

/// One image per keyframe from `first` to `last`, from one fixed view.
///
/// ⚠️ **The camera is fitted once, to the pose already held**, and then left
/// alone. Refitting per keyframe would rescale the model as it moved, which
/// reads as the animation zooming rather than the camera chasing it.
fn sweep(
    mesh: &mut Mesh,
    request: &Request,
    first: usize,
    last: usize,
) -> Result<Vec<Image>, String> {
    if last < first {
        return Err(format!("--to {last} is before --frame {first}"));
    }
    let cell = Size::new(request.size, request.size);
    let view = View {
        camera: Camera::fit(mesh.visible_bounds()),
        background: request.background,
    };
    let mut cells = Vec::with_capacity(last - first + 1);
    for frame in first..=last {
        hold(mesh, request.clip, frame)?;
        cells.push(render::render(mesh, &view, cell));
    }
    Ok(cells)
}

#[cfg(test)]
mod tests;
