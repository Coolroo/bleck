//! The model viewport: the model list, the facts strip, and the frame the
//! software rasteriser draws into.
//!
//! ⚠️ The viewport draws on the CPU, not through `eframe`'s GPU surface. That
//! is what lets `crate::render` be tested with no window and no driver, which
//! is the only evidence this program has that it draws the right thing.

use std::path::Path;

use eframe::egui;

use super::Viewer;
use crate::data::{self, mesh};
use crate::render;

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

/// Colour of the standing warning that a model is one shape out of a file that
/// holds many. The same amber the effect pane uses for an undecoded part: both
/// say "this is less than it looks like".
const FRAGMENT: egui::Color32 = egui::Color32::from_rgb(220, 170, 90);

/// Everything the model mode owns. Grouped so the texture fields stay legible
/// beside it, and so one `stale` flag decides when to rasterise.
#[derive(Default)]
pub(super) struct ModelPane {
    pub(super) library: data::ModelLibrary,
    pub(super) search: String,
    pub(super) selected: Option<usize>,
    /// The selected model's geometry. Empty until something is picked, and
    /// empty again if the file behind a selection could not be read.
    pub(super) mesh: mesh::Mesh,
    /// Why the selected model has no geometry, as opposed to the library
    /// having none.
    pub(super) problem: Option<mesh::Problem>,
    pub(super) view: render::View,
    /// The last rasterised frame, uploaded once and replaced in place. A new
    /// handle per frame would leak a GPU texture per frame.
    pub(super) frame: Option<egui::TextureHandle>,
    pub(super) size: render::Size,
    /// Set by anything that changes what the frame should look like. ⚠️ Without
    /// it the rasteriser runs every frame, whether or not anything moved.
    pub(super) stale: bool,
}

impl ModelPane {
    pub(super) fn load(root: &Path) -> Self {
        Self {
            library: data::ModelLibrary::load(root),
            ..Default::default()
        }
    }
}

impl Viewer {
    pub(super) fn model_controls(&mut self, ui: &mut egui::Ui) {
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

    /// The models to choose from, searchable. Rows are virtualised for the
    /// same reason the texture grid is: `/a` holds 1,687 model files, and a
    /// widget per row is a widget per row whether or not it is on screen.
    pub(super) fn model_list(&mut self, ctx: &egui::Context) {
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
    pub(super) fn model_facts(&mut self, ctx: &egui::Context) {
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
                        .color(FRAGMENT),
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

    pub(super) fn viewport(&mut self, ui: &mut egui::Ui) {
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
