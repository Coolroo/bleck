//! Dimentio — look at Super Paper Mario's assets without building a disc.
//!
//! Named for the jester who steps sideways out of the world to watch it: this
//! is the window onto the game's art that does not require booting the game.
//!
//! # What this program is not
//!
//! It does not read a single game format. `bleck` owns those — TPL, U8, LZ77,
//! setup files, evt bytecode — and is tested against a real disc. A second
//! implementation here would drift from that one silently, and the failure
//! would be a texture that builds correctly and displays wrongly, or worse the
//! reverse.
//!
//! So `bleck` exports PNG and JSON, and this renders them. Dimentio improves
//! for free as `bleck` learns more formats, and format bugs have exactly one
//! place to be fixed. See `docs/plan-dimentio.md`.
//!
//! ```text
//! uv run bleck texture export --out work/export
//! uv run bleck model   export --out work/export
//! cargo run -- ../work/export
//! ```
//!
//! # State
//!
//! Two modes over one export folder: the texture browser, and a model viewport
//! fed by the software rasteriser in `render.rs`.
//!
//! ⚠️ The viewport draws on the CPU, not through `eframe`'s GPU surface. That
//! is what lets `render.rs` be tested with no window and no driver, which is
//! the only evidence this program has that it draws the right thing.

use eframe::egui;

mod catalog;
mod mesh;
mod render;

/// Thumbnail edge, in points. Small enough that a few hundred fit on screen.
const THUMB: f32 = 96.0;

/// Space around each thumbnail, so the grid arithmetic matches the layout.
const PAD: f32 = 8.0;

/// Radians of orbit per point of drag.
const ORBIT_SPEED: f32 = 0.008;

/// How hard a scroll notch pulls the camera in. Applied as an exponent, so
/// zoom is proportional and cannot walk through zero.
const ZOOM_SPEED: f32 = 0.0015;

/// ⚠️ Longest edge the viewport is rasterised at, whatever size the panel is.
/// Every pixel costs CPU here, and a maximised 4K window would otherwise
/// rasterise ~8M of them on each frame of a drag. Beyond this the frame is
/// drawn smaller and scaled up by the GPU.
const MAX_EDGE: f32 = 1600.0;

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1180.0, 760.0])
            .with_min_inner_size([720.0, 420.0])
            .with_title("Dimentio"),
        ..Default::default()
    };
    eframe::run_native(
        "Dimentio",
        options,
        Box::new(|cc| {
            egui_extras::install_image_loaders(&cc.egui_ctx);
            Ok(Box::new(Viewer::from_args()))
        }),
    )
}

/// Which half of the program is on screen. One export folder feeds both.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
enum Mode {
    #[default]
    Textures,
    Models,
}

struct Viewer {
    root: Option<std::path::PathBuf>,
    catalog: catalog::Catalog,
    search: String,
    /// None means "every format".
    format: Option<String>,
    selected: Option<usize>,
    mode: Mode,
    models: ModelPane,
}

/// Everything the model mode owns. Grouped so the texture fields stay legible
/// beside it, and so one `stale` flag decides when to rasterise.
#[derive(Default)]
struct ModelPane {
    library: mesh::Library,
    search: String,
    selected: Option<usize>,
    /// The selected model's geometry. Empty until something is picked, and
    /// empty again if the file behind a selection could not be read.
    mesh: mesh::Mesh,
    /// Why the selected model has no geometry, as opposed to the library
    /// having none.
    problem: Option<mesh::Problem>,
    view: render::View,
    /// The last rasterised frame, uploaded once and replaced in place. A new
    /// handle per frame would leak a GPU texture per frame.
    frame: Option<egui::TextureHandle>,
    size: render::Size,
    /// Set by anything that changes what the frame should look like. ⚠️ Without
    /// it the rasteriser runs every frame, whether or not anything moved.
    stale: bool,
}

impl Viewer {
    fn from_args() -> Self {
        let mut viewer = Self {
            root: None,
            catalog: catalog::Catalog::default(),
            search: String::new(),
            format: None,
            selected: None,
            mode: Mode::default(),
            models: ModelPane::default(),
        };
        if let Some(path) = std::env::args().nth(1) {
            viewer.open(std::path::PathBuf::from(path));
        }
        viewer
    }

    fn open(&mut self, root: std::path::PathBuf) {
        self.catalog = catalog::Catalog::load(&root);
        self.models = ModelPane {
            library: mesh::Library::load(&root),
            ..Default::default()
        };
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
        }
    }
}

const WELCOME: &str = "\
No export folder given.

Dimentio renders what bleck exports, and reads no game formats itself.

    uv run bleck texture export --out work/export
    uv run bleck model   export --out work/export
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
                ui.separator();
                match self.mode {
                    Mode::Textures => self.texture_controls(ui),
                    Mode::Models => self.model_controls(ui),
                }
            });
            ui.add_space(4.0);
        });
    }

    fn texture_controls(&mut self, ui: &mut egui::Ui) {
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
    }

    fn model_controls(&mut self, ui: &mut egui::Ui) {
        let chosen = self.models.view.background;
        egui::ComboBox::from_label("background")
            .selected_text(chosen.label())
            .show_ui(ui, |ui| {
                for background in render::BACKGROUNDS {
                    ui.selectable_value(
                        &mut self.models.view.background,
                        background,
                        background.label(),
                    );
                }
            });
        if self.models.view.background != chosen {
            self.models.stale = true;
        }

        ui.separator();
        if ui.button("fit").clicked() {
            self.models.view.camera = render::Camera::fit(self.models.mesh.bounds());
            self.models.stale = true;
        }
        ui.label(
            egui::RichText::new("drag to orbit · scroll to zoom")
                .weak()
                .small(),
        );
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
        Self::inline_fact(ui, key, value);
        ui.end_row();
    }

    /// The same pair without `end_row`, which in a horizontal layout would
    /// wrap the strip onto a second line instead of ending a grid row.
    fn inline_fact(ui: &mut egui::Ui, key: &str, value: &str) {
        ui.label(egui::RichText::new(key).weak());
        ui.label(egui::RichText::new(value).monospace());
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

    /// The models to choose from, searchable. Rows are virtualised for the
    /// same reason the texture grid is: `/a` holds 1,687 model files, and a
    /// widget per row is a widget per row whether or not it is on screen.
    fn model_list(&mut self, ctx: &egui::Context) {
        egui::SidePanel::left("models")
            .default_width(300.0)
            .show(ctx, |ui| {
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    ui.label("Search");
                    ui.add(
                        egui::TextEdit::singleline(&mut self.models.search)
                            .desired_width(150.0)
                            .hint_text("name or shape"),
                    );
                    if ui.button("clear").clicked() {
                        self.models.search.clear();
                    }
                });

                let visible = self.models.library.matching(&self.models.search);
                ui.label(
                    egui::RichText::new(format!(
                        "{} of {} model(s)",
                        visible.len(),
                        self.models.library.len()
                    ))
                    .weak(),
                );
                ui.separator();

                // The viewport says what went wrong, in the space to say it in.
                if self.models.library.problem().is_some() {
                    return;
                }

                let selected = self.models.selected;
                let entries = self.models.library.entries();
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
                        let label = if entry.shape.is_empty() {
                            entry.name.clone()
                        } else {
                            format!("{}  ·  {}", entry.name, entry.shape)
                        };
                        let row = ui.selectable_label(selected == Some(index), label);
                        if row.on_hover_text(entry.describe()).clicked() {
                            picked = Some(index);
                        }
                    }
                });
                if let Some(index) = picked {
                    self.select_model(index);
                }
            });
    }

    /// What `bleck` recorded about the selection, under the viewport.
    fn model_facts(&mut self, ctx: &egui::Context) {
        let Some(entry) = self
            .models
            .selected
            .and_then(|index| self.models.library.entries().get(index))
            .cloned()
        else {
            return;
        };
        egui::TopBottomPanel::bottom("model-facts").show(ctx, |ui| {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                Self::inline_fact(ui, "source", &entry.source);
                ui.separator();
                Self::inline_fact(ui, "shape", &entry.shape);
                ui.separator();
                Self::inline_fact(ui, "verts", &entry.positions.to_string());
                ui.separator();
                Self::inline_fact(ui, "faces", &entry.faces.to_string());
                ui.separator();
                Self::inline_fact(ui, "tris", &entry.triangles.to_string());
                ui.separator();
                Self::inline_fact(ui, "extent", &entry.extent());
                if entry.fragment {
                    ui.separator();
                    ui.label(
                        egui::RichText::new(format!(
                            "fragment — {:.0}% of this file's vertices",
                            entry.coverage * 100.0
                        ))
                        .color(egui::Color32::from_rgb(220, 170, 90)),
                    )
                    .on_hover_text(
                        "One shape record out of a file that holds many. \
                         What is drawn is all the export contains.",
                    );
                }
            });
            ui.add_space(4.0);
        });
    }

    /// Read the geometry for `index` and frame it.
    ///
    /// ⚠️ The camera is refitted here and nowhere else. Refitting on every
    /// frame would fight the user's own orbit and zoom; not refitting on a new
    /// selection leaves a model either off-screen or a speck, since exported
    /// models are in the game's units and differ in size by orders of
    /// magnitude.
    fn select_model(&mut self, index: usize) {
        let Some(path) = self
            .models
            .library
            .entries()
            .get(index)
            .map(|entry| entry.path.clone())
        else {
            return;
        };
        self.models.selected = Some(index);
        self.models.stale = true;
        match mesh::Mesh::load(&path) {
            Ok(mesh) => {
                self.models.view.camera = render::Camera::fit(mesh.bounds());
                self.models.mesh = mesh;
                self.models.problem = None;
            }
            Err(problem) => {
                self.models.mesh = mesh::Mesh::default();
                self.models.problem = Some(problem);
            }
        }
    }

    fn viewport(&mut self, ui: &mut egui::Ui) {
        if let Some(problem) = self.models.library.problem() {
            Self::message(ui, &problem.describe());
            return;
        }
        if let Some(problem) = &self.models.problem {
            Self::message(ui, &problem.describe());
            return;
        }
        if self.models.selected.is_none() {
            Self::message(ui, "Pick a model on the left.");
            return;
        }

        let area = ui.available_size();
        let (rect, response) = ui.allocate_exact_size(area, egui::Sense::click_and_drag());
        self.steer(ui, &response);

        // Rasterised at the panel's aspect ratio, so a wide window does not
        // squash the model; only the resolution is capped.
        let scale = (MAX_EDGE / area.x.max(area.y).max(1.0)).min(1.0);
        let size = render::Size::new(
            ((area.x * scale) as usize).max(1),
            ((area.y * scale) as usize).max(1),
        );
        if size != self.models.size {
            self.models.size = size;
            self.models.stale = true;
        }

        if self.models.stale || self.models.frame.is_none() {
            let drawn = render::render(&self.models.mesh, &self.models.view, size);
            let image = egui::ColorImage::from_rgba_unmultiplied(
                [size.width, size.height],
                drawn.as_rgba(),
            );
            match &mut self.models.frame {
                Some(handle) => handle.set(image, egui::TextureOptions::LINEAR),
                None => {
                    self.models.frame = Some(ui.ctx().load_texture(
                        "viewport",
                        image,
                        egui::TextureOptions::LINEAR,
                    ));
                }
            }
            self.models.stale = false;
        }

        if let Some(handle) = &self.models.frame {
            ui.painter().image(
                handle.id(),
                rect,
                egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                egui::Color32::WHITE,
            );
        }
    }

    /// Drag orbits, scroll zooms. Both only mark the frame stale; the camera
    /// itself does the clamping, so no input can put it somewhere it cannot
    /// come back from.
    fn steer(&mut self, ui: &egui::Ui, response: &egui::Response) {
        let drag = response.drag_delta();
        if drag != egui::Vec2::ZERO {
            self.models
                .view
                .camera
                .orbit(drag.x * ORBIT_SPEED, drag.y * ORBIT_SPEED);
            self.models.stale = true;
        }
        if response.hovered() {
            let scroll = ui.input(|input| input.smooth_scroll_delta.y);
            if scroll != 0.0 {
                self.models.view.camera.zoom((-scroll * ZOOM_SPEED).exp());
                self.models.stale = true;
            }
        }
    }
}
