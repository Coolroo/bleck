//! The window: what is on screen, and the state the three modes share.
//!
//! One export folder feeds every mode, so it is opened once here and each mode
//! reads its own manifest out of it. A mode's panels live beside the state they
//! draw — `textures`, `models`, `effects` — and every panel is a method on
//! `Viewer`, because egui draws from state mutated in place rather than from a
//! returned tree.

use eframe::egui;

use crate::data;

mod effects;
mod models;
mod textures;

use effects::EffectPane;
use models::ModelPane;

/// Space around each thumbnail, so the grid arithmetic matches the layout.
/// Shared by the texture grid and the effect image strip.
const PAD: f32 = 8.0;

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

    fn export_folder() -> std::path::PathBuf {
        let root = std::env::temp_dir().join(format!("dimentio-ui-{}", std::process::id()));
        std::fs::create_dir_all(&root).expect("scratch dir");
        std::fs::write(root.join("effects.json"), EFFECTS).expect("effects.json");
        std::fs::write(root.join("textures.json"), TEXTURES).expect("textures.json");
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
        let root = export_folder();
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
        let mut bare = Viewer {
            mode: Mode::Effects,
            ..Viewer::empty()
        };
        bare.open(std::env::temp_dir().join("dimentio-ui-absent"));
        assert!(bare.effects.library.problem().is_some());
        draw(&mut bare, &ctx);
    }
}
