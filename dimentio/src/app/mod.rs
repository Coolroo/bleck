//! The window: what is on screen, and the state the four modes share.
//!
//! One export folder feeds every mode, so it is opened once here and each mode
//! reads its own manifest out of it. A mode's panels live beside the state they
//! draw — `textures`, `models`, `effects`, `sounds` — and every panel is a
//! method on `Viewer`, because egui draws from state mutated in place rather
//! than from a returned tree.
//!
//! ⛔ `audio` is the only module that touches a sound device, and every
//! `rodio` type stays inside it.

use eframe::egui;

use crate::data;
use crate::render;

mod audio;
mod effects;
mod models;
mod sounds;
mod textures;

use effects::EffectPane;
use models::ModelPane;
use sounds::SoundPane;

/// Space around each thumbnail, so the grid arithmetic matches the layout.
/// Shared by the texture grid and the effect image strip.
const PAD: f32 = 8.0;

/// Radians of orbit per point of drag.
const ORBIT_SPEED: f32 = 0.008;

/// How hard a scroll notch pulls the camera in. Applied as an exponent, so
/// zoom is proportional and cannot walk through zero.
const ZOOM_SPEED: f32 = 0.0015;

/// ⚠️ Longest edge a viewport is rasterised at, whatever size its panel is.
/// Every pixel costs CPU here, and a maximised 4K window would otherwise
/// rasterise ~8M of them on each frame of a drag. Beyond this the frame is
/// drawn smaller and scaled up by the GPU. Shared by both viewports.
const MAX_EDGE: f32 = 1600.0;

/// Which part of the program is on screen. One export folder feeds them all.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
enum Mode {
    #[default]
    Textures,
    Models,
    Effects,
    Sounds,
}

pub(crate) struct Viewer {
    root: Option<std::path::PathBuf>,
    catalog: data::Catalog,
    search: String,
    /// None means "every format".
    format: Option<String>,
    selected: Option<usize>,
    mode: Mode,
    models: ModelPane,
    effects: EffectPane,
    sounds: SoundPane,
}

impl Viewer {
    pub(crate) fn from_args() -> Self {
        let mut viewer = Self::empty();
        if let Some(path) = std::env::args().nth(1) {
            viewer.open(std::path::PathBuf::from(path));
        }
        viewer
    }

    /// A window with no folder behind it, which is what the welcome screen is.
    fn empty() -> Self {
        Self {
            root: None,
            catalog: data::Catalog::default(),
            search: String::new(),
            format: None,
            selected: None,
            mode: Mode::default(),
            models: ModelPane::default(),
            effects: EffectPane::default(),
            sounds: SoundPane::default(),
        }
    }

    /// ⚠️ Replacing `sounds` drops the old pane, and dropping its `Engine`
    /// stops whatever it was playing. Opening a second folder while a track
    /// runs must not leave the first one audible.
    fn open(&mut self, root: std::path::PathBuf) {
        self.catalog = data::Catalog::load(&root);
        self.models = ModelPane::load(&root);
        // The bank is read out of the texture catalog, so the effect pane is
        // built after that catalog is loaded and never before.
        self.effects = EffectPane::load(&root, &self.catalog);
        self.sounds = SoundPane::load(&root);
        self.root = Some(root);
        self.selected = None;
    }
}

impl eframe::App for Viewer {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.top_bar(ctx);
        match self.mode {
            Mode::Textures => {
                if self.selected.is_some() {
                    self.detail_panel(ctx);
                }
                egui::CentralPanel::default().show(ctx, |ui| {
                    if let Some(problem) = self.catalog.problem() {
                        Self::message(ui, &problem.describe());
                        return;
                    }
                    if self.root.is_none() {
                        Self::message(ui, WELCOME);
                        return;
                    }
                    self.grid(ui);
                });
            }
            Mode::Models => {
                self.model_list(ctx);
                self.model_facts(ctx);
                egui::CentralPanel::default().show(ctx, |ui| {
                    if self.root.is_none() {
                        Self::message(ui, WELCOME);
                        return;
                    }
                    self.viewport(ui);
                });
            }
            Mode::Effects => {
                self.run_clock(ctx);
                self.effect_list(ctx);
                self.effect_bank(ctx);
                egui::CentralPanel::default().show(ctx, |ui| {
                    if let Some(problem) = self.effects.library.problem() {
                        Self::message(ui, &problem.describe());
                        return;
                    }
                    if self.root.is_none() {
                        Self::message(ui, WELCOME);
                        return;
                    }
                    self.effect_detail(ui);
                });
            }
            Mode::Sounds => {
                self.run_sound_clock(ctx);
                self.sound_list(ctx);
                egui::CentralPanel::default().show(ctx, |ui| {
                    if let Some(problem) = self.sounds.library.problem() {
                        Self::message(ui, &problem.describe());
                        return;
                    }
                    if self.root.is_none() {
                        Self::message(ui, WELCOME);
                        return;
                    }
                    self.sound_detail(ui);
                });
            }
        }
    }
}

const WELCOME: &str = "\
No export folder given.

Dimentio renders what bleck exports, and reads no game formats itself.

    uv run bleck texture export --out work/export
    uv run bleck model   export --out work/export
    uv run bleck effect  export --out work/export
    uv run bleck sound   export --out work/export
    cargo run -- ../work/export";

impl Viewer {
    fn message(ui: &mut egui::Ui, text: &str) {
        ui.add_space(48.0);
        ui.vertical_centered(|ui| {
            ui.label(egui::RichText::new(text).monospace());
        });
    }

    /// The mode picker, and whichever mode's controls belong beside it.
    ///
    /// ⚠️ Leaving the sound mode stops playback. A track that kept playing
    /// under the texture grid would have no visible transport to stop it with,
    /// which is the failure this whole tab has to avoid.
    fn top_bar(&mut self, ctx: &egui::Context) {
        let leaving = self.mode;
        egui::TopBottomPanel::top("bar").show(ctx, |ui| {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.selectable_value(&mut self.mode, Mode::Textures, "Textures");
                ui.selectable_value(&mut self.mode, Mode::Models, "Models");
                ui.selectable_value(&mut self.mode, Mode::Effects, "Effects");
                ui.selectable_value(&mut self.mode, Mode::Sounds, "Sounds");
                ui.separator();
                match self.mode {
                    Mode::Textures => self.texture_controls(ui),
                    Mode::Models => self.model_controls(ui),
                    Mode::Effects => self.effect_controls(ui),
                    Mode::Sounds => self.sound_controls(ui),
                }
            });
            ui.add_space(4.0);
        });
        self.switched_from(leaving);
    }

    /// React to the tab the user just left.
    ///
    /// ⚠️ Separate from `top_bar` so it can be tested: a click on a tab cannot
    /// be delivered to a headless context, and "playback stops when the tab
    /// closes" is the one behaviour here nobody can check by looking.
    fn switched_from(&mut self, leaving: Mode) {
        if leaving == Mode::Sounds && self.mode != Mode::Sounds {
            self.stop_sound();
        }
    }

    fn fact(ui: &mut egui::Ui, key: &str, value: &str) {
        Self::inline_fact(ui, key, value);
        ui.end_row();
    }

    /// The same pair without `end_row`, which in a horizontal layout would
    /// wrap the strip onto a second line instead of ending a grid row.
    fn inline_fact(ui: &mut egui::Ui, key: &str, value: &str) {
        ui.label(egui::RichText::new(key).weak());
        ui.label(egui::RichText::new(value).monospace());
    }

    /// Drag orbits, scroll zooms. Reports whether the camera moved, which is
    /// what tells a cached frame it is out of date.
    ///
    /// The camera does its own clamping, so no input here can put it somewhere
    /// it cannot come back from.
    fn steer_camera(ui: &egui::Ui, response: &egui::Response, camera: &mut render::Camera) -> bool {
        let mut moved = false;
        let drag = response.drag_delta();
        if drag != egui::Vec2::ZERO {
            camera.orbit(drag.x * ORBIT_SPEED, drag.y * ORBIT_SPEED);
            moved = true;
        }
        if response.hovered() {
            let scroll = ui.input(|input| input.smooth_scroll_delta.y);
            if scroll != 0.0 {
                camera.zoom((-scroll * ZOOM_SPEED).exp());
                moved = true;
            }
        }
        moved
    }

    /// Rasterise `pixels` into `handle`, replacing what is there.
    ///
    /// ⚠️ The handle is reused rather than replaced. A new one per frame leaks
    /// a GPU texture per frame, which a viewport that redraws while a timeline
    /// runs would do sixty times a second.
    fn upload(
        ui: &egui::Ui,
        handle: &mut Option<egui::TextureHandle>,
        name: &str,
        drawn: &render::Image,
    ) {
        let size = drawn.size();
        let image =
            egui::ColorImage::from_rgba_unmultiplied([size.width, size.height], drawn.as_rgba());
        match handle {
            Some(existing) => existing.set(image, egui::TextureOptions::LINEAR),
            None => {
                *handle = Some(
                    ui.ctx()
                        .load_texture(name, image, egui::TextureOptions::LINEAR),
                );
            }
        }
    }

    /// The size to rasterise a viewport at: the panel's own aspect ratio, with
    /// only the resolution capped.
    fn frame_size(area: egui::Vec2) -> render::Size {
        let scale = (MAX_EDGE / area.x.max(area.y).max(1.0)).min(1.0);
        render::Size::new(
            ((area.x * scale) as usize).max(1),
            ((area.y * scale) as usize).max(1),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::sounds::Motion;

    const EFFECTS: &str = r#"{"schema": 1, "textures": "files/eff/effdata.tpl",
      "effects": [
        {"name": "chaos", "index": 16, "seconds": 3.0,
         "parts": [{"name": "A", "composed": "chaosA", "index": 61,
                    "frames": 181, "seconds": 3.0}],
         "rows": [{"index": 498, "values": [0.30902, 0.95106, 0.0, 0.0]}]},
        {"name": "system", "index": 120, "seconds": 0.0,
         "parts": [{"name": "IndTexture0", "composed": "systemIndTexture0",
                    "index": 700, "frames": 1, "seconds": 0.0}],
         "rows": []}
      ]}"#;

    const TEXTURES: &str = r#"{"schema": 1, "textures": [
      {"name": "files/eff/effdata.tpl#0", "file": "a.png", "format": "CMPR",
       "width": 8, "height": 32, "source": "files/eff/effdata.tpl"},
      {"name": "files/map/aa1_01.tpl#0", "file": "b.png", "format": "CMPR",
       "width": 64, "height": 64, "source": "files/map/aa1_01.tpl"}
    ]}"#;

    /// Four rows covering the shapes the panel has to survive: a track that
    /// plays, a shorter one, a file this program refuses, and one with no
    /// samples at all.
    const SOUNDS: &str = r#"{"schema": 1, "sounds": [
      {"name": "loud", "file": "loud.wav", "source": "files/sound/loud.brstm",
       "rate": 8000, "channels": 2, "seconds": 1.0,
       "loops": true, "loop_start": 4000, "capped": true},
      {"name": "quiet", "file": "quiet.wav", "source": "files/sound/quiet.brstm",
       "rate": 8000, "channels": 1, "seconds": 0.5,
       "loops": false, "loop_start": 0, "capped": false},
      {"name": "floaty", "file": "floaty.wav", "source": "files/sound/floaty.brstm",
       "rate": 8000, "channels": 2, "seconds": 1.0,
       "loops": false, "loop_start": 0, "capped": false},
      {"name": "empty", "file": "empty.wav", "source": "files/sound/empty.brstm",
       "rate": 8000, "channels": 2, "seconds": 0.0,
       "loops": false, "loop_start": 0, "capped": false}
    ]}"#;

    /// ⚠️ The PNGs and WAVs are written for real. `choose_image` decodes the
    /// file the catalog names and `select_sound` decodes the file the sound
    /// manifest names, so a folder of manifests with nothing behind them would
    /// exercise only the failure paths.
    /// ⚠️ Tagged per test. One folder shared between them races: a test that
    /// deletes an image to reach the failure path would delete it under a test
    /// running beside it.
    fn export_folder(tag: &str) -> std::path::PathBuf {
        let root = std::env::temp_dir().join(format!("dimentio-ui-{tag}-{}", std::process::id()));
        std::fs::create_dir_all(&root).expect("scratch dir");
        std::fs::write(root.join("effects.json"), EFFECTS).expect("effects.json");
        std::fs::write(root.join("textures.json"), TEXTURES).expect("textures.json");
        std::fs::write(root.join("sounds.json"), SOUNDS).expect("sounds.json");
        let texel = crate::data::texture::Texel {
            r: 0,
            g: 220,
            b: 220,
            a: 255,
        };
        for name in ["a.png", "b.png"] {
            std::fs::write(root.join(name), crate::data::texture::png(1, 1, &[texel]))
                .expect("a real png");
        }

        use crate::data::wav;
        let full: Vec<i16> = (0..16_000)
            .map(|at| if at % 2 == 0 { i16::MAX } else { i16::MIN })
            .collect();
        std::fs::write(root.join("loud.wav"), wav::wav(8000, 2, &full)).expect("a real wav");
        std::fs::write(root.join("quiet.wav"), wav::wav(8000, 1, &vec![0i16; 4000]))
            .expect("a real wav");
        // ⚠️ IEEE float, which this program refuses rather than plays.
        std::fs::write(
            root.join("floaty.wav"),
            wav::write_wav(8000, 2, &full, 3, 32),
        )
        .expect("a real wav");
        std::fs::write(root.join("empty.wav"), wav::wav(8000, 2, &[])).expect("a real wav");
        root
    }

    /// A quarter of a simulated second between drawn frames.
    ///
    /// ⚠️ The clock is fed in rather than measured. `run_sound_clock` asks for
    /// an immediate repaint, which makes egui report the *real* time between
    /// frames — microseconds in a test loop — so a transport driven by it would
    /// never reach the end of a track however many frames were drawn.
    const STEP: f64 = 0.25;

    /// One egui frame with every sound panel in it, at simulated time `at`, and
    /// no window anywhere.
    ///
    /// ⛔ Nothing here opens an audio device, and nothing may. `play_sound` is
    /// what reaches the mixer, and the transport is set directly instead — a
    /// test suite that seized the sound card would be unrunnable on CI and
    /// audible on a desk.
    fn draw_sounds(viewer: &mut Viewer, ctx: &egui::Context, at: f64) {
        let input = egui::RawInput {
            time: Some(at),
            ..Default::default()
        };
        let _ = ctx.run(input, |ctx| {
            viewer.top_bar(ctx);
            viewer.run_sound_clock(ctx);
            viewer.sound_list(ctx);
            egui::CentralPanel::default().show(ctx, |ui| viewer.sound_detail(ui));
        });
    }

    /// The sound clock on its own, at simulated time `at` — no panels, so
    /// nothing overwrites the state the caller set up.
    fn run_clock(viewer: &mut Viewer, ctx: &egui::Context, at: f64) {
        let input = egui::RawInput {
            time: Some(at),
            ..Default::default()
        };
        let _ = ctx.run(input, |ctx| viewer.run_sound_clock(ctx));
    }

    fn sound_viewer(tag: &str) -> Viewer {
        let mut viewer = Viewer {
            mode: Mode::Sounds,
            ..Viewer::empty()
        };
        viewer.open(export_folder(tag));
        viewer
    }

    /// ⚠️ "The window opens" is not evidence anybody can check, and a track
    /// playing is evidence nobody here can hear. Laying the panels out
    /// headlessly is what is left: a slider over an empty range, a waveform
    /// over a track with no samples, or a panel that borrows itself surfaces
    /// here instead of on a screen nobody can photograph.
    #[test]
    fn the_sound_panels_lay_out_and_run_without_a_window() {
        let mut viewer = sound_viewer("sounds");
        assert_eq!(viewer.sounds.library.len(), 4);
        let ctx = egui::Context::default();
        let mut clock = 0.0;

        // Nothing selected is the state the tab opens in.
        draw_sounds(&mut viewer, &ctx, clock);

        viewer.select_sound(0);
        let loaded = viewer.sounds.loaded.as_ref().expect("loud.wav decoded");
        assert_eq!(loaded.audio.channels(), 2);
        assert!(
            !loaded.envelope.is_empty(),
            "a full-scale track has a shape"
        );
        assert!(viewer.sounds.note.is_none());

        // ⚠️ The transport is set here rather than clicked, so no device is
        // opened. The clock, the playhead and the waveform are what is on test.
        viewer.sounds.transport.play();
        clock += STEP;
        draw_sounds(&mut viewer, &ctx, clock);
        assert!(viewer.sounds.frame.is_some(), "no waveform was drawn");
        assert!(
            viewer.sounds.transport.time > 0.0,
            "a drawn frame advances the transport, got {}",
            viewer.sounds.transport.time
        );
        assert!(viewer.sounds.transport.time < 1.0, "and stays in the track");

        // ⚠️ The track ends. A transport that wrapped instead would still be
        // playing here, and a window left alone would loop for ever.
        for _ in 0..8 {
            clock += STEP;
            draw_sounds(&mut viewer, &ctx, clock);
        }
        assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);
        assert_eq!(viewer.sounds.transport.time, 0.0);
    }

    /// The three files that are not a playable track, drawn through the real
    /// panels. Each one is a division by zero or an empty slider range waiting
    /// to happen.
    #[test]
    fn a_refused_or_empty_track_is_named_rather_than_panicking() {
        let mut viewer = sound_viewer("sounds-odd");
        let ctx = egui::Context::default();

        viewer.select_sound(2);
        let why = viewer.sounds.note.as_ref().expect("floaty.wav is refused");
        assert!(why.contains("PCM"), "{why}");
        assert!(viewer.sounds.loaded.is_none(), "nothing was decoded");
        // ⛔ Pressing play on a file that would not decode must not reach the
        // mixer, which is also what keeps this test off the sound card.
        viewer.play_sound();
        assert!(!viewer.sounds.audio.live(), "no device was opened");
        draw_sounds(&mut viewer, &ctx, STEP);

        // A track with no samples: the scrubber would be a slider over an
        // empty range, and the playhead a division by its length.
        viewer.select_sound(3);
        assert!(viewer.sounds.loaded.is_some(), "an empty wav still decodes");
        viewer.sounds.transport.play();
        draw_sounds(&mut viewer, &ctx, STEP * 2.0);
        assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);
        assert_eq!(viewer.sounds.transport.time, 0.0);

        // And an export with no sound manifest at all.
        let mut bare = Viewer {
            mode: Mode::Sounds,
            ..Viewer::empty()
        };
        bare.open(std::env::temp_dir().join("dimentio-ui-absent"));
        assert!(bare.sounds.library.problem().is_some());
        draw_sounds(&mut bare, &ctx, STEP);
    }

    /// The whole tab against the folder `bleck sound export` actually wrote,
    /// when there is one.
    ///
    /// ⚠️ The fixtures above are two-second files this crate writes itself. A
    /// 20-second 44.1 kHz stereo track is 3.5 M samples, and the envelope, the
    /// list of 135 rows and the panel layout have never met one anywhere else.
    #[test]
    fn the_real_export_opens_and_draws_a_real_track() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("a parent directory")
            .join("work")
            .join("export");
        if !root.join("sounds.json").is_file() {
            eprintln!("no work/export on this machine; skipped");
            return;
        }
        let mut viewer = Viewer {
            mode: Mode::Sounds,
            ..Viewer::empty()
        };
        viewer.open(root);
        assert!(viewer.sounds.library.len() > 100, "the real manifest");

        let ctx = egui::Context::default();
        viewer.select_sound(0);
        let loaded = viewer.sounds.loaded.as_ref().expect("a real track decodes");
        assert!(loaded.audio.seconds() > 1.0, "a real track has length");
        assert!(!loaded.envelope.is_empty());
        viewer.sounds.transport.play();
        draw_sounds(&mut viewer, &ctx, STEP);
        assert!(viewer.sounds.frame.is_some(), "no waveform was drawn");
        assert!(
            viewer.sounds.transport.playing(),
            "a real track outlasts one frame"
        );
        assert!(!viewer.sounds.audio.live(), "no device was opened");
    }

    /// ⚠️ A held scrub handle owns the position. The clock runs on every drawn
    /// frame, so without this the handle is dragged back out of the user's
    /// hand — which looks like a slider that will not move, and is invisible to
    /// any check that only draws single frames.
    #[test]
    fn a_held_scrubber_keeps_its_position_while_frames_go_by() {
        let mut viewer = sound_viewer("sounds-scrub");
        let ctx = egui::Context::default();
        viewer.select_sound(0);
        viewer.sounds.transport.play();
        viewer.sounds.transport.seek(0.6, 1.0);

        // ⛔ The clock alone, not a whole frame: the flag is derived from the
        // widgets on every frame, so a drawn frame with no pointer in it would
        // clear the flag before the clock could be seen ignoring it.
        let mut clock = 0.0;
        for _ in 0..4 {
            clock += STEP;
            viewer.sounds.scrubbing = true;
            run_clock(&mut viewer, &ctx, clock);
            assert_eq!(viewer.sounds.transport.time, 0.6, "the clock moved it");
        }
        assert_eq!(viewer.sounds.transport.motion, Motion::Playing);

        // Letting go hands the position back to the clock.
        viewer.sounds.scrubbing = false;
        clock += STEP;
        run_clock(&mut viewer, &ctx, clock);
        assert!(
            viewer.sounds.transport.time > 0.6,
            "the clock did not resume, got {}",
            viewer.sounds.transport.time
        );

        // ⚠️ And a drawn frame with no pointer in it leaves the flag false, so
        // a scrub that ended outside the window cannot freeze the clock.
        viewer.sounds.scrubbing = true;
        clock += STEP;
        draw_sounds(&mut viewer, &ctx, clock);
        assert!(!viewer.sounds.scrubbing, "nothing is holding the scrubber");
    }

    /// ⚠️ The two ways a track gets abandoned. Both have to silence it: a
    /// stream left running behind a tab nobody is looking at has no visible
    /// control to stop it with.
    #[test]
    fn changing_track_or_leaving_the_tab_stops_what_was_playing() {
        let mut viewer = sound_viewer("sounds-stop");

        viewer.select_sound(0);
        viewer.sounds.transport.play();
        viewer.sounds.transport.seek(0.4, 1.0);
        assert_eq!(viewer.sounds.transport.time, 0.4);

        viewer.select_sound(1);
        assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);
        assert_eq!(viewer.sounds.transport.time, 0.0, "and back to the start");
        assert_eq!(
            viewer
                .sounds
                .loaded
                .as_ref()
                .expect("quiet.wav")
                .audio
                .channels(),
            1,
            "the new track's samples replaced the old ones"
        );

        viewer.sounds.transport.play();
        viewer.mode = Mode::Textures;
        viewer.switched_from(Mode::Sounds);
        assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);

        // Opening another folder drops the pane, and with it the engine.
        viewer.mode = Mode::Sounds;
        viewer.select_sound(0);
        viewer.sounds.transport.play();
        viewer.open(export_folder("sounds-reopen"));
        assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);
        assert!(viewer.sounds.selected.is_none());
    }

    /// One egui frame with every effect panel in it, and no window anywhere.
    fn draw(viewer: &mut Viewer, ctx: &egui::Context) {
        let _ = ctx.run(egui::RawInput::default(), |ctx| {
            viewer.top_bar(ctx);
            viewer.run_clock(ctx);
            viewer.effect_list(ctx);
            viewer.effect_bank(ctx);
            egui::CentralPanel::default().show(ctx, |ui| viewer.effect_detail(ui));
        });
    }

    /// ⚠️ "The window opens" is not evidence anybody can check: this machine
    /// cannot capture its own interactive desktop. Laying the panels out
    /// headlessly is — a slider over an empty range, a panel that borrows
    /// itself, or a layout that panics surfaces here instead of on a screen
    /// nobody can photograph.
    #[test]
    fn the_effect_panels_lay_out_and_play_without_a_window() {
        let root = export_folder("panels");
        let mut viewer = Viewer {
            mode: Mode::Effects,
            ..Viewer::empty()
        };
        viewer.open(root);
        assert_eq!(viewer.effects.library.len(), 2);
        assert_eq!(viewer.effects.bank.len(), 1, "only the effdata image");

        let ctx = egui::Context::default();
        viewer.select_effect(0);
        viewer.effects.play.playing = true;
        draw(&mut viewer, &ctx);
        assert!(
            viewer.effects.play.time > 0.0,
            "a drawn frame advances the timeline, got {}",
            viewer.effects.play.time
        );
        assert!(
            viewer.effects.play.time < 3.0,
            "and stays inside the effect"
        );

        // ⚠️ The single-frame effect is the one that could panic: its
        // duration is zero, and a slider needs a range to put a handle in.
        viewer.select_effect(1);
        draw(&mut viewer, &ctx);
        assert_eq!(viewer.effects.play.time, 0.0);
        assert!(!viewer.effects.play.playing, "nothing to play, so it stops");

        // An empty selection and an empty folder are the other two shapes the
        // panels have to survive.
        viewer.effects.selected = None;
        draw(&mut viewer, &ctx);
        viewer.select_effect(0);
        draw(&mut viewer, &ctx);
        let mut bare = Viewer {
            mode: Mode::Effects,
            ..Viewer::empty()
        };
        bare.open(std::env::temp_dir().join("dimentio-ui-absent"));
        assert!(bare.effects.library.problem().is_some());
        draw(&mut bare, &ctx);
    }

    /// The viewport's plumbing, end to end through the window: an effect is
    /// picked, a frame is rasterised, and a bank image the user clicked reaches
    /// the part they chose.
    ///
    /// ⛔ The pairing is the user's. Nothing here reads an image out of the
    /// effect data, and `render::effect`'s own tests are what prove the chosen
    /// image changes the pixels — this only proves the window can deliver it.
    #[test]
    fn the_viewport_rasterises_and_takes_a_manually_chosen_image() {
        let root = export_folder("stage");
        let mut viewer = Viewer {
            mode: Mode::Effects,
            ..Viewer::empty()
        };
        viewer.open(root);
        let ctx = egui::Context::default();

        viewer.select_effect(0);
        assert!(!viewer.effects.stage.drawn(), "nothing has been drawn yet");
        draw(&mut viewer, &ctx);
        assert!(viewer.effects.stage.drawn(), "the viewport drew no frame");
        assert_eq!(
            viewer.effects.stage.previewing(),
            None,
            "nothing was picked"
        );

        let image = viewer.effects.bank[0];
        viewer.choose_image(image);
        assert_eq!(
            viewer.effects.stage.previewing(),
            Some(("files/eff/effdata.tpl#0", 0)),
            "the clicked image did not reach the chosen part"
        );
        draw(&mut viewer, &ctx);

        // A catalog entry whose PNG is not on disk must say so rather than
        // silently keeping the last image.
        std::fs::remove_file(&viewer.catalog.entries()[image].path).expect("the png");
        viewer.choose_image(image);
        assert_eq!(viewer.effects.stage.previewing(), None);
        draw(&mut viewer, &ctx);
    }
}
