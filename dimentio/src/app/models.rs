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
use crate::data::transport::Playback;
use crate::data::{self, mesh, morph};
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
    /// Which of the selection's clips the transport is on.
    pub(super) clip: usize,
    /// ⚠️ **Paused at the first frame by default**, which `Playback::default`
    /// is. A viewport that started animating on selection would never show the
    /// pose the geometry was authored in.
    pub(super) play: Playback,
    /// What the geometry is currently displaced to, so a re-pose only happens
    /// when it has to — posing walks every vertex of every weighted target.
    pub(super) posed: Option<Posed>,
}

/// One shape the user just showed or hid.
///
/// Collected while the menu is open and applied after it closes: the list is
/// drawn from the mesh, so it cannot be mutated while it is being read.
struct Toggle {
    index: usize,
    shown: bool,
}

/// A point in a clip: which one, and how far in.
#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) struct Posed {
    clip: usize,
    time: f32,
}

impl ModelPane {
    pub(super) fn load(root: &Path) -> Self {
        Self {
            library: data::ModelLibrary::load(root),
            whole_only: true,
            ..Default::default()
        }
    }

    /// How long the selected clip runs, or zero when there is nothing to play.
    ///
    /// ⚠️ Read from the geometry, not the manifest, for the same reason the
    /// sound pane reads the decoded file: the manifest records what the
    /// exporter meant to write, and the scrubber has to match what it wrote.
    fn span(&self) -> f32 {
        self.mesh
            .animation()
            .and_then(|animation| animation.clips().get(self.clip))
            .map_or(0.0, |clip| clip.seconds())
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
        ui.separator();
        self.shape_menu(ui);
        ui.label(
            egui::RichText::new("drag to orbit · scroll to zoom")
                .weak()
                .small(),
        );
    }

    /// How many shapes the selection was split into, and a checkbox each.
    ///
    /// ⚠️ **This is what turns a stray shape into a fact.** `e_lui_robo` holds
    /// 92 and one of them is a flat quad 130 units to the side; merged into one
    /// mesh it was reported as "fucked up verts", because nothing said it was a
    /// separate object and nothing could hide it (D236).
    fn shape_menu(&mut self, ui: &mut egui::Ui) {
        let total = self.models.mesh.shapes().len();
        if total == 0 {
            return;
        }
        let hidden = self.models.mesh.hidden_shapes();
        let label = if hidden == 0 {
            format!("{total} shape(s)")
        } else {
            format!("{total} shape(s), {hidden} hidden")
        };
        if total == 1 {
            ui.label(egui::RichText::new(label).weak().small());
            return;
        }

        let mut toggled: Vec<Toggle> = Vec::new();
        let mut all = None;
        ui.menu_button(label, |ui| {
            ui.label(
                egui::RichText::new(
                    "One shape per glTF primitive, as the file groups its faces. \
                     Which Maya shape name goes with which is not decoded.",
                )
                .weak()
                .small(),
            );
            ui.horizontal(|ui| {
                if ui.button("show all").clicked() {
                    all = Some(true);
                }
                if ui.button("hide all").clicked() {
                    all = Some(false);
                }
            });
            ui.separator();
            let step = ui.text_style_height(&egui::TextStyle::Body) + 6.0;
            let shapes: Vec<mesh::Shape> = self.models.mesh.shapes().to_vec();
            egui::ScrollArea::vertical().max_height(320.0).show_rows(
                ui,
                step,
                shapes.len(),
                |ui, range| {
                    for index in range {
                        let Some(shape) = shapes.get(index) else {
                            break;
                        };
                        let mut shown = shape.visible;
                        let name = format!("shape {index} · {} tris", shape.count);
                        if ui.checkbox(&mut shown, name).changed() {
                            toggled.push(Toggle { index, shown });
                        }
                    }
                },
            );
        });

        if let Some(shown) = all {
            if shown {
                self.models.mesh.show_all_shapes();
            } else {
                for index in 0..total {
                    self.models.mesh.set_shape_visible(index, false);
                }
            }
            self.models.stale = true;
        }
        for change in toggled {
            self.models
                .mesh
                .set_shape_visible(change.index, change.shown);
            self.models.stale = true;
        }
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
                asset.inline(ui, "shapes", &self.models.mesh.shapes().len().to_string());
                ui.separator();
                asset.inline(ui, "extent", &entry.extent());
                ui.separator();
                asset.inline(ui, "texture", painted.as_deref().unwrap_or("none"));
                ui.separator();
                asset.inline(ui, "clips", &Self::clip_count(&entry));
                if entry.animations_dropped > 0 {
                    ui.separator();
                    ui.label(
                        egui::RichText::new(format!(
                            "{} clip(s) not exported",
                            entry.animations_dropped
                        ))
                        .color(FRAGMENT),
                    )
                    .on_hover_text(Self::dropped_clips(&entry));
                }
                if entry.texture_guessed {
                    ui.separator();
                    ui.label(egui::RichText::new("texture is a guess").color(FRAGMENT))
                        .on_hover_text(
                            "This model has several shapes and each has its own                              image, but which image goes with which shape is not                              decoded. --guess-textures gave every shape image 0,                              which is wrong for most models.",
                        );
                }
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

    /// How many clips the manifest says are playable, out of how many the file
    /// holds. A model whose clips all decode to nothing says "none".
    fn clip_count(entry: &mesh::Entry) -> String {
        let held = entry.clips.len();
        if held == 0 {
            return "none".to_owned();
        }
        let longest = entry
            .clips
            .iter()
            .filter(|clip| clip.written)
            .map(|clip| clip.seconds)
            .fold(0.0f32, f32::max);
        format!(
            "{} of {held} playable, longest {longest:.2}s",
            entry.animations
        )
    }

    /// The clips that moved something but did not fit the exporter's budget,
    /// by name and size.
    ///
    /// ⚠️ Named, not counted. "12 clips not exported" gives nobody a way to
    /// find out which, and the manifest already carries them.
    fn dropped_clips(entry: &mesh::Entry) -> String {
        let mut said = String::from(
            "The exporter caps the morph targets one file may carry, because each \
             is a full set of per-vertex deltas. Left out of the .glb:\n",
        );
        let left: Vec<&morph::ClipEntry> = entry
            .clips
            .iter()
            .filter(|clip| clip.poses > 0 && !clip.written)
            .collect();
        for clip in left.iter().take(12) {
            said.push_str(&format!("\n  {} — {} poses", clip.name, clip.poses));
        }
        if left.len() > 12 {
            said.push_str(&format!("\n  ... and {} more", left.len() - 12));
        }
        said
    }

    /// Pick a clip, play it, and scrub through it.
    ///
    /// ⚠️ Shown only when the selection has one. 646 of 864 exported models
    /// carry no clip, and a transport over nothing reads as a viewer whose
    /// play button does not work.
    pub(super) fn model_transport(&mut self, ctx: &egui::Context) {
        if self.models.selected.is_none() || self.models.mesh.animation().is_none() {
            return;
        }
        egui::TopBottomPanel::bottom("model-animation").show(ctx, |ui| {
            ui.add_space(4.0);
            let targets = self
                .models
                .mesh
                .animation()
                .map_or(0, |animation| animation.targets());
            ui.horizontal_wrapped(|ui| {
                Self::clip_picker(ui, &mut self.models);
                ui.separator();
                Self::clip_transport(ui, &mut self.models);
                ui.separator();
                ui.label(
                    egui::RichText::new(format!("{targets} morph target(s)"))
                        .weak()
                        .small(),
                )
                .on_hover_text(
                    "Every clip in a file shares one target list, and each target \
                     is a position delta for every vertex.",
                );
            });
            ui.add_space(4.0);
        });
    }

    /// The clips this model carries, by name.
    ///
    /// Changing it rewinds: a new clip has its own length, and the old
    /// position may be past the end of it.
    fn clip_picker(ui: &mut egui::Ui, pane: &mut ModelPane) {
        let Some(animation) = pane.mesh.animation() else {
            return;
        };
        let clips = animation.clips();
        let chosen = pane.clip.min(clips.len().saturating_sub(1));
        let label = clips
            .get(chosen)
            .map_or_else(|| "none".to_owned(), |clip| clip.describe());
        let mut picked = chosen;
        egui::ComboBox::from_id_salt("model-clip")
            .selected_text(label)
            .width(240.0)
            .show_ui(ui, |ui| {
                for (index, clip) in clips.iter().enumerate() {
                    ui.selectable_value(&mut picked, index, clip.describe());
                }
            });
        ui.label(
            egui::RichText::new(format!("{} clip(s)", clips.len()))
                .weak()
                .small(),
        );
        if picked != pane.clip {
            pane.clip = picked;
            pane.play.rewind();
        }
    }

    /// Play, pause, rewind and scrub — the timeline the effect pane uses, over
    /// a morph clip instead of an effect.
    fn clip_transport(ui: &mut egui::Ui, pane: &mut ModelPane) {
        let span = pane.span();
        if span <= 0.0 {
            // A clip of one pose is a still. There is nothing to scrub, and a
            // slider over an empty range cannot be moved.
            pane.play.playing = false;
            ui.label(egui::RichText::new("a single pose — nothing to play").weak());
            return;
        }
        let symbol = if pane.play.playing { "⏸" } else { "▶" };
        if ui.button(symbol).on_hover_text("play / pause").clicked() {
            pane.play.playing = !pane.play.playing;
        }
        if ui.button("⏮").on_hover_text("back to the start").clicked() {
            pane.play.rewind();
        }
        ui.add(
            egui::Slider::new(&mut pane.play.time, 0.0..=span)
                .suffix(" s")
                .fixed_decimals(2),
        );
        ui.label(egui::RichText::new(format!("of {span:.2}s")).monospace());
    }

    /// Follow the clip, and keep frames coming while it moves.
    ///
    /// ⚠️ `request_repaint` is what makes it animate at all. egui redraws in
    /// response to input and nothing else, so without it the model would step
    /// one frame per mouse movement.
    pub(super) fn run_model_clock(&mut self, ctx: &egui::Context) {
        if !self.models.play.playing {
            return;
        }
        let span = self.models.span();
        let dt = ctx.input(|input| input.stable_dt);
        self.models.play.advance(dt, span);
        ctx.request_repaint();
    }

    /// Displace the geometry to wherever the transport is, if it has moved.
    ///
    /// A model with no animation is left exactly as it was loaded — which is
    /// what makes the untouched case cost nothing and look unchanged.
    pub(super) fn hold_pose(&mut self) {
        if self.models.mesh.animation().is_none() {
            return;
        }
        let wanted = Posed {
            clip: self.models.clip,
            time: self.models.play.time,
        };
        if self.models.posed == Some(wanted) {
            return;
        }
        self.models.mesh.pose(wanted.clip, wanted.time);
        self.models.posed = Some(wanted);
        self.models.stale = true;
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
        // ⚠️ Back to clip 0, paused at its first frame. Carrying the old
        // position across would drop a new model into the middle of a clip it
        // may not even have.
        self.models.clip = 0;
        self.models.play = Playback::default();
        self.models.posed = None;
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
        self.hold_pose();
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
