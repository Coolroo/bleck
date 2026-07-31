//! The track list, the transport, and the waveform under it. **This is the UI
//! layer** — the manifest it draws is read by `crate::data::sounds`, the
//! samples by `crate::data::wav`, the picture by `crate::render::wave`, and the
//! sound itself comes out of `super::audio`.
//!
//! ⚠️ **`Transport` decides what the window shows; the mixer only follows.**
//! The panel is driven by the transport's own state so that play, pause, stop
//! and seek can be tested on a machine with no audio device — which is every
//! machine this has been built on.

use std::path::Path;

use eframe::egui;

use super::{audio, Viewer};
use crate::data::{self, sounds, wav};
use crate::render;

/// Columns the envelope is summarised into, once per track.
///
/// ⚠️ Independent of the panel's width on purpose: `render::wave::draw`
/// resamples it, so resizing the window redraws rather than re-reading 3.5 M
/// samples. Wider than any plausible panel, so the picture never gains detail
/// it does not have.
const ENVELOPE_COLUMNS: usize = 4096;

/// Height of the waveform panel, in points.
const WAVE_HEIGHT: f32 = 170.0;

/// Carries the standing warning that a file is not the whole track. The same
/// amber the model pane uses for a fragment: both say "this is less than it
/// looks like".
const CAPPED: egui::Color32 = egui::Color32::from_rgb(220, 170, 90);

/// The selected track's samples, and the picture summarised from them.
pub(super) struct Loaded {
    pub(super) audio: wav::Audio,
    pub(super) envelope: render::wave::Envelope,
}

/// Everything the sound mode owns.
#[derive(Default)]
pub(super) struct SoundPane {
    pub(super) library: data::SoundLibrary,
    pub(super) search: String,
    pub(super) selected: Option<usize>,
    pub(super) transport: sounds::Transport,
    /// The selection's decoded samples. `None` until something is picked, and
    /// `None` again when the file behind a selection could not be read.
    pub(super) loaded: Option<Loaded>,
    /// Why the selection has no samples, as opposed to the library having no
    /// tracks. A refused WAV says which encoding it was.
    pub(super) note: Option<String>,
    /// A scrub handle is held down this frame.
    ///
    /// ⚠️ While it is, the clock must not write `time`. The mixer is still
    /// playing from where the drag started, so a clock that kept following it
    /// would drag the handle back out of the user's hand on every frame.
    pub(super) scrubbing: bool,
    /// The last drawn waveform, uploaded once and replaced in place. A new
    /// handle per frame would leak a GPU texture per frame, and the playhead
    /// moves on every frame while a track plays.
    pub(super) frame: Option<egui::TextureHandle>,
    pub(super) audio: audio::Engine,
}

impl SoundPane {
    pub(super) fn load(root: &Path) -> Self {
        Self {
            library: data::SoundLibrary::load(root),
            ..Default::default()
        }
    }

    /// How long the thing that is actually playing is.
    ///
    /// The decoded file wins over the manifest: the manifest records what the
    /// exporter meant to write, and the scrubber has to match the samples.
    fn span(&self, entry: Option<&sounds::Entry>) -> f32 {
        match &self.loaded {
            Some(loaded) => loaded.audio.seconds(),
            None => entry.map_or(0.0, |entry| entry.seconds),
        }
    }
}

impl Viewer {
    pub(super) fn sound_controls(&mut self, ui: &mut egui::Ui) {
        let shown = self.sounds.library.matching(&self.sounds.search).len();
        ui.label(format!("{shown} of {} track(s)", self.sounds.library.len()));
        ui.separator();
        ui.label("volume");
        let slider = ui.add(
            egui::Slider::new(&mut self.sounds.transport.volume, 0.0..=sounds::MAX_VOLUME)
                .show_value(false)
                .fixed_decimals(2),
        );
        if slider.changed() {
            self.sounds.audio.set_volume(self.sounds.transport.volume);
        }
        ui.label(
            egui::RichText::new(format!("{:.0}%", self.sounds.transport.volume * 100.0))
                .monospace(),
        );
        ui.separator();
        // ⚠️ Said before the first click, not after it. A machine with no output
        // device otherwise looks like a window that ignores the play button.
        match self.sounds.audio.problem() {
            Some(why) => {
                ui.label(egui::RichText::new(why).color(CAPPED).small());
            }
            None => {
                ui.label(
                    egui::RichText::new(if self.sounds.audio.live() {
                        "audio device open"
                    } else {
                        "the audio device opens on the first play"
                    })
                    .weak()
                    .small(),
                );
            }
        }
    }

    fn selected_sound(&self) -> Option<&sounds::Entry> {
        self.sounds
            .selected
            .and_then(|index| self.sounds.library.entries().get(index))
    }

    /// Follow the sound, and keep frames coming while it moves.
    ///
    /// ⚠️ `request_repaint` is what makes the playhead move at all. egui redraws
    /// in response to input and nothing else, so without it the waveform would
    /// step once per mouse movement while the music played on underneath.
    ///
    /// ⚠️ The mixer's position wins when there is one. A frame clock and an
    /// audio clock drift, and a playhead that ends up seconds away from what is
    /// audible is worse than no playhead.
    pub(super) fn run_sound_clock(&mut self, ctx: &egui::Context) {
        if !self.sounds.transport.playing() {
            return;
        }
        if self.sounds.scrubbing {
            // The handle is under the pointer and owns `time` until it is let
            // go. Frames still have to keep coming, or the drag would stall.
            ctx.request_repaint();
            return;
        }
        let span = self.sounds.span(self.selected_sound());
        if self.sounds.audio.finished() {
            self.stop_sound();
            return;
        }
        match self.sounds.audio.position() {
            Some(at) if at >= span => self.stop_sound(),
            Some(at) => self.sounds.transport.time = at,
            None => {
                let dt = ctx.input(|input| input.stable_dt);
                self.sounds.transport.advance(dt, span);
            }
        }
        ctx.request_repaint();
    }

    /// The tracks to choose from, searchable. Rows are virtualised for the same
    /// reason the model list's are: a widget per row costs a widget per row
    /// whether or not that row is on screen.
    pub(super) fn sound_list(&mut self, ctx: &egui::Context) {
        egui::SidePanel::left("sounds")
            .default_width(280.0)
            .show(ctx, |ui| {
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    ui.label("Search");
                    ui.add(
                        egui::TextEdit::singleline(&mut self.sounds.search)
                            .desired_width(130.0)
                            .hint_text("name or disc file"),
                    );
                    if ui.button("clear").clicked() {
                        self.sounds.search.clear();
                    }
                });

                let visible = self.sounds.library.matching(&self.sounds.search);
                ui.label(
                    egui::RichText::new(format!(
                        "{} of {} track(s)",
                        visible.len(),
                        self.sounds.library.len()
                    ))
                    .weak(),
                );
                ui.separator();

                // The central panel says what went wrong, in the space to say
                // it in.
                if self.sounds.library.problem().is_some() {
                    return;
                }

                let selected = self.sounds.selected;
                let entries = self.sounds.library.entries();
                let step = ui.text_style_height(&egui::TextStyle::Body) + 6.0;
                let mut picked = None;
                egui::ScrollArea::vertical().show_rows(ui, step, visible.len(), |ui, range| {
                    for row in range {
                        let Some(&index) = visible.get(row) else {
                            break;
                        };
                        let Some(entry) = entries.get(index) else {
                            break;
                        };
                        let label = format!("{}  ·  {:.1}s", entry.name, entry.seconds);
                        let row = ui.selectable_label(selected == Some(index), label);
                        if row.on_hover_text(entry.describe()).clicked() {
                            picked = Some(index);
                        }
                    }
                });
                if let Some(index) = picked {
                    self.select_sound(index);
                }
            });
    }

    /// Pick a track: silence whatever was playing, then decode the new one.
    ///
    /// ⚠️ The old track is stopped *first*. Loading the new one takes long
    /// enough to hear, and a window that changed selection without this would
    /// mix the two.
    pub(super) fn select_sound(&mut self, index: usize) {
        self.stop_sound();
        self.sounds.selected = Some(index);
        self.sounds.loaded = None;
        self.sounds.note = None;
        let Some(path) = self
            .sounds
            .library
            .entries()
            .get(index)
            .map(|entry| entry.path.clone())
        else {
            return;
        };
        match wav::Audio::load(&path) {
            Ok(audio) => {
                let envelope = render::wave::Envelope::of(audio.samples(), ENVELOPE_COLUMNS);
                self.sounds.loaded = Some(Loaded { audio, envelope });
            }
            Err(why) => self.sounds.note = Some(why),
        }
    }

    /// Start, or resume a pause. Queues the samples only when the mixer is not
    /// already holding this track, so pause and play do not restart it.
    pub(super) fn play_sound(&mut self) {
        self.sounds.transport.play();
        let pane = &mut self.sounds;
        if pane.audio.queued() {
            pane.audio.resume();
            return;
        }
        if let Some(loaded) = &pane.loaded {
            pane.audio
                .start(&loaded.audio, pane.transport.time, pane.transport.volume);
        }
    }

    pub(super) fn pause_sound(&mut self) {
        self.sounds.transport.pause();
        self.sounds.audio.pause();
    }

    pub(super) fn stop_sound(&mut self) {
        self.sounds.transport.stop();
        self.sounds.audio.stop();
    }

    /// Move to a point in the track, and take the sound with it.
    ///
    /// ⚠️ Requeues from the new offset rather than seeking the queued source:
    /// the mixer is handed the tail of the track from wherever playback starts,
    /// so a seek is a new tail.
    pub(super) fn seek_sound(&mut self, time: f32) {
        let span = self.sounds.span(self.selected_sound());
        self.sounds.transport.seek(time, span);
        let pane = &mut self.sounds;
        if !pane.transport.playing() {
            pane.audio.stop();
            return;
        }
        if let Some(loaded) = &pane.loaded {
            pane.audio
                .start(&loaded.audio, pane.transport.time, pane.transport.volume);
        }
    }

    pub(super) fn sound_detail(&mut self, ui: &mut egui::Ui) {
        let Some(index) = self.sounds.selected else {
            Self::message(ui, "Pick a track on the left.");
            return;
        };
        let Some(entry) = self.sounds.library.entries().get(index).cloned() else {
            Self::message(ui, "That track is no longer in the manifest.");
            return;
        };

        ui.add_space(4.0);
        ui.heading(&entry.name);
        ui.add_space(4.0);
        Self::sound_facts(ui, &entry, self.sounds.loaded.as_ref());
        if let Some(note) = self.sounds.note.clone() {
            ui.label(egui::RichText::new(note).color(CAPPED));
        }
        ui.separator();

        // ⚠️ The scrub controls only move `Transport`; the mixer is told where
        // to go once, on the frame the pointer comes up. Requeueing per frame
        // would stop and restart the sound as fast as frames are drawn, and
        // each restart blocks this thread until the mixer's queue drains.
        let was_held = self.sounds.scrubbing;
        let mut held = self.transport_row(ui, &entry);
        ui.separator();
        held |= self.waveform(ui, &entry);
        self.sounds.scrubbing = held;
        if was_held && !held {
            self.seek_sound(self.sounds.transport.time);
        }
    }

    /// What `bleck` recorded about the track, and what the file turned out to
    /// hold. Both, because a manifest that disagrees with its own WAV is the
    /// one thing a viewer can catch that an exporter cannot.
    fn sound_facts(ui: &mut egui::Ui, entry: &sounds::Entry, loaded: Option<&Loaded>) {
        ui.horizontal_wrapped(|ui| {
            Self::inline_fact(ui, "rate", &format!("{} Hz", entry.rate));
            ui.separator();
            Self::inline_fact(
                ui,
                "channels",
                &format!(
                    "{} ({})",
                    entry.channels,
                    sounds::channel_name(entry.channels)
                ),
            );
            ui.separator();
            Self::inline_fact(ui, "duration", &format!("{:.3}s", entry.seconds));
            ui.separator();
            match entry.loop_seconds() {
                Some(at) => Self::inline_fact(ui, "loops", &format!("from {at:.3}s")),
                None => Self::inline_fact(ui, "loops", "no"),
            }
            ui.separator();
            Self::inline_fact(ui, "source", &entry.source);
        });
        if let Some(loaded) = loaded {
            ui.horizontal_wrapped(|ui| {
                Self::inline_fact(ui, "decoded", &format!("{:.3}s", loaded.audio.seconds()));
                ui.separator();
                Self::inline_fact(ui, "frames", &loaded.audio.frames().to_string());
                ui.separator();
                Self::inline_fact(ui, "peak", &format!("{:.3}", loaded.envelope.peak()));
            });
        }
        if entry.capped {
            ui.label(
                egui::RichText::new(
                    "capped — the export stopped early, so this file is shorter than \
                     the game's track and the duration above is the file's",
                )
                .color(CAPPED)
                .small(),
            );
        }
    }

    /// Play, pause, stop and scrub.
    ///
    /// ⚠️ A track with no length gets no scrubber: its range would be empty,
    /// and there is nothing to move through.
    ///
    /// Reports whether the scrubber is being held, which is what tells
    /// `sound_detail` the position belongs to the pointer and not to the clock.
    fn transport_row(&mut self, ui: &mut egui::Ui, entry: &sounds::Entry) -> bool {
        let span = self.sounds.span(Some(entry));
        let playing = self.sounds.transport.playing();
        let mut action = None;
        let mut sought = None;
        let mut held = false;
        ui.horizontal(|ui| {
            if span <= 0.0 {
                ui.label(egui::RichText::new("no samples — nothing to play").weak());
                return;
            }
            let symbol = if playing { "⏸" } else { "▶" };
            if ui.button(symbol).on_hover_text("play / pause").clicked() {
                action = Some(if playing { Action::Pause } else { Action::Play });
            }
            if ui.button("⏹").on_hover_text("stop, and rewind").clicked() {
                action = Some(Action::Stop);
            }
            let mut time = self.sounds.transport.time;
            let slider = ui.add(
                egui::Slider::new(&mut time, 0.0..=span)
                    .suffix(" s")
                    .fixed_decimals(2),
            );
            // ⚠️ Gated on the pointer being down, not on `changed()` alone.
            // A slider with `fixed_decimals` rewrites the value it is given to
            // that many places, so a running clock makes it report a change on
            // every frame — which read as a scrub nobody performed, and
            // requeued the mixer sixty times a second.
            held = slider.is_pointer_button_down_on();
            if held && slider.changed() {
                sought = Some(time);
            }
            ui.label(egui::RichText::new(format!("of {span:.2}s")).monospace());
        });
        if span <= 0.0 {
            self.stop_sound();
            return false;
        }
        if let Some(time) = sought {
            self.sounds.transport.seek(time, span);
        }
        match action {
            Some(Action::Play) => self.play_sound(),
            Some(Action::Pause) => self.pause_sound(),
            Some(Action::Stop) => self.stop_sound(),
            None => {}
        }
        held
    }

    /// The whole track as one picture, with the playhead on it. Clicking or
    /// dragging in it seeks — the inverse of the mapping that put the playhead
    /// where it is.
    ///
    /// ⚠️ Redrawn every frame with no stale flag while a track plays, because
    /// the playhead is what moves. It is a column of arithmetic per pixel of
    /// width, not a scene.
    fn waveform(&mut self, ui: &mut egui::Ui, entry: &sounds::Entry) -> bool {
        let span = self.sounds.span(Some(entry));
        let area = egui::vec2(ui.available_width(), WAVE_HEIGHT.min(ui.available_height()));
        if area.x < 1.0 || area.y < 1.0 {
            return false;
        }
        let (rect, response) = ui.allocate_exact_size(area, egui::Sense::click_and_drag());
        let size = Self::frame_size(area);

        let empty = render::wave::Envelope::default();
        let envelope = self
            .sounds
            .loaded
            .as_ref()
            .map_or(&empty, |loaded| &loaded.envelope);
        let mark = render::wave::playhead(self.sounds.transport.time, span, size.width);
        let drawn = render::wave::draw(envelope, mark, size);
        // Read before the frame handle is borrowed mutably below; the envelope
        // itself borrows the pane and cannot outlive that.
        let silent = envelope.is_empty();
        Self::upload(ui, &mut self.sounds.frame, "waveform", &drawn);
        if let Some(handle) = &self.sounds.frame {
            ui.painter().image(
                handle.id(),
                rect,
                egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                egui::Color32::WHITE,
            );
        }

        // Pressing anywhere in the picture moves the playhead there; the sound
        // follows when the pointer comes up, which `sound_detail` does.
        let held = response.is_pointer_button_down_on();
        if held {
            if let Some(at) = response.interact_pointer_pos() {
                let across = ((at.x - rect.left()) / rect.width().max(1.0)).clamp(0.0, 1.0);
                self.sounds.transport.seek(across * span, span);
            }
        }
        response.on_hover_text(if silent {
            "no samples to draw".to_string()
        } else {
            format!("{:.2}s of {}", span, sounds::channel_name(entry.channels))
        });
        held
    }
}

/// What a click on the transport asked for. Collected inside the row's closure
/// and applied after it, because the buttons borrow `ui` and the handlers
/// borrow the pane.
enum Action {
    Play,
    Pause,
    Stop,
}
