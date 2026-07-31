//! The texture browser: the search strip, the thumbnail grid, and the panel
//! that opens beside a chosen image.

use eframe::egui;

use super::{Viewer, PAD};

/// Thumbnail edge, in points. Small enough that a few hundred fit on screen.
const THUMB: f32 = 96.0;

impl Viewer {
    pub(super) fn texture_controls(&mut self, ui: &mut egui::Ui) {
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

    pub(super) fn detail_panel(&mut self, ctx: &egui::Context) {
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

    /// ⚠️ Rows are virtualised on purpose. The disc holds 21,780 textures, and
    /// egui uploads every image it draws to the GPU and keeps it. Drawing them
    /// all would exhaust texture memory within a few seconds of scrolling;
    /// `show_rows` only calls back for the rows actually on screen.
    pub(super) fn grid(&mut self, ui: &mut egui::Ui) {
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
