//! A track drawn as a waveform: peak envelope, playhead, and the pixels both.
//!
//! ⚠️ The envelope is min *and* max per column, not an average of magnitudes.
//! Averaging flattens a track into a band of roughly constant height, so a
//! quiet passage and a loud one look the same and the picture stops being
//! evidence of anything. The peak pair keeps the shape a listener would expect.
//!
//! ⚠️ Drawn on the CPU into the same `Image` the model viewport uses, for the
//! same reason: a machine that cannot capture its own screen can still assert
//! on pixels.

use super::{Background, Image, Rgba, Size};

/// The backdrop a waveform is drawn on. Fixed rather than chosen: the picker
/// exists to show a model against light and dark, and a waveform is a diagram.
const BACKDROP: Background = Background::DarkGrey;

/// The envelope itself.
const WAVE: Rgba = Rgba::new(96, 190, 200);

/// The playhead. Warm against the cold envelope, so the two never read as the
/// same mark.
const PLAYHEAD: Rgba = Rgba::new(240, 196, 92);

/// One column of the envelope: the quietest and loudest sample under it.
///
/// Silence is `low == high == 0.0`, which draws as the single centre row —
/// a flat line, which is what silence should look like.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Column {
    pub low: f32,
    pub high: f32,
}

impl Column {
    /// How far the column spans, in sample units. Zero for silence.
    ///
    /// The renderer maps `low` and `high` to rows separately and never needs
    /// the difference; the tests measure it, because "louder" is exactly this
    /// number growing.
    #[cfg(test)]
    pub fn height(self) -> f32 {
        self.high - self.low
    }
}

/// A whole track reduced to one column per pixel of width.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Envelope {
    columns: Vec<Column>,
}

impl Envelope {
    /// Summarise interleaved samples into `columns` peak pairs.
    ///
    /// ⚠️ Channels are deliberately not separated. The peak across both is what
    /// the ear hears, and two stacked mono traces would double the height of
    /// the panel for a picture nobody reads separately.
    ///
    /// A track with no samples produces no columns rather than a row of
    /// zeroes: "silent" and "not there" are different, and the panel says so.
    pub fn of(samples: &[f32], columns: usize) -> Self {
        if samples.is_empty() || columns == 0 {
            return Self::default();
        }
        let mut built = Vec::with_capacity(columns);
        for column in 0..columns {
            let start = column * samples.len() / columns;
            // ⚠️ At least one sample per column. A track shorter than the panel
            // is wide gives some columns an empty range, and a fold over
            // nothing returns the identity — which draws as full-scale bars.
            let end = ((column + 1) * samples.len() / columns).max(start + 1);
            let span = &samples[start..end.min(samples.len())];
            let mut low = f32::INFINITY;
            let mut high = f32::NEG_INFINITY;
            for &sample in span {
                low = low.min(sample);
                high = high.max(sample);
            }
            built.push(Column {
                low: if low.is_finite() { low } else { 0.0 },
                high: if high.is_finite() { high } else { 0.0 },
            });
        }
        Self { columns: built }
    }

    /// The summarised columns. `draw` reads the field directly and resamples
    /// it; only the tests need to look at one column at a time.
    #[cfg(test)]
    pub fn columns(&self) -> &[Column] {
        &self.columns
    }

    pub fn is_empty(&self) -> bool {
        self.columns.is_empty()
    }

    /// The tallest column, which says whether a track has anything in it.
    pub fn peak(&self) -> f32 {
        self.columns
            .iter()
            .map(|column| column.high.abs().max(column.low.abs()))
            .fold(0.0, f32::max)
    }
}

/// The column the playhead sits in, `time` seconds into a track of `seconds`.
///
/// ⚠️ The time is clamped, not the column. That is what keeps the result inside
/// the frame by construction, and it is also what makes a wrong mapping — one
/// that forgets to divide by the duration, say — land far outside the width
/// instead of being silently pinned to the last column.
///
/// A track with no duration has no playhead: every position in it is the same
/// position.
pub fn playhead(time: f32, seconds: f32, width: usize) -> Option<usize> {
    if width == 0 || seconds <= 0.0 {
        return None;
    }
    let fraction = time.clamp(0.0, seconds) / seconds;
    Some((fraction * (width - 1) as f32).round() as usize)
}

/// Draw an envelope, with an optional playhead column.
///
/// Always returns a full frame: an empty envelope, a zero size, or a playhead
/// outside the frame produce the backdrop rather than a failure, because the
/// caller is a window that has to draw something.
pub fn draw(envelope: &Envelope, mark: Option<usize>, size: Size) -> Image {
    let mut image = Image::filled(size, BACKDROP);
    if size.pixels() == 0 {
        return image;
    }
    if !envelope.is_empty() {
        for x in 0..size.width {
            // The envelope is sampled across the frame rather than assumed to
            // be one column per pixel, so a cached envelope survives a resize.
            let column = envelope.columns[x * envelope.columns.len() / size.width];
            let top = row(column.high, size.height);
            let bottom = row(column.low, size.height);
            for y in top..=bottom {
                image.set(x, y, WAVE);
            }
        }
    }
    if let Some(x) = mark.filter(|&x| x < size.width) {
        for y in 0..size.height {
            image.set(x, y, PLAYHEAD);
        }
    }
    image
}

/// The row a sample amplitude falls on. +1 is the top row, -1 the bottom, and 0
/// the middle — so silence is a line through the centre rather than along an
/// edge.
fn row(amplitude: f32, height: usize) -> usize {
    if height == 0 {
        return 0;
    }
    let last = (height - 1) as f32;
    let fallen = (1.0 - amplitude.clamp(-1.0, 1.0)) * 0.5 * last;
    if fallen.is_finite() {
        (fallen.round() as usize).min(height - 1)
    } else {
        0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FRAME: Size = Size::new(101, 41);

    /// `n` samples of pure silence.
    fn silence(count: usize) -> Vec<f32> {
        vec![0.0; count]
    }

    /// A square wave at full scale, which is the loudest thing 16-bit PCM holds.
    fn loud(count: usize) -> Vec<f32> {
        (0..count)
            .map(|at| if at % 2 == 0 { 1.0 } else { -1.0 })
            .collect()
    }

    /// A square wave whose amplitude climbs from silence to full scale.
    fn swelling(count: usize) -> Vec<f32> {
        (0..count)
            .map(|at| {
                let level = at as f32 / count as f32;
                if at % 2 == 0 {
                    level
                } else {
                    -level
                }
            })
            .collect()
    }

    /// Pixels that are not the backdrop, per column.
    fn lit(image: &Image) -> Vec<Vec<usize>> {
        let size = image.size();
        (0..size.width)
            .map(|x| {
                (0..size.height)
                    .filter(|&y| image.pixel(x, y) != BACKDROP.pixel(x, y, size))
                    .collect()
            })
            .collect()
    }

    /// ⚠️ Silence must draw as a line through the middle, one pixel deep. A
    /// renderer that mapped 0 to an edge, or that filled from the top, passes
    /// every "something was drawn" check and shows a solid block.
    #[test]
    fn a_silent_track_draws_a_flat_line_through_the_centre() {
        let envelope = Envelope::of(&silence(8000), FRAME.width);
        assert_eq!(envelope.peak(), 0.0);

        let image = draw(&envelope, None, FRAME);
        let middle = FRAME.height / 2;
        for (x, rows) in lit(&image).iter().enumerate() {
            assert_eq!(rows.len(), 1, "column {x} is not one pixel deep: {rows:?}");
            assert_eq!(rows[0], middle, "column {x} is off centre");
        }
    }

    #[test]
    fn a_loud_track_is_not_a_flat_line() {
        let quiet = draw(&Envelope::of(&silence(8000), FRAME.width), None, FRAME);
        let noisy = draw(&Envelope::of(&loud(8000), FRAME.width), None, FRAME);
        assert_ne!(quiet.as_rgba(), noisy.as_rgba());

        for (x, rows) in lit(&noisy).iter().enumerate() {
            assert_eq!(
                rows.len(),
                FRAME.height,
                "column {x} of a full-scale track should reach both edges"
            );
        }
    }

    /// A track that gets louder must *look* like it gets louder. This is the
    /// test that a magnitude average would fail: averaging turns a swell into a
    /// band of nearly constant height.
    #[test]
    fn a_swelling_track_is_wider_on_the_right_than_the_left() {
        let envelope = Envelope::of(&swelling(8000), FRAME.width);
        let columns = envelope.columns();
        let first = columns[0].height();
        let last = columns[columns.len() - 1].height();
        assert!(last > first * 4.0, "first {first}, last {last}");
        assert!(first >= 0.0, "a height is never negative: {first}");

        let drawn = lit(&draw(&envelope, None, FRAME));
        assert!(
            drawn[FRAME.width - 1].len() > drawn[0].len(),
            "left {} px, right {} px",
            drawn[0].len(),
            drawn[FRAME.width - 1].len()
        );
    }

    /// ⛔ The mapping the whole scrubber rests on. Dropping the division by the
    /// duration passes at t = 0 and fails everywhere else, which is exactly
    /// what a UI-only check would have missed.
    #[test]
    fn the_playhead_maps_time_to_a_column() {
        let width = 101;
        assert_eq!(playhead(0.0, 4.0, width), Some(0), "the start");
        assert_eq!(playhead(2.0, 4.0, width), Some(50), "halfway");
        assert_eq!(playhead(4.0, 4.0, width), Some(100), "the last column");
        assert_eq!(playhead(1.0, 4.0, width), Some(25), "a quarter in");

        // A different duration must move the same time to a different column.
        assert_eq!(playhead(2.0, 8.0, width), Some(25));
        // And a different width must scale with it.
        assert_eq!(playhead(2.0, 4.0, 201), Some(100));
    }

    #[test]
    fn a_playhead_outside_the_track_is_pinned_or_absent() {
        assert_eq!(playhead(-5.0, 4.0, 101), Some(0), "before the start");
        assert_eq!(playhead(9.0, 4.0, 101), Some(100), "past the end");
        assert_eq!(playhead(1.0, 0.0, 101), None, "a track with no length");
        assert_eq!(playhead(1.0, 4.0, 0), None, "a frame with no width");
    }

    #[test]
    fn the_playhead_is_drawn_in_the_column_the_mapping_names() {
        let envelope = Envelope::of(&silence(8000), FRAME.width);
        let at = playhead(2.0, 4.0, FRAME.width).expect("halfway");
        let image = draw(&envelope, Some(at), FRAME);
        assert_eq!(
            lit(&image)[at].len(),
            FRAME.height,
            "the playhead column should be full height"
        );
        assert_eq!(image.pixel(at, 0), PLAYHEAD);
        assert_ne!(image.pixel(at - 1, 0), PLAYHEAD, "and only that column");
    }

    /// A frame with nothing to draw in it, and a frame with no pixels at all.
    #[test]
    fn a_zero_length_track_renders_the_backdrop_rather_than_panicking() {
        let empty = Envelope::of(&[], FRAME.width);
        assert!(empty.is_empty());
        assert_eq!(empty.peak(), 0.0);

        let image = draw(&empty, None, FRAME);
        assert!(lit(&image).iter().all(Vec::is_empty), "nothing was drawn");
        assert_eq!(image.as_rgba().len(), FRAME.pixels() * 4);

        // The playhead has nowhere to go, and asking for one anyway must not
        // reach outside the frame.
        let _ = draw(&empty, Some(9999), FRAME);
        assert!(draw(&empty, None, Size::new(0, 0)).as_rgba().is_empty());
        assert_eq!(draw(&empty, Some(0), Size::new(1, 1)).as_rgba().len(), 4);
    }

    /// ⚠️ A track shorter than the panel is wide leaves some columns with an
    /// empty sample range. Folding over nothing returns the identity, which is
    /// ±infinity — and that draws as a full-scale bar out of silence.
    #[test]
    fn a_track_shorter_than_the_frame_is_wide_still_summarises() {
        let envelope = Envelope::of(&silence(7), FRAME.width);
        assert_eq!(envelope.columns().len(), FRAME.width);
        for column in envelope.columns() {
            assert!(column.low.is_finite(), "{column:?}");
            assert!(column.high.is_finite(), "{column:?}");
        }
        assert_eq!(envelope.peak(), 0.0);
    }

    /// The envelope is computed once per track and drawn at whatever size the
    /// panel happens to be, so it must survive both directions.
    #[test]
    fn one_envelope_draws_at_any_frame_width() {
        let envelope = Envelope::of(&loud(8000), 64);
        for width in [1, 17, 64, 400] {
            let image = draw(&envelope, Some(0), Size::new(width, 32));
            assert_eq!(image.as_rgba().len(), width * 32 * 4);
        }
    }
}
