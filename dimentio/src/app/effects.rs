//! The effect table, its viewport, its timeline, and the image bank under it.
//! **This is the UI layer** — the manifest it draws is read by
//! `crate::data::effects` and the pixels come from `crate::render`.

use std::path::Path;

use eframe::egui;

use super::clipboard::{copy_button, Asset};
use super::{Viewer, PAD};
use crate::data::{self, effects, texture};
use crate::render;

/// Thumbnail edge for the effect image bank, in points. Smaller than the
/// texture grid's: the strip is one row deep and shares the window with the
/// effect it sits under.
const BANK_THUMB: f32 = 64.0;

/// Carries the standing warning that a part's image is not decoded. The same
/// amber the model pane uses for a fragment: both say "this is less than it
/// looks like".
const UNDECODED: egui::Color32 = egui::Color32::from_rgb(220, 170, 90);

/// Share of the detail panel the viewport takes, as a column count. Two
/// columns: the effect on the left, the numbers behind it on the right.
const COLUMNS: usize = 2;

/// An image the user chose to preview on a part.
///
/// ⛔ Both ends of this are choices made in the window. Nothing in the export
/// says which image a part draws, so nothing may fill either field in from a
/// field a part carries — see `crate::render::effect::Manual`.
struct Chosen {
    /// Position in the texture catalog, so the bank can mark the thumbnail.
    catalog: usize,
    name: String,
    image: texture::Texture,
}

/// The effect viewport's own state: where the camera is, the frame it drew
/// last, and the image a user asked to see on a part.
#[derive(Default)]
pub(super) struct Stage {
    view: render::View,
    /// The last rasterised frame, uploaded once and replaced in place.
    frame: Option<egui::TextureHandle>,
    /// Which part `chosen` is drawn on. Zero until someone moves it.
    part: usize,
    chosen: Option<Chosen>,
    /// The decoded image for each part of the selected effect, resolved once
    /// when the selection changes rather than per frame — decoding a PNG on
    /// every repaint would stall the timeline it exists to animate.
    art: Vec<Option<texture::Texture>>,
    /// Why the last image pick produced nothing, so a failed decode says so
    /// rather than looking like a viewport that ignores clicks.
    note: Option<String>,
}

impl Stage {
    /// Whether a frame has been rasterised and uploaded. The headless layout
    /// test is the only evidence this window draws at all, and it cannot see
    /// pixels — only that the viewport got as far as producing some.
    #[cfg(test)]
    pub(super) fn drawn(&self) -> bool {
        self.frame.is_some()
    }

    /// The image being previewed, and the part it is on.
    #[cfg(test)]
    pub(super) fn previewing(&self) -> Option<(&str, usize)> {
        self.chosen
            .as_ref()
            .map(|chosen| (chosen.name.as_str(), self.part))
    }

    /// What the renderer paints on each part: the decoded images (D258), with
    /// the user's manual pick overriding one of them.
    ///
    /// ⚠️ The override is applied to a **copy**, so moving the preview from one
    /// part to another does not permanently lose the decoded image underneath.
    fn art(&self) -> Vec<Option<texture::Texture>> {
        let mut images = self.art.clone();
        if let Some(chosen) = &self.chosen {
            if self.part >= images.len() {
                images.resize(self.part + 1, None);
            }
            images[self.part] = Some(chosen.image.clone());
        }
        images
    }
}

/// Everything the effect mode owns.
///
/// ⛔ `bank` is the effect system's whole image bank and is never indexed by
/// anything to do with a part. Which image a part draws is not decoded; see
/// `crate::data::effects::bank`.
#[derive(Default)]
pub(super) struct EffectPane {
    pub(super) library: data::EffectLibrary,
    pub(super) search: String,
    pub(super) selected: Option<usize>,
    pub(super) play: effects::Playback,
    /// Indices into the texture catalog of the effect system's images.
    /// Resolved once when a folder is opened: the filter is by disc file, and
    /// neither the catalog nor that file changes while the folder is open.
    pub(super) bank: Vec<usize>,
    pub(super) stage: Stage,
}

impl EffectPane {
    pub(super) fn load(root: &Path, catalog: &data::Catalog) -> Self {
        let library = data::EffectLibrary::load(root);
        let bank = effects::bank(catalog.entries(), library.textures());
        Self {
            library,
            bank,
            ..Default::default()
        }
    }
}

impl Viewer {
    pub(super) fn effect_controls(&mut self, ui: &mut egui::Ui) {
        let shown = self.effects.library.matching(&self.effects.search).len();
        ui.label(format!(
            "{shown} of {} effect(s)",
            self.effects.library.len()
        ));
        ui.separator();
        egui::ComboBox::from_label("background")
            .selected_text(self.effects.stage.view.background.label())
            .show_ui(ui, |ui| {
                for background in render::BACKGROUNDS {
                    ui.selectable_value(
                        &mut self.effects.stage.view.background,
                        background,
                        background.label(),
                    );
                }
            });
        if ui.button("fit").clicked() {
            self.fit_effect();
        }
        ui.separator();
        ui.label(
            egui::RichText::new("drag to orbit · scroll to zoom · durations are frames at 60Hz")
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
    pub(super) fn run_clock(&mut self, ctx: &egui::Context) {
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
    pub(super) fn effect_list(&mut self, ctx: &egui::Context) {
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
                        let asset = Asset::named(&entry.name);
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
                    self.select_effect(index);
                }
            });
    }

    /// Pick an effect and put the timeline back at its start: a different
    /// effect has a different length, and the old position may be past its end.
    ///
    /// The preview part goes back to the first one for the same reason — the
    /// new effect may have fewer parts than the old one.
    pub(super) fn select_effect(&mut self, index: usize) {
        self.effects.selected = Some(index);
        self.effects.play.rewind();
        self.effects.stage.part = 0;
        self.fit_effect();
    }

    /// Frame the whole layout, running or not.
    ///
    /// ⚠️ Done on a new selection and on the button, and nowhere else.
    /// Refitting every frame would fight the user's own orbit, and refitting as
    /// parts start and stop would jerk the camera each time the timeline
    /// crossed a duration.
    fn fit_effect(&mut self) {
        let Some(entry) = self
            .effects
            .selected
            .and_then(|index| self.effects.library.entries().get(index))
        else {
            return;
        };
        self.effects.stage.view.camera = render::Camera::fit(render::effect::bounds(entry));
        self.effects.stage.art = Self::resolve_art(
            entry,
            self.catalog.entries(),
            self.effects.library.textures(),
        );
    }

    /// Decode the image each part of `entry` draws.
    ///
    /// ⚠️ A picture that cannot be read leaves its part unpainted rather than
    /// failing the whole effect — one missing PNG in the export should cost one
    /// quad's texture, not the viewport.
    fn resolve_art(
        entry: &effects::Entry,
        catalog: &[data::catalog::Entry],
        source: &str,
    ) -> Vec<Option<texture::Texture>> {
        entry
            .parts
            .iter()
            .map(|part| {
                let picture = part.pictures.first()?;
                let at = effects::image_at(catalog, source, picture.image)?;
                let entry = catalog.get(at)?;
                let raw = std::fs::read(&entry.path).ok()?;
                texture::Texture::decode(&raw).ok()
            })
            .collect()
    }

    pub(super) fn effect_detail(&mut self, ui: &mut egui::Ui) {
        let Some(index) = self.effects.selected else {
            Self::message(ui, "Pick an effect on the left.");
            return;
        };
        let Some(entry) = self.effects.library.entries().get(index) else {
            Self::message(ui, "That effect is no longer in the manifest.");
            return;
        };

        let asset = Asset::named(&entry.name);
        ui.add_space(4.0);
        ui.horizontal(|ui| {
            ui.heading(&entry.name);
            copy_button(ui, "name", &entry.copy_text());
        });
        ui.add_space(4.0);
        ui.horizontal_wrapped(|ui| {
            asset.inline(ui, "index", &entry.index.to_string());
            ui.separator();
            asset.inline(ui, "parts", &entry.parts.len().to_string());
            ui.separator();
            asset.inline(ui, "rows", &entry.rows.len().to_string());
            ui.separator();
            asset.inline(
                ui,
                "duration",
                &format!("{:.3}s · {} frames", entry.seconds, entry.frames()),
            );
        });
        ui.separator();
        Self::timeline(ui, entry, &mut self.effects.play);
        ui.separator();

        let time = self.effects.play.time;
        let stage = &mut self.effects.stage;
        ui.columns(COLUMNS, |columns| {
            Self::effect_stage(&mut columns[0], entry, stage, time);
            egui::ScrollArea::vertical().show(&mut columns[1], |ui| {
                Self::part_table(ui, entry, time);
                ui.add_space(12.0);
                Self::row_table(ui, entry);
            });
        });
    }

    /// The viewport: one camera-facing quad per running part, drawn by the same
    /// software rasteriser the model tab uses.
    ///
    /// ⚠️ Rasterised on every frame, with no stale flag. The timeline moves the
    /// geometry, so a frame that was skipped because nothing was clicked would
    /// freeze the animation this panel exists to show.
    fn effect_stage(ui: &mut egui::Ui, entry: &effects::Entry, stage: &mut Stage, time: f32) {
        Self::manual_row(ui, entry, stage);
        let area = ui.available_size();
        if area.x < 1.0 || area.y < 1.0 {
            return;
        }
        let (rect, response) = ui.allocate_exact_size(area, egui::Sense::click_and_drag());
        Self::steer_camera(ui, &response, &mut stage.view.camera);

        let size = Self::frame_size(area);
        let images = stage.art();
        let quads = render::effect::quads(
            entry,
            time,
            &stage.view.camera,
            Some(render::effect::Art { images: &images }),
        );
        let pieces: Vec<render::Piece<'_>> = quads
            .iter()
            .map(|quad| render::Piece {
                mesh: &quad.mesh,
                flat: quad.colour,
            })
            .collect();
        let drawn = render::scene(&pieces, &stage.view, size);
        Self::upload(ui, &mut stage.frame, "effect-stage", &drawn);

        if let Some(handle) = &stage.frame {
            ui.painter().image(
                handle.id(),
                rect,
                egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                egui::Color32::WHITE,
            );
        }

        // Names the shapes on screen. A quad carries the part it came from, and
        // an unlabelled coloured square says nothing about which row it is.
        let running: Vec<&str> = quads
            .iter()
            .filter_map(|quad| entry.parts.get(quad.part))
            .map(|part| part.composed.as_str())
            .collect();
        response.on_hover_text(if running.is_empty() {
            "no part is running at this point in the timeline".to_string()
        } else {
            format!("running: {}", running.join(", "))
        });
    }

    /// The manual image chooser, and the standing statement that it is manual.
    ///
    /// ⛔ The label below is not decoration. Nothing in the export pairs a part
    /// with an image, and a viewport that showed one beside the other without
    /// saying so would look exactly like a decoded fact.
    fn manual_row(ui: &mut egui::Ui, entry: &effects::Entry, stage: &mut Stage) {
        ui.horizontal(|ui| {
            ui.label(
                egui::RichText::new("preview an image on part")
                    .weak()
                    .small(),
            );
            let chosen_part = entry
                .parts
                .get(stage.part)
                .map_or_else(|| "—".to_string(), |part| part.composed.clone());
            egui::ComboBox::from_id_salt("effect-manual-part")
                .selected_text(chosen_part)
                .show_ui(ui, |ui| {
                    for (index, part) in entry.parts.iter().enumerate() {
                        ui.selectable_value(&mut stage.part, index, part.composed.as_str());
                    }
                });
            match &stage.chosen {
                Some(chosen) => {
                    ui.label(egui::RichText::new(chosen.name.as_str()).monospace());
                    if ui.button("clear").clicked() {
                        stage.chosen = None;
                    }
                }
                None => {
                    ui.label(
                        egui::RichText::new("none — click one in the bank below")
                            .weak()
                            .small(),
                    );
                }
            }
        });
        ui.label(
            egui::RichText::new(
                "no image is bound to a part in the data; this is a manual preview, \
                 not a decoded pairing",
            )
            .color(UNDECODED)
            .small(),
        );
        if let Some(note) = &stage.note {
            ui.label(egui::RichText::new(note.as_str()).color(UNDECODED).small());
        }
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
    /// The mark takes the colour that part's quad is drawn in, so a row and a
    /// shape in the viewport can be matched up by eye.
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
                for (index, part) in entry.parts.iter().enumerate() {
                    let mark = if part.active_at(time) {
                        let drawn = render::effect::colour(index);
                        egui::RichText::new("●")
                            .color(egui::Color32::from_rgb(drawn.r, drawn.g, drawn.b))
                    } else {
                        egui::RichText::new("·").weak()
                    };
                    ui.label(mark);
                    ui.label(part.name.as_str()).on_hover_text(part.describe());
                    let composed = part.copy_text();
                    Asset::named(&composed).value(ui, "part name", &composed);
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
    /// Clicking one puts it on the part the viewport is previewing. That is a
    /// choice the user made and the labels say so; it is not a binding.
    ///
    /// ⚠️ Unlike the texture grid this is not virtualised, and can stay that
    /// way only because the bank is one disc file — 219 images — where the
    /// grid spans 21,780 and would exhaust texture memory.
    pub(super) fn effect_bank(&mut self, ctx: &egui::Context) {
        let mut picked = None;
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
                         is paired with a part. Click one to preview it on the \
                         part you chose above.",
                    )
                    .color(UNDECODED)
                    .small(),
                );
            });
            let marked = self
                .effects
                .stage
                .chosen
                .as_ref()
                .map(|chosen| chosen.catalog);
            egui::ScrollArea::horizontal()
                .max_height(BANK_THUMB + PAD)
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        for &index in &self.effects.bank {
                            let Some(entry) = self.catalog.entries().get(index) else {
                                continue;
                            };
                            let thumb = egui::ImageButton::new(
                                egui::Image::new(entry.uri())
                                    .fit_to_exact_size(egui::vec2(BANK_THUMB, BANK_THUMB))
                                    .maintain_aspect_ratio(true),
                            )
                            .selected(marked == Some(index));
                            let shown = ui.add(thumb);
                            let source = entry.source_text();
                            let asset = Asset::sourced(&entry.name, source.as_deref());
                            asset.menu(&shown);
                            if shown
                                .on_hover_text(format!(
                                    "{}\n{}\n{}",
                                    entry.name,
                                    entry.describe(),
                                    asset.hint()
                                ))
                                .clicked()
                            {
                                picked = Some(index);
                            }
                        }
                    });
                });
            ui.add_space(4.0);
        });
        if let Some(index) = picked {
            self.choose_image(index);
        }
    }

    /// Decode a bank image so the viewport can paint it on a part.
    ///
    /// ⛔ Which image and which part are both the user's choice. Nothing here
    /// may derive either from the effect data.
    pub(super) fn choose_image(&mut self, index: usize) {
        let Some(entry) = self.catalog.entries().get(index) else {
            return;
        };
        self.effects.stage.note = None;
        let decoded = std::fs::read(&entry.path)
            .map_err(|why| format!("{} could not be read: {why}", entry.path.display()))
            .and_then(|raw| texture::Texture::decode(&raw));
        match decoded {
            Ok(image) => {
                self.effects.stage.chosen = Some(Chosen {
                    catalog: index,
                    name: entry.name.clone(),
                    image,
                });
            }
            Err(why) => {
                self.effects.stage.chosen = None;
                self.effects.stage.note = Some(why);
            }
        }
    }
}
