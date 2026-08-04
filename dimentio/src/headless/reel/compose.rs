//! Turning one effect into a grid of rendered cells, and counting what landed.
//!
//! Given an effect, the times to sample and the tables a pose is built from,
//! this renders each cell, blits it into the sheet, and measures what reached
//! the pixels. The verdicts drawn from those numbers are `super::report`'s; the
//! sampling is `super`'s.

use crate::data::catalog::Catalog;
use crate::data::effects::{
    frame_at, image_at, Curve, Entry, MaterialDef, Mesh as Geometry, NodeDef, SamplerDef,
};
use crate::data::texture::Texture;
use crate::headless::sheet::{self, Sheet, GUTTER};
use crate::render::{self, effect, Background, Camera, Image, Piece, Rgba, Size, View};

use super::report::Frame;
use super::request::Request;

/// The sheet and everything measured while filling it.
pub(super) struct Built {
    pub(super) sheet: Sheet,
    /// Each frame on its own, kept so the same run can be written as an
    /// animation instead of a sheet.
    pub(super) cells: Vec<Image>,
    pub(super) frames: Vec<Frame>,
    pub(super) changes: usize,
    pub(super) painted: usize,
    pub(super) stood_in: usize,
    pub(super) depth_ratio: f32,
}

/// The shared tables a pose is built from, passed together because they are
/// only meaningful together.
#[derive(Clone, Copy)]
pub(super) struct Scene<'a> {
    pub(super) meshes: &'a [Geometry],
    pub(super) nodes: &'a [NodeDef],
    pub(super) curves: &'a [Curve],
    /// The colour registers and texture records the same curves drive (D281).
    pub(super) materials: &'a [MaterialDef],
    pub(super) samplers: &'a [SamplerDef],
}

/// Decode the image each **draw** of each part paints with, from the texture
/// catalog beside the effect manifest.
///
/// ⚠️ An image that cannot be read leaves its draw unpainted rather than
/// failing the run. The report counts what actually arrived, so a missing PNG
/// shows up as a lower `painted` rather than as a crash or a silent flat piece
/// indistinguishable from a part that genuinely draws nothing.
pub(super) fn resolve_art(
    entry: &Entry,
    root: &std::path::Path,
    source: &str,
) -> Vec<Vec<Option<Texture>>> {
    let catalog = Catalog::load(root);
    entry
        .parts
        .iter()
        .map(|part| {
            part.draws
                .iter()
                .map(|draw| {
                    let at = image_at(catalog.entries(), source, draw.image()?)?;
                    let found = catalog.entries().get(at)?;
                    Texture::decode(&std::fs::read(&found.path).ok()?).ok()
                })
                .collect()
        })
        .collect()
}

pub(super) fn draw(
    entry: &Entry,
    times: &[f32],
    art: &[Vec<Option<Texture>>],
    scene: Scene<'_>,
    request: &Request,
) -> Built {
    let palette = effect::Art {
        images: art,
        meshes: scene.meshes,
        nodes: scene.nodes,
        curves: scene.curves,
        materials: scene.materials,
        samplers: scene.samplers,
    };
    let cell = Size::new(request.size, request.size);
    let columns = sheet::grid_columns(times.len());
    let rows = times.len().div_ceil(columns);
    let mut sheet = Sheet::blank(request.size, columns, rows);
    // One camera for the whole reel. Refitting per frame would rescale the view
    // as parts stop, so a part ending would look like the rest moving.
    let span = effect::bounds(entry, Some(palette));
    let flat = (span.max.x - span.min.x).max(span.max.y - span.min.y);
    let depth_ratio = (span.max.z - span.min.z) / flat.max(f32::EPSILON);
    let camera = Camera::fit(span);
    let view = View {
        camera,
        background: request.background,
    };

    let mut frames = Vec::with_capacity(times.len());
    let mut cells = Vec::with_capacity(times.len());
    let mut changes = 0;
    let mut painted = vec![false; entry.parts.len()];
    let mut stood_in = 0;
    let mut previous: Option<Image> = None;

    for (index, &time) in times.iter().enumerate() {
        let drawn = effect::quads(entry, time, &camera, Some(palette));
        let quads = &drawn.pieces;
        for quad in quads {
            if let Some(seen) = painted.get_mut(quad.part) {
                *seen |= !quad.mesh.paints().is_empty();
            }
        }
        // ⚠️ Counted on the first frame only. A later frame runs fewer parts,
        // so summing across the reel would scale the number by how long each
        // part happened to last.
        if index == 0 {
            stood_in = quads.iter().filter(|quad| quad.stood_in).count();
        }
        let pieces: Vec<Piece<'_>> = quads
            .iter()
            .map(|quad| Piece {
                mesh: &quad.mesh,
                flat: quad.colour,
            })
            .collect();
        let image = render::scene(&pieces, &view, cell);

        let coverage = sheet::measure(image.as_rgba(), cell, request.background);
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
            active: entry.active_at(time).len(),
            pieces: quads.len(),
            painted: quads.len() - plain.len(),
            faded: drawn.faded,
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
        sheet::blit(
            &mut sheet,
            &image,
            (index % columns) * (request.size + GUTTER),
            (index / columns) * (request.size + GUTTER),
        );
        cells.push(image.clone());
        previous = Some(image);
    }

    Built {
        sheet,
        cells,
        frames,
        changes,
        painted: painted.iter().filter(|seen| **seen).count(),
        stood_in,
        depth_ratio,
    }
}

/// `colours` with repeats removed, in first-seen order.
///
/// ⚠️ Kept as its own function so a test can show the counting above can
/// return *less* than it was given. Measured against a render alone, a
/// `visible` that simply echoed `active` would agree with every frame and look
/// like a confirmation.
pub(super) fn deduped(colours: &[Rgba]) -> Vec<Rgba> {
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
