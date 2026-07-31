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
//! uv run bleck effect  export --out work/export
//! cargo run -- ../work/export
//! ```
//!
//! # State
//!
//! Three modes over one export folder: the texture browser, a model viewport
//! fed by the software rasteriser in `render.rs`, and the effect table with
//! its timeline.
//!
//! ⚠️ The viewport draws on the CPU, not through `eframe`'s GPU surface. That
//! is what lets `render.rs` be tested with no window and no driver, which is
//! the only evidence this program has that it draws the right thing.

use eframe::egui;

mod catalog;
mod effects;
mod mesh;
mod render;

/// Thumbnail edge, in points. Small enough that a few hundred fit on screen.
const THUMB: f32 = 96.0;

/// Space around each thumbnail, so the grid arithmetic matches the layout.
const PAD: f32 = 8.0;

/// Thumbnail edge for the effect image bank, in points. Smaller than the
/// grid's: the strip is one row deep and shares the window with the effect
/// it sits under.
const BANK_THUMB: f32 = 64.0;

/// Marks a part that is running at the timeline's current position.
const ACTIVE: egui::Color32 = egui::Color32::from_rgb(120, 200, 120);

/// Carries the standing warning that a part's image is not decoded. The same
/// amber the model pane uses for a fragment: both say "this is less than it
/// looks like".
const UNDECODED: egui::Color32 = egui::Color32::from_rgb(220, 170, 90);

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

/// Which part of the program is on screen. One export folder feeds them all.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
enum Mode {
    #[default]
    Textures,
    Models,
    Effects,
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
    effects: EffectPane,
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

/// Everything the effect mode owns.
///
/// ⛔ `bank` is the effect system's whole image bank and is never indexed by
/// anything to do with a part. Which image a part draws is not decoded; see
/// `effects::bank`.
#[derive(Default)]
struct EffectPane {
    library: effects::Library,
    search: String,
    selected: Option<usize>,
    play: effects::Playback,
    /// Indices into the texture catalog of the effect system's images.
    /// Resolved once when a folder is opened: the filter is by disc file, and
    /// neither the catalog nor that file changes while the folder is open.
    bank: Vec<usize>,
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
            effects: EffectPane::default(),
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
        // The bank is read out of the texture catalog, so it is resolved after
        // that catalog is loaded and never before.
        let library = effects::Library::load(&root);
        let bank = effects::bank(self.catalog.entries(), library.textures());
        self.effects = EffectPane {
            library,
            bank,
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

    fn effect_controls(&mut self, ui: &mut egui::Ui) {
        let shown = self.effects.library.matching(&self.effects.search).len();
        ui.label(format!(
            "{shown} of {} effect(s)",
            self.effects.library.len()
        ));
        ui.separator();
        ui.label(
            egui::RichText::new("durations are frames at 60Hz, counted inclusively")
                .weak()
                .small(),
        );
    }

    fn selected_effect(&self) -> Option<&effects::Entry> {
        self.effects
            .selected
            .and_then(|index| self.effects.library.entries().get(index))
    }

    /// Advance the scrubber, and keep frames coming while it moves.
    ///
    /// ⚠️ `request_repaint` is what makes playback run at all. egui redraws in
    /// response to input and nothing else, so without it the timeline would
    /// step once per mouse movement and stand still otherwise.
    fn run_clock(&mut self, ctx: &egui::Context) {
        if !self.effects.play.playing {
            return;
        }
        let span = self.selected_effect().map_or(0.0, |entry| entry.seconds);
        let dt = ctx.input(|input| input.stable_dt);
        self.effects.play.advance(dt, span);
        ctx.request_repaint();
    }

    /// The effects to choose from, searchable. Rows are virtualised for the
    /// same reason the model list's are: a widget per row costs a widget per
    /// row whether or not that row is on screen.
    fn effect_list(&mut self, ctx: &egui::Context) {
        egui::SidePanel::left("effects")
            .default_width(260.0)
            .show(ctx, |ui| {
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    ui.label("Search");
                    ui.add(
                        egui::TextEdit::singleline(&mut self.effects.search)
                            .desired_width(120.0)
                            .hint_text("effect or part"),
                    );
                    if ui.button("clear").clicked() {
                        self.effects.search.clear();
                    }
                });

                let visible = self.effects.library.matching(&self.effects.search);
                ui.label(
                    egui::RichText::new(format!(
                        "{} of {} effect(s)",
                        visible.len(),
                        self.effects.library.len()
                    ))
                    .weak(),
                );
                ui.separator();

                // The central panel says what went wrong, in the space to say
                // it in.
                if self.effects.library.problem().is_some() {
                    return;
                }

                let selected = self.effects.selected;
                let entries = self.effects.library.entries();
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
                        let label = format!("{}  ·  {:.2}s", entry.name, entry.seconds);
                        let row = ui.selectable_label(selected == Some(index), label);
                        if row.on_hover_text(entry.describe()).clicked() {
                            picked = Some(index);
                        }
                    }
                });
                if let Some(index) = picked {
                    self.select_effect(index);
                }
            });
    }

    /// Pick an effect and put the timeline back at its start: a different
    /// effect has a different length, and the old position may be past its end.
    fn select_effect(&mut self, index: usize) {
        self.effects.selected = Some(index);
        self.effects.play.rewind();
    }

    fn effect_detail(&mut self, ui: &mut egui::Ui) {
        let Some(index) = self.effects.selected else {
            Self::message(ui, "Pick an effect on the left.");
            return;
        };
        let Some(entry) = self.effects.library.entries().get(index) else {
            Self::message(ui, "That effect is no longer in the manifest.");
            return;
        };

        ui.add_space(4.0);
        ui.heading(&entry.name);
        ui.add_space(4.0);
        ui.horizontal(|ui| {
            Self::inline_fact(ui, "index", &entry.index.to_string());
            ui.separator();
            Self::inline_fact(ui, "parts", &entry.parts.len().to_string());
            ui.separator();
            Self::inline_fact(ui, "rows", &entry.rows.len().to_string());
            ui.separator();
            Self::inline_fact(
                ui,
                "duration",
                &format!("{:.3}s · {} frames", entry.seconds, entry.frames()),
            );
        });
        ui.separator();
        Self::timeline(ui, entry, &mut self.effects.play);
        ui.separator();

        let time = self.effects.play.time;
        egui::ScrollArea::vertical().show(ui, |ui| {
            Self::part_table(ui, entry, time);
            ui.add_space(12.0);
            Self::row_table(ui, entry);
        });
    }

    /// Play, pause and scrub.
    ///
    /// ⚠️ An effect that lasts a single frame gets no scrubber: its range
    /// would be empty, and there is nothing to move through.
    fn timeline(ui: &mut egui::Ui, entry: &effects::Entry, play: &mut effects::Playback) {
        ui.horizontal(|ui| {
            if entry.seconds <= 0.0 {
                play.playing = false;
                play.time = 0.0;
                ui.label(egui::RichText::new("one frame — nothing to play").weak());
                return;
            }
            let symbol = if play.playing { "⏸" } else { "▶" };
            if ui.button(symbol).on_hover_text("play / pause").clicked() {
                play.playing = !play.playing;
            }
            if ui.button("⏮").on_hover_text("back to the start").clicked() {
                play.rewind();
            }
            ui.add(
                egui::Slider::new(&mut play.time, 0.0..=entry.seconds)
                    .suffix(" s")
                    .fixed_decimals(3),
            );
            ui.label(
                egui::RichText::new(format!(
                    "frame {} of {}",
                    effects::frame_at(play.time),
                    entry.frames()
                ))
                .monospace(),
            );
        });
        ui.label(
            egui::RichText::new(format!(
                "{} of {} part(s) running",
                entry.active_at(play.time).len(),
                entry.parts.len()
            ))
            .weak(),
        );
    }

    /// The parts, with the ones running at the current time marked.
    ///
    /// ⛔ A part is a name, a table position and a duration — that is
    /// everything known about it. It is deliberately not shown beside an
    /// image, because which image a part draws is not decoded.
    fn part_table(ui: &mut egui::Ui, entry: &effects::Entry, time: f32) {
        ui.label(egui::RichText::new("parts").strong());
        egui::Grid::new("effect-parts")
            .num_columns(6)
            .striped(true)
            .show(ui, |ui| {
                for heading in ["", "part", "composed", "index", "frames", "seconds"] {
                    ui.label(egui::RichText::new(heading).weak().small());
                }
                ui.end_row();
                for part in &entry.parts {
                    let mark = if part.active_at(time) {
                        egui::RichText::new("●").color(ACTIVE)
                    } else {
                        egui::RichText::new("·").weak()
                    };
                    ui.label(mark);
                    ui.label(part.name.as_str()).on_hover_text(part.describe());
                    ui.label(egui::RichText::new(part.composed.as_str()).monospace());
                    ui.label(egui::RichText::new(part.index.to_string()).monospace());
                    ui.label(egui::RichText::new(part.frames.to_string()).monospace());
                    ui.label(egui::RichText::new(format!("{:.3}", part.seconds)).monospace());
                    ui.end_row();
                }
            });
    }

    /// The transform rows, folded away by default: one effect carries up to
    /// 315 of them, which would bury the parts above.
    fn row_table(ui: &mut egui::Ui, entry: &effects::Entry) {
        egui::CollapsingHeader::new(format!("transform rows ({})", entry.rows.len()))
            .default_open(false)
            .show(ui, |ui| {
                egui::Grid::new("effect-rows")
                    .num_columns(3)
                    .striped(true)
                    .show(ui, |ui| {
                        for row in &entry.rows {
                            ui.label(
                                egui::RichText::new(row.index.to_string())
                                    .monospace()
                                    .weak(),
                            );
                            ui.label(egui::RichText::new(row.describe()).monospace());
                            ui.label(
                                egui::RichText::new(format!("len {:.4}", row.magnitude()))
                                    .monospace()
                                    .weak(),
                            )
                            .on_hover_text("the row read as a vector");
                            ui.end_row();
                        }
                    });
            });
    }

    /// The effect system's image bank, as a strip under the effect.
    ///
    /// ⛔ **Nothing in this strip is paired with a part above, and the panel
    /// says so.** Which image a part draws is not decoded: six candidate
    /// fields have been refuted, so this is the bank as a whole, selected by
    /// the disc file it comes from and shown in catalog order. Ordering it by
    /// anything a part carries would invent a mapping.
    ///
    /// ⚠️ Unlike the texture grid this is not virtualised, and can stay that
    /// way only because the bank is one disc file — 219 images — where the
    /// grid spans 21,780 and would exhaust texture memory.
    fn effect_bank(&self, ctx: &egui::Context) {
        egui::TopBottomPanel::bottom("effect-bank").show(ctx, |ui| {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("effect image bank").strong());
                let source = self.effects.library.textures();
                ui.label(
                    egui::RichText::new(if source.is_empty() {
                        "effects.json names no image source".to_string()
                    } else {
                        format!("{} image(s) from {source}", self.effects.bank.len())
                    })
                    .weak(),
                );
                ui.separator();
                ui.label(
                    egui::RichText::new(
                        "which image a part draws is not decoded — nothing here \
                         is paired with a part",
                    )
                    .color(UNDECODED)
                    .small(),
                );
            });
            egui::ScrollArea::horizontal()
                .max_height(BANK_THUMB + PAD)
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        for &index in &self.effects.bank {
                            let Some(entry) = self.catalog.entries().get(index) else {
                                continue;
                            };
                            ui.add(
                                egui::Image::new(entry.uri())
                                    .fit_to_exact_size(egui::vec2(BANK_THUMB, BANK_THUMB))
                                    .maintain_aspect_ratio(true),
                            )
                            .on_hover_text(format!(
                                "{}\n{}",
                                entry.name,
                                entry.describe()
                            ));
                        }
                    });
                });
            ui.add_space(4.0);
        });
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
            root: None,
            catalog: catalog::Catalog::default(),
            search: String::new(),
            format: None,
            selected: None,
            mode: Mode::Effects,
            models: ModelPane::default(),
            effects: EffectPane::default(),
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
            root: None,
            catalog: catalog::Catalog::default(),
            search: String::new(),
            format: None,
            selected: None,
            mode: Mode::Effects,
            models: ModelPane::default(),
            effects: EffectPane::default(),
        };
        bare.open(std::env::temp_dir().join("dimentio-ui-absent"));
        assert!(bare.effects.library.problem().is_some());
        draw(&mut bare, &ctx);
    }
}
