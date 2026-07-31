//! The window: what is on screen, and the state the three modes share.
//!
//! One export folder feeds every mode, so it is opened once here and each mode
//! reads its own manifest out of it. A mode's panels live beside the state they
//! draw — `textures`, `models`, `effects` — and every panel is a method on
//! `Viewer`, because egui draws from state mutated in place rather than from a
//! returned tree.

use eframe::egui;

use crate::data;
use crate::render;

mod effects;
mod models;
mod textures;

use effects::EffectPane;
use models::ModelPane;

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
        }
    }

    fn open(&mut self, root: std::path::PathBuf) {
        self.catalog = data::Catalog::load(&root);
        self.models = ModelPane::load(&root);
        // The bank is read out of the texture catalog, so the effect pane is
        // built after that catalog is loaded and never before.
        self.effects = EffectPane::load(&root, &self.catalog);
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
        }
    }
}

const WELCOME: &str = "\
No export folder given.

Dimentio renders what bleck exports, and reads no game formats itself.

    uv run bleck texture export --out work/export
    uv run bleck model   export --out work/export
    uv run bleck effect  export --out work/export
    cargo run -- ../work/export";

impl Viewer {
    fn message(ui: &mut egui::Ui, text: &str) {
        ui.add_space(48.0);
        ui.vertical_centered(|ui| {
            ui.label(egui::RichText::new(text).monospace());
        });
    }

    fn top_bar(&mut self, ctx: &egui::Context) {
        egui::TopBottomPanel::top("bar").show(ctx, |ui| {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.selectable_value(&mut self.mode, Mode::Textures, "Textures");
                ui.selectable_value(&mut self.mode, Mode::Models, "Models");
                ui.selectable_value(&mut self.mode, Mode::Effects, "Effects");
                ui.separator();
                match self.mode {
                    Mode::Textures => self.texture_controls(ui),
                    Mode::Models => self.model_controls(ui),
                    Mode::Effects => self.effect_controls(ui),
                }
            });
            ui.add_space(4.0);
        });
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

    /// ⚠️ The PNGs are written for real. `choose_image` decodes the file the
    /// catalog names, so a folder of manifests with no images behind them would
    /// exercise only the failure path.
    /// ⚠️ Tagged per test. One folder shared between them races: a test that
    /// deletes an image to reach the failure path would delete it under a test
    /// running beside it.
    fn export_folder(tag: &str) -> std::path::PathBuf {
        let root = std::env::temp_dir().join(format!("dimentio-ui-{tag}-{}", std::process::id()));
        std::fs::create_dir_all(&root).expect("scratch dir");
        std::fs::write(root.join("effects.json"), EFFECTS).expect("effects.json");
        std::fs::write(root.join("textures.json"), TEXTURES).expect("textures.json");
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
        root
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
