//! Look at Super Paper Mario's assets without building a 460 MB disc first.
//!
//! # What this program is not
//!
//! It does not read a single game format. `bleck` owns those — TPL, U8, LZ77,
//! setup files, evt bytecode — and is tested against a real disc. A second
//! implementation here would drift from that one silently, and the failure
//! would be a texture that builds correctly and displays wrongly, or worse the
//! reverse.
//!
//! So `bleck` exports PNG and JSON, and this renders them. The viewer improves
//! for free as `bleck` learns more formats, and format bugs have exactly one
//! place to be fixed. See `docs/plan-viewer.md`.
//!
//! # State
//!
//! Stage 1 of five: a texture browser. There is deliberately **no 3D viewport
//! yet** — the model container is not decoded (only its string table is
//! readable), so a camera orbiting an empty scene would prove nothing and
//! could not be validated. Stage 2 begins when there is geometry to show.

use eframe::egui;

mod catalog;

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1100.0, 720.0])
            .with_min_inner_size([640.0, 400.0])
            .with_title("bleck viewer"),
        ..Default::default()
    };
    eframe::run_native(
        "bleck-viewer",
        options,
        Box::new(|cc| {
            egui_extras::install_image_loaders(&cc.egui_ctx);
            Ok(Box::new(Viewer::default()))
        }),
    )
}

#[derive(Default)]
struct Viewer {
    /// Where `bleck texture export` put its PNGs. Empty until one is chosen.
    exported: Option<std::path::PathBuf>,
    catalog: catalog::Catalog,
    search: String,
    selected: Option<usize>,
}

impl eframe::App for Viewer {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        egui::TopBottomPanel::top("bar").show(ctx, |ui| {
            ui.horizontal(|ui| {
                if ui.button("Open export folder…").clicked() {
                    self.open_folder();
                }
                ui.separator();
                ui.label("Search:");
                ui.text_edit_singleline(&mut self.search);
                ui.separator();
                ui.label(format!("{} texture(s)", self.catalog.len()));
            });
        });

        egui::CentralPanel::default().show(ctx, |ui| {
            if self.exported.is_none() {
                self.welcome(ui);
                return;
            }
            self.grid(ui);
        });
    }
}

impl Viewer {
    /// ⚠️ Says what to run, not just that something is missing. The export step
    /// is the part a new user has no way to guess.
    fn welcome(&mut self, ui: &mut egui::Ui) {
        ui.add_space(40.0);
        ui.vertical_centered(|ui| {
            ui.heading("No textures loaded");
            ui.add_space(12.0);
            ui.label("This viewer renders what bleck exports. Produce some first:");
            ui.add_space(8.0);
            ui.code("uv run bleck texture export --out art/");
            ui.add_space(12.0);
            ui.label("then open art/ with the button above.");
        });
    }

    fn open_folder(&mut self) {
        // Deliberately not a native file dialog yet: that is another dependency
        // and a platform surface, and the path can come from the command line
        // until the rest of the program earns it.
        if let Some(path) = std::env::args().nth(1) {
            let root = std::path::PathBuf::from(path);
            self.catalog = catalog::Catalog::load(&root);
            self.exported = Some(root);
        }
    }

    fn grid(&mut self, ui: &mut egui::Ui) {
        let needle = self.search.to_lowercase();
        egui::ScrollArea::vertical().show(ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                for (index, texture) in self.catalog.entries().iter().enumerate() {
                    if !needle.is_empty() && !texture.name.to_lowercase().contains(&needle) {
                        continue;
                    }
                    let uri = format!("file://{}", texture.path.display());
                    let response = ui.add(
                        egui::Image::new(uri)
                            .fit_to_exact_size(egui::vec2(96.0, 96.0))
                            .sense(egui::Sense::click()),
                    );
                    if response.clicked() {
                        self.selected = Some(index);
                    }
                    // The GameCube format is the part a modder needs and a
                    // filename cannot carry: CMPR recolours losslessly, an
                    // intensity format cannot hold a hue at all.
                    response.on_hover_text(format!(
                        "{}\n{}x{} {}",
                        texture.name, texture.width, texture.height, texture.format
                    ));
                }
            });
        });
    }
}
