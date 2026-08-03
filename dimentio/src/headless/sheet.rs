//! The contact sheet: a grid of rendered cells, and what those pixels measure.
//!
//! ⚠️ **Several views into one image, not one file each.** Most defects are
//! visible from one direction, or at one instant, only — a stray shape off to
//! the side, a surface that vanishes when its back is turned, a part that has
//! already stopped. Four files means four looks, and the one nobody opens is the
//! one that showed it.
//!
//! ⚠️ **The backdrop is never white.** A texture that decodes to near-white and
//! a texture that failed to decode look the same against a white page, and
//! telling those apart is most of what this is for.
//!
//! This module knows nothing about models or effects. It is handed cells that
//! are already rendered, lays them out, and reports what it measured.

use crate::render::{Background, Image, Rgba, Size};

/// Pixels between cells of the contact sheet, in a colour neither background
/// uses, so where one view ends and the next begins is never in doubt.
///
/// ⚠️ Shared by `shot` and `reel`, which lay their cells out in the same grid.
/// Two constants would let the two sheets drift apart, and a reader comparing a
/// model sheet against an effect sheet would be measuring the difference.
pub(super) const GUTTER: usize = 2;
pub(super) const DIVIDER: Rgba = Rgba::new(120, 124, 132);

/// Under this a frame's colours are one surface tint at different
/// brightnesses. See `Coverage::spread`.
///
/// ⛔ **The calibration that chose this number no longer holds.** D253
/// measured 60 models — the 30 with no image spread at most 0.007, the 30 with
/// one at least 0.023 — and picked the midpoint. Then D251 taught the renderer
/// to draw `COLOR_0`, and the untextured half moved: `e_big_nok` names no
/// image and now spreads **1.426**, above `e_lui_robo`'s 0.758 with fifteen.
///
/// The threshold survives because the question it answers changed with it.
/// It no longer means "an image reached this" — `shot::Report` reads the image
/// count from the file for that — only "these pixels are not one flat tint",
/// which is still worth saying and is still true either side of 0.015.
pub(super) const FLAT_SPREAD: f32 = 0.015;

/// A contact sheet under construction, and what has been drawn into it.
pub(super) struct Sheet {
    pub(super) size: Size,
    pub(super) pixels: Vec<u8>,
    pub(super) coverage: Coverage,
}

impl Sheet {
    /// An empty sheet of `columns` x `rows` cells, each `cell` pixels square.
    pub(super) fn blank(cell: usize, columns: usize, rows: usize) -> Self {
        let span = |count: usize| count * cell + count.saturating_sub(1) * GUTTER;
        let size = Size::new(span(columns), span(rows));
        Self {
            size,
            pixels: divided(size),
            coverage: Coverage::default(),
        }
    }
}

/// How much of a frame the model reached, and how varied its colours were.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub(super) struct Coverage {
    pub(super) drawn: usize,
    pub(super) total: usize,
    /// Spread of the drawn pixels' colour away from their own average, with
    /// brightness divided out.
    ///
    /// ⚠️ **Brightness is divided out on purpose.** Shading already varies a
    /// flat surface from ambient to full, so a plain spread of RGB values
    /// cannot tell a lit grey model from a painted one. Dividing each pixel by
    /// its own luminance leaves only the tint, which a flat-shaded model holds
    /// constant and a textured one does not.
    pub(super) spread: f32,
    /// Mean brightness step between side-by-side pixels of the model, over 255.
    ///
    /// ⛔ **Reported, never judged.** It was meant to catch what `spread`
    /// cannot — an image that decoded to near-white — and two measurements on
    /// the real export took it out of the verdict (D253). Small facets read as
    /// texels: the untextured `e_bari_bari` steps 0.099. Magnification reads as
    /// smooth: `OFF_doorL`, a sharp kanji across a quarter of the frame, steps
    /// 0.006, which is what a bare cube steps. It is a second view of the same
    /// pixels, and nothing may be concluded from it alone.
    pub(super) detail: f32,
}

impl Coverage {
    pub(super) fn share(self) -> f32 {
        if self.total == 0 {
            return 0.0;
        }
        self.drawn as f32 / self.total as f32
    }

    pub(super) fn add(&mut self, other: Self) {
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
pub(super) fn measure(pixels: &[u8], size: Size, background: Background) -> Coverage {
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

/// As square a grid as the count allows, widest side first.
pub(super) fn grid_columns(cells: usize) -> usize {
    let mut columns = 1;
    while columns * columns < cells {
        columns += 1;
    }
    columns.max(1)
}

fn divided(size: Size) -> Vec<u8> {
    [DIVIDER.r, DIVIDER.g, DIVIDER.b, 255].repeat(size.pixels())
}

pub(super) fn blit(sheet: &mut Sheet, image: &Image, left: usize, top: usize) {
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

/// Lay already-rendered cells into a fresh sheet, measuring each as it lands.
pub(super) fn tile(cells: &[Image], edge: usize, background: Background) -> Sheet {
    let columns = grid_columns(cells.len());
    let rows = cells.len().div_ceil(columns);
    let mut sheet = Sheet::blank(edge, columns, rows);
    let cell = Size::new(edge, edge);
    for (index, image) in cells.iter().enumerate() {
        sheet
            .coverage
            .add(measure(image.as_rgba(), cell, background));
        blit(
            &mut sheet,
            image,
            (index % columns) * (edge + GUTTER),
            (index / columns) * (edge + GUTTER),
        );
    }
    sheet
}

#[cfg(test)]
mod tests {
    use super::*;

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

    /// ⚠️ Half of a control pair. A `measure` that returned zero for everything
    /// would pass `shot`'s bare-cube test and call every model in the export
    /// untextured — which is the failure the tool is meant to detect, arriving
    /// in the detector itself.
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
    fn the_grid_stays_as_square_as_the_count_allows() {
        assert_eq!(grid_columns(1), 1);
        assert_eq!(grid_columns(2), 2);
        assert_eq!(grid_columns(4), 2);
        assert_eq!(grid_columns(6), 3);
        assert_eq!(grid_columns(9), 3);
        assert_eq!(grid_columns(16), 4);
    }
}
