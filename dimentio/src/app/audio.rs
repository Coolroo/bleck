//! The only part of this program that touches an audio device.
//!
//! ⛔ **Every `rodio` type stays inside this file.** The rest of the window
//! deals in seconds and a `Transport`; swapping the backend, or building
//! without one, must not reach `app::sounds`.
//!
//! ⚠️ **The device is opened on the first play, not when the folder is.** A
//! window opened to look at textures should not seize the sound card, and the
//! headless layout tests must never touch one — a CI runner has no default
//! output and opening one there is an error, not a test failure.
//!
//! ⚠️ **Nothing here is the authority on where playback is.** `Transport` is.
//! This reports the mixer's own position so the scrubber can follow the sound
//! rather than a frame clock that drifts from it, and reports `None` whenever
//! there is nothing queued.

use std::num::NonZero;

use crate::data::wav::Audio;

/// The device, and the one voice queued on it.
///
/// Dropping this stops playback: `rodio::Player`'s own `Drop` marks its queue
/// stopped, and dropping the device sink tears down the stream. Both happen
/// when `Engine` is dropped, which is what closing the window does.
struct Device {
    /// ⚠️ Held only to keep the stream alive, and never read again. Dropping it
    /// silences the player even though the player is still in scope.
    _sink: rodio::MixerDeviceSink,
    player: rodio::Player,
}

/// What is queued, and where in the track it started.
///
/// ⚠️ The offset exists because the samples handed to the mixer are the tail of
/// the track, not all of it. `Player::get_pos` counts from the first sample it
/// was given, so without this a seek to 10 s would report a position of 0.
struct Queued {
    offset: f32,
}

/// Playback, or an explanation of why there is none.
#[derive(Default)]
pub(super) struct Engine {
    device: Option<Device>,
    queued: Option<Queued>,
    /// Why the device could not be opened, so the panel can say so once rather
    /// than retrying on every frame.
    problem: Option<String>,
}

impl Engine {
    /// Play `audio` from `seconds` in, at `volume`.
    ///
    /// Replaces whatever was playing. Reports whether sound actually started:
    /// a machine with no output device is not an error the user caused, and
    /// the panel says so instead of looking broken.
    pub(super) fn start(&mut self, audio: &Audio, seconds: f32, volume: f32) -> bool {
        let Some(channels) = NonZero::new(audio.channels()) else {
            self.problem = Some("the track declares no channels".into());
            return false;
        };
        let Some(rate) = NonZero::new(audio.rate()) else {
            self.problem = Some("the track declares no sample rate".into());
            return false;
        };
        let samples = audio.from(seconds);
        if samples.is_empty() {
            self.stop();
            return false;
        }
        if !self.open() {
            return false;
        }
        let Some(device) = &self.device else {
            return false;
        };
        device.player.stop();
        device.player.set_volume(volume);
        device
            .player
            .append(rodio::buffer::SamplesBuffer::new(channels, rate, samples));
        device.player.play();
        self.queued = Some(Queued { offset: seconds });
        true
    }

    /// Hold the sound where it is, keeping it queued so `resume` can continue.
    pub(super) fn pause(&self) {
        if let Some(device) = &self.device {
            device.player.pause();
        }
    }

    pub(super) fn resume(&self) {
        if let Some(device) = &self.device {
            device.player.play();
        }
    }

    /// Silence, and discard what was queued.
    ///
    /// ⚠️ Called on a new selection as well as on the stop button. A window
    /// that changed tracks without this would mix the old one under the new.
    pub(super) fn stop(&mut self) {
        if let Some(device) = &self.device {
            device.player.stop();
        }
        self.queued = None;
    }

    pub(super) fn set_volume(&self, volume: f32) {
        if let Some(device) = &self.device {
            device.player.set_volume(volume);
        }
    }

    /// Where the mixer has got to, in track seconds. `None` when nothing is
    /// queued or no device was opened, which is when the caller falls back to
    /// its own clock.
    pub(super) fn position(&self) -> Option<f32> {
        let device = self.device.as_ref()?;
        let queued = self.queued.as_ref()?;
        Some(queued.offset + device.player.get_pos().as_secs_f32())
    }

    /// Whether the queued track has run out. False when nothing is queued, so
    /// "never started" is not mistaken for "finished".
    pub(super) fn finished(&self) -> bool {
        match (&self.device, &self.queued) {
            (Some(device), Some(_)) => device.player.empty(),
            _ => false,
        }
    }

    /// Whether a device is open, so the panel can say that sound is available
    /// before the first play rather than after it.
    pub(super) fn live(&self) -> bool {
        self.device.is_some()
    }

    /// Whether this engine still holds a track the mixer could resume.
    ///
    /// ⚠️ This is what makes pause-then-play continue rather than restart. A
    /// caller that queued the samples again on every play would rewind to the
    /// transport's position, which is nearly right and audibly wrong.
    pub(super) fn queued(&self) -> bool {
        self.queued.is_some() && self.device.is_some()
    }

    pub(super) fn problem(&self) -> Option<&str> {
        self.problem.as_deref()
    }

    /// Open the default output, once. A failure is remembered rather than
    /// retried: a machine with no sound card would otherwise pay for the
    /// attempt on every click.
    fn open(&mut self) -> bool {
        if self.device.is_some() {
            return true;
        }
        if self.problem.is_some() {
            return false;
        }
        match rodio::DeviceSinkBuilder::open_default_sink() {
            Ok(mut sink) => {
                // Otherwise rodio prints a line to stderr when the window
                // closes, which reads as a crash on the way out.
                sink.log_on_drop(false);
                let player = rodio::Player::connect_new(sink.mixer());
                self.device = Some(Device {
                    _sink: sink,
                    player,
                });
                true
            }
            Err(why) => {
                self.problem = Some(format!("no audio output: {why}"));
                false
            }
        }
    }
}

impl Drop for Engine {
    /// ⚠️ Explicit, rather than left to field order. A sound left running after
    /// its window has gone is the failure this whole module has to avoid, and
    /// stopping the player before the stream is torn down is what guarantees
    /// the mixer stops asking for samples first.
    fn drop(&mut self) {
        self.stop();
    }
}
