//! Where a scrubber is and whether it is moving — the one idiom every
//! playable thing in this program uses.
//!
//! Kept apart from the windows that draw it so the wrap can be tested with no
//! display: this machine cannot capture its own desktop, so playback that only
//! ran inside a frame callback would have no evidence behind it at all.
//!
//! ⚠️ **`sounds::Transport` is deliberately not this.** A track stops at its
//! end, holds a paused position distinct from a stopped one, and carries a
//! volume; an effect and a model animation loop and have no device to feed.
//! Folding the two together would give a viewport a stop button that means
//! something only to the mixer.

/// Where the scrubber is and whether it is moving.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct Playback {
    pub time: f32,
    pub playing: bool,
}

impl Playback {
    /// Advance `dt` seconds, wrapping at `span` so the clip loops.
    ///
    /// Something of zero length holds at 0: it is a single frame, and there is
    /// nothing to scrub through.
    pub fn advance(&mut self, dt: f32, span: f32) {
        if !self.playing {
            return;
        }
        if span <= 0.0 {
            self.time = 0.0;
            return;
        }
        self.time = (self.time + dt.max(0.0)) % span;
    }

    /// Back to the start, keeping whether it was playing — used when the
    /// selection changes, since a new clip has a different length and the old
    /// position may be past its end.
    pub fn rewind(&mut self) {
        self.time = 0.0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn playback_wraps_at_the_duration() {
        let mut play = Playback {
            time: 0.9,
            playing: true,
        };
        play.advance(0.05, 1.0);
        assert!((play.time - 0.95).abs() < 1e-6, "{}", play.time);
        play.advance(0.1, 1.0);
        assert!(play.time < 0.06, "wrapped to {}", play.time);
        play.advance(9.5, 1.0);
        assert!(
            play.time < 1.0,
            "a long step still lands inside {}",
            play.time
        );
    }

    #[test]
    fn playback_holds_still_while_paused() {
        let mut play = Playback {
            time: 0.4,
            playing: false,
        };
        play.advance(1.0, 2.0);
        assert_eq!(play.time, 0.4);
    }

    /// A single-frame effect, or a clip with one pose, has nothing to scrub —
    /// and dividing by its length would be a division by zero.
    #[test]
    fn a_zero_length_span_stays_at_the_start() {
        let mut play = Playback {
            time: 0.4,
            playing: true,
        };
        play.advance(0.1, 0.0);
        assert_eq!(play.time, 0.0);
        play.rewind();
        assert_eq!(play.time, 0.0);
    }

    /// ⚠️ The default is **paused at the start**, which is what a newly
    /// selected model must be: a viewport that began animating on selection
    /// would never show the pose the geometry was authored in.
    #[test]
    fn the_default_is_paused_at_the_start() {
        let play = Playback::default();
        assert_eq!(play.time, 0.0);
        assert!(!play.playing);
    }
}
