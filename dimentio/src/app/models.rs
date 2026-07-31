//! The model viewport: the model list, the facts strip, and the frame the
//! software rasteriser draws into.
//!
//! ⚠️ The viewport draws on the CPU, not through `eframe`'s GPU surface. That
//! is what lets `crate::render` be tested with no window and no driver, which
//! is the only evidence this program has that it draws the right thing.

use std::path::Path;

use eframe::egui;

use super::clipboard::Asset;
use super::Viewer;
use crate::data::{self, mesh};
use crate::render;

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
    /// Hide models whose faces reach almost none of their vertices.
    ///
    /// ⚠️ **On by default**, because 732 of 864 exported models are fragments
    /// and a fragment does not look broken — it looks like a model with one
    /// corner torn into the middle, which reads as a renderer fault rather
    /// than incomplete data (D211). `e_genjin_b` was reported that way: it is
    /// recognisably a Cragnon, at 7.6% coverage.
    pub(super) whole_only: bool,
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
            whole_only: true,
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

                ui.horizontal(|ui| {
                    ui.checkbox(&mut self.models.whole_only, "whole models only")
                        .on_hover_text(
                            "A fragment is one shape record out of a file that \
                             holds many. It renders as a recognisable model with \
                             a corner torn into the middle, which looks like a \
                             rendering fault rather than incomplete data.",
                        );
                });

                let visible = self
                    .models
                    .library
                    .filtered(&self.models.search, self.models.whole_only);
                ui.label(
                    egui::RichText::new(format!(
                        "{} of {} model(s){}",
                        visible.len(),
                        self.models.library.len(),
                        if self.models.whole_only {
                            format!(", {} hidden as fragments", {
                                self.models.library.len() - self.models.library.whole()
                            })
                        } else {
                            String::new()
                        }
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
                        let source = entry.source_text();
                        let asset = Asset::sourced(&entry.name, source.as_deref());
                        asset.menu(&row);
                        if row
                            .on_hover_text(format!("{}\n{}", entry.describe(), asset.hint()))
                            .clicked()
                        {
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
        // What the mesh file actually carried, as opposed to what the manifest
        // said about it: an untextured model and one whose image failed to
        // decode are indistinguishable on screen, and both look like a broken
        // renderer.
        let painted = self
            .models
            .mesh
            .surface()
            .map(|surface| format!("{}x{}", surface.texture.width(), surface.texture.height()));
        let source = entry.source_text();
        let asset = Asset::sourced(&entry.name, source.as_deref());
        egui::TopBottomPanel::bottom("model-facts").show(ctx, |ui| {
            ui.add_space(4.0);
            ui.horizontal_wrapped(|ui| {
                asset.inline(ui, "name", &entry.copy_text());
                ui.separator();
                asset.inline(ui, "source", &entry.source);
                ui.separator();
                asset.inline(ui, "shape", &entry.shape);
                ui.separator();
                asset.inline(ui, "verts", &entry.positions.to_string());
                ui.separator();
                asset.inline(ui, "faces", &entry.faces.to_string());
                ui.separator();
                asset.inline(ui, "tris", &entry.triangles.to_string());
                ui.separator();
                asset.inline(ui, "extent", &entry.extent());
                ui.separator();
                asset.inline(ui, "texture", painted.as_deref().unwrap_or("none"));
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
    pub(super) fn select_model(&mut self, index: usize) {
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
        let size = Self::frame_size(area);
        if size != self.models.size {
            self.models.size = size;
            self.models.stale = true;
        }

        if self.models.stale || self.models.frame.is_none() {
            let drawn = render::render(&self.models.mesh, &self.models.view, size);
            Self::upload(ui, &mut self.models.frame, "viewport", &drawn);
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
        if Self::steer_camera(ui, response, &mut self.models.view.camera) {
            self.models.stale = true;
        }
    }
}
