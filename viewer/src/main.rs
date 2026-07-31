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
//! ```text
//! uv run bleck texture export --out work/export
//! cargo run -- ../work/export
//! ```
//!
//! # State
//!
//! Stage 1 of five: a texture browser. There is deliberately **no 3D viewport
//! yet** — the model container is not decoded (only its string table is
//! readable), so a camera orbiting an empty scene would prove nothing and
//! could not be validated. Stage 2 begins when there is geometry to show.

use eframe::egui;

mod catalog;

/// Thumbnail edge, in points. Small enough that a few hundred fit on screen.
const THUMB: f32 = 96.0;

/// Space around each thumbnail, so the grid arithmetic matches the layout.
const PAD: f32 = 8.0;

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1180.0, 760.0])
            .with_min_inner_size([720.0, 420.0])
            .with_title("bleck viewer"),
        ..Default::default()
    };
    eframe::run_native(
        "bleck-viewer",
        options,
        Box::new(|cc| {
            egui_extras::install_image_loaders(&cc.egui_ctx);
            Ok(Box::new(Viewer::from_args()))
        }),
    )
}

struct Viewer {
    root: Option<std::path::PathBuf>,
    catalog: catalog::Catalog,
    search: String,
    /// None means "every format".
    format: Option<String>,
    selected: Option<usize>,
}

impl Viewer {
    fn from_args() -> Self {
        let mut viewer = Self {
            root: None,
            catalog: catalog::Catalog::default(),
            search: String::new(),
            format: None,
            selected: None,
        };
        if let Some(path) = std::env::args().nth(1) {
            viewer.open(std::path::PathBuf::from(path));
        }
        viewer
    }

    fn open(&mut self, root: std::path::PathBuf) {
        self.catalog = catalog::Catalog::load(&root);
        self.root = Some(root);
        self.selected = None;
    }
}

impl eframe::App for Viewer {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.top_bar(ctx);
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
}

const WELCOME: &str = "\
No export folder given.

This viewer renders what bleck exports, and reads no game formats itself.

    uv run bleck texture export --out work/export
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
                ui.label("Search");
                ui.add(
                    egui::TextEdit::singleline(&mut self.search)
                        .desired_width(220.0)
                        .hint_text("path or name"),
                );
                if ui.button("clear").clicked() {
                    self.search.clear();
                }
                ui.separator();

                // Only formats actually present, so the filter cannot select
                // an empty set.
                let label = self.format.clone().unwrap_or_else(|| "all".into());
                egui::ComboBox::from_label("format")
                    .selected_text(label)
                    .show_ui(ui, |ui| {
                        ui.selectable_value(&mut self.format, None, "all");
                        for format in self.catalog.formats() {
                            ui.selectable_value(&mut self.format, Some(format.clone()), format);
                        }
                    });

                ui.separator();
                let shown = self
                    .catalog
                    .matching(&self.search, self.format.as_deref())
                    .len();
                ui.label(format!("{shown} of {} texture(s)", self.catalog.len()));
            });
            ui.add_space(4.0);
        });
    }

    fn detail_panel(&mut self, ctx: &egui::Context) {
        let Some(entry) = self
            .selected
            .and_then(|index| self.catalog.entries().get(index))
            .cloned()
        else {
            return;
        };
        egui::SidePanel::right("detail")
            .default_width(320.0)
            .show(ctx, |ui| {
                ui.add_space(8.0);
                ui.heading(&entry.format);
                ui.add_space(8.0);
                // Fit rather than fill: an 8x32 texture stretched to a square
                // panel would misrepresent its shape.
                ui.add(
                    egui::Image::new(entry.uri())
                        .max_size(egui::vec2(288.0, 288.0))
                        .maintain_aspect_ratio(true),
                );
                ui.add_space(12.0);
                egui::Grid::new("facts").num_columns(2).show(ui, |ui| {
                    Self::fact(ui, "size", &format!("{}x{}", entry.width, entry.height));
                    Self::fact(ui, "format", &entry.format);
                    Self::fact(ui, "source", &entry.source);
                    if !entry.member.is_empty() {
                        Self::fact(ui, "member", &entry.member);
                    }
                });
                ui.add_space(8.0);
                ui.label(egui::RichText::new(&entry.name).monospace().small());
                ui.add_space(8.0);
                if ui.button("close").clicked() {
                    self.selected = None;
                }
            });
    }

    fn fact(ui: &mut egui::Ui, key: &str, value: &str) {
        ui.label(egui::RichText::new(key).weak());
        ui.label(egui::RichText::new(value).monospace());
        ui.end_row();
    }

    /// ⚠️ Rows are virtualised on purpose. The disc holds 21,780 textures, and
    /// egui uploads every image it draws to the GPU and keeps it. Drawing them
    /// all would exhaust texture memory within a few seconds of scrolling;
    /// `show_rows` only calls back for the rows actually on screen.
    fn grid(&mut self, ui: &mut egui::Ui) {
        let visible = self.catalog.matching(&self.search, self.format.as_deref());
        if visible.is_empty() {
            Self::message(ui, "Nothing matches that search.");
            return;
        }

        let step = THUMB + PAD;
        let columns = ((ui.available_width() / step).floor() as usize).max(1);
        let rows = visible.len().div_ceil(columns);

        egui::ScrollArea::vertical().show_rows(ui, step, rows, |ui, range| {
            for row in range {
                ui.horizontal(|ui| {
                    for column in 0..columns {
                        let Some(&index) = visible.get(row * columns + column) else {
                            break;
                        };
                        self.thumbnail(ui, index);
                    }
                });
            }
        });
    }

    fn thumbnail(&mut self, ui: &mut egui::Ui, index: usize) {
        let Some(entry) = self.catalog.entries().get(index) else {
            return;
        };
        let selected = self.selected == Some(index);
        let image = egui::Image::new(entry.uri())
            .fit_to_exact_size(egui::vec2(THUMB, THUMB))
            .maintain_aspect_ratio(true)
            .sense(egui::Sense::click());

        let response = ui.add(image);
        if selected {
            ui.painter().rect_stroke(
                response.rect.expand(2.0),
                2.0,
                ui.visuals().selection.stroke,
            );
        }
        if response.clicked() {
            self.selected = Some(index);
        }
        response.on_hover_text(format!("{}\n{}", entry.name, entry.describe()));
    }
}
