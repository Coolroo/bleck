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
//!
//! Copying a name to the clipboard is one idiom, and it lives in `clipboard`:
//! all four modes reach for the same `Asset`, so a row copies the same way
//! whichever list it is in.

use eframe::egui;

use crate::data;
use crate::render;

mod audio;
mod clipboard;
mod effects;
mod models;
mod sounds;
mod textures;

use clipboard::copy_note;
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
                self.run_model_clock(ctx);
                self.model_list(ctx);
                self.model_facts(ctx);
                self.model_transport(ctx);
                self.hold_pose();
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
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), copy_note);
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
mod tests;
