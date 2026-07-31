//! The effect table, its timeline, and the image bank under it. **This is the
//! UI layer** — the manifest it draws is read by `crate::data::effects`.

use std::path::Path;

use eframe::egui;

use super::{Viewer, PAD};
use crate::data::{self, effects};

/// Thumbnail edge for the effect image bank, in points. Smaller than the
/// texture grid's: the strip is one row deep and shares the window with the
/// effect it sits under.
const BANK_THUMB: f32 = 64.0;

/// Marks a part that is running at the timeline's current position.
const ACTIVE: egui::Color32 = egui::Color32::from_rgb(120, 200, 120);

/// Carries the standing warning that a part's image is not decoded. The same
/// amber the model pane uses for a fragment: both say "this is less than it
/// looks like".
const UNDECODED: egui::Color32 = egui::Color32::from_rgb(220, 170, 90);

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
    pub(super) fn select_effect(&mut self, index: usize) {
        self.effects.selected = Some(index);
        self.effects.play.rewind();
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
    pub(super) fn effect_bank(&self, ctx: &egui::Context) {
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
