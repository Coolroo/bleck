//! Copying an asset's name to the clipboard, and saying that it happened.
//!
//! One idiom for all four modes, so a row copies the same way whichever list
//! it is in. `Asset` is what a panel reaches for: it carries the two strings
//! an asset offers — its name, and the disc file behind it — and draws the
//! button, the menu and the fact rows that put either one on the clipboard.
//!
//! ⛔ **Nothing here decides what a copy says.** The strings come from
//! `copy_text` and `source_text` on each kind of entry in `crate::data`, which
//! is where they can be tested with no window at all.

use eframe::egui;

/// The glyph on every copy button.
///
/// ⚠️ A character the bundled fonts do not carry draws as a replacement box,
/// which reads as a broken button. `the_copy_glyph_is_in_the_bundled_fonts`
/// is what checks it, because nothing here can look at the window.
const COPY_GLYPH: &str = "📋";

/// How long the copied-note stays in the top bar, in seconds.
const NOTE_SECONDS: f64 = 2.0;

/// Colour of the copied-note. Green, where the panes use amber for a standing
/// warning: this one says something worked.
const NOTE: egui::Color32 = egui::Color32::from_rgb(120, 200, 140);

/// What the last copy put on the clipboard, and when.
///
/// ⚠️ Held in egui's own memory rather than on `Viewer`. Fact rows are drawn
/// by functions that hold no `&mut self`, so a field on the window could not
/// be written from where a copy actually happens.
#[derive(Clone)]
struct Copied {
    what: String,
    text: String,
    at: f64,
}

/// Where the copied-note lives in egui's memory. One slot: the note says what
/// went to the clipboard last, and there is only ever one clipboard.
fn note_id() -> egui::Id {
    egui::Id::new("dimentio-copied")
}

/// Put `text` on the clipboard, and record it so the top bar can say so.
///
/// ⚠️ `Context::copy_text` hands the string to whatever is hosting the window,
/// and that hand-off is the last thing this program can observe. Nothing here
/// reads back an OS clipboard, so the note is the only feedback there is.
fn copy(ui: &egui::Ui, what: &str, text: &str) {
    ui.ctx().copy_text(text.to_owned());
    let at = ui.input(|input| input.time);
    ui.ctx().data_mut(|data| {
        data.insert_temp(
            note_id(),
            Copied {
                what: what.to_owned(),
                text: text.to_owned(),
                at,
            },
        );
    });
}

/// Seconds a note made at `at` still has to run at `now`.
///
/// Separate from the drawing because a note that outstays its welcome, or
/// vanishes before it is read, is invisible to anything that can only lay
/// panels out.
fn note_left(at: f64, now: f64) -> f64 {
    NOTE_SECONDS - (now - at)
}

/// The copy that just happened, for as long as it is worth saying so.
///
/// ⚠️ Asks for a repaint at the moment it expires. egui redraws in response to
/// input and nothing else, so without it the note would stay on screen until
/// the pointer moved.
pub(super) fn copy_note(ui: &mut egui::Ui) {
    let Some(note) = ui.ctx().data(|data| data.get_temp::<Copied>(note_id())) else {
        return;
    };
    let left = note_left(note.at, ui.input(|input| input.time));
    if left <= 0.0 {
        return;
    }
    ui.label(
        egui::RichText::new(format!("{COPY_GLYPH} copied {}", note.what))
            .color(NOTE)
            .small(),
    )
    .on_hover_text(note.text);
    ui.ctx()
        .request_repaint_after(std::time::Duration::from_secs_f64(left));
}

/// A button that copies `text`. The visible half of the affordance: a
/// right-click menu cannot be seen until it is tried.
pub(super) fn copy_button(ui: &mut egui::Ui, what: &str, text: &str) {
    let pressed = ui.add(
        egui::Button::new(egui::RichText::new(COPY_GLYPH).small())
            .frame(false)
            .small(),
    );
    if pressed.clicked() {
        copy(ui, what, text);
    }
    pressed.on_hover_text(format!("copy the {what}"));
}

/// What an asset offers to the clipboard: what it is called, and the disc file
/// it came from.
#[derive(Clone, Copy)]
pub(super) struct Asset<'a> {
    name: &'a str,
    source: Option<&'a str>,
}

impl<'a> Asset<'a> {
    /// An asset with no disc file behind it.
    pub(super) fn named(name: &'a str) -> Self {
        Self { name, source: None }
    }

    /// ⚠️ An empty source is dropped rather than offered. A "Copy source path"
    /// that put nothing on the clipboard reads as a copy that failed.
    pub(super) fn sourced(name: &'a str, source: Option<&'a str>) -> Self {
        Self {
            name,
            source: source.filter(|source| !source.is_empty()),
        }
    }

    /// What a hover says a right-click will do. Said out loud because a menu
    /// that is never opened may as well not exist.
    pub(super) fn hint(self) -> &'static str {
        match self.source {
            Some(_) => "right-click to copy the name or the disc path",
            None => "right-click to copy the name",
        }
    }

    /// Attach the copy menu to whatever was just drawn.
    ///
    /// ⚠️ The response must sense clicks. egui reports a secondary click only
    /// on a widget that senses one, so a plain label gets no menu at all.
    pub(super) fn menu(self, response: &egui::Response) {
        response.context_menu(|ui| {
            if ui.button(format!("{COPY_GLYPH} Copy name")).clicked() {
                copy(ui, "name", self.name);
                ui.close_menu();
            }
            if let Some(source) = self.source {
                if ui
                    .button(format!("{COPY_GLYPH} Copy source path"))
                    .clicked()
                {
                    copy(ui, "source path", source);
                    ui.close_menu();
                }
            }
        });
    }

    /// A value that copies on click, with a button and the menu beside it.
    ///
    /// ⚠️ Wrapped in a `horizontal` so it counts as one cell. Two widgets laid
    /// straight into a `Grid` would take two columns and stagger every row
    /// after it.
    pub(super) fn value(self, ui: &mut egui::Ui, what: &str, value: &str) {
        ui.horizontal(|ui| {
            let shown =
                ui.add(egui::Button::new(egui::RichText::new(value).monospace()).frame(false));
            if shown.clicked() {
                copy(ui, what, value);
            }
            self.menu(&shown);
            shown.on_hover_text(format!("click to copy · {}", self.hint()));
            copy_button(ui, what, value);
        });
    }

    /// A key and its value, side by side.
    pub(super) fn inline(self, ui: &mut egui::Ui, key: &str, value: &str) {
        ui.label(egui::RichText::new(key).weak());
        self.value(ui, key, value);
    }

    /// The same pair with `end_row`, which a horizontal layout must not have:
    /// it would wrap the strip onto a second line instead of ending a grid row.
    pub(super) fn row(self, ui: &mut egui::Ui, key: &str, value: &str) {
        self.inline(ui, key, value);
        ui.end_row();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// ⛔ **The clipboard itself is not checked here, and cannot be.**
    /// `Context::copy_text` hands the string to whatever is hosting the
    /// window, and no test on this machine can read an OS clipboard. What is
    /// checked is the last thing this program can see: the string reaching
    /// egui's own platform output, and the note the top bar draws from.
    #[test]
    fn a_copy_reaches_eguis_platform_output_and_leaves_a_note() {
        let ctx = egui::Context::default();
        let input = egui::RawInput {
            time: Some(4.0),
            ..Default::default()
        };
        let output = ctx.run(input, |ctx| {
            egui::CentralPanel::default().show(ctx, |ui| {
                copy(ui, "name", "files/eff/effdata.tpl#0");
            });
        });
        assert_eq!(
            output.platform_output.copied_text,
            "files/eff/effdata.tpl#0"
        );

        let note = ctx
            .data(|data| data.get_temp::<Copied>(note_id()))
            .expect("a note was left");
        assert_eq!(note.what, "name");
        assert_eq!(note.text, "files/eff/effdata.tpl#0");
        assert_eq!(note.at, 4.0);
    }

    /// The note has to outlast a glance and then go. One that never expired
    /// would claim the last copy was the current one for the rest of the
    /// session.
    #[test]
    fn the_note_fades_rather_than_staying_on_screen() {
        assert!(note_left(4.0, 4.0) > 0.0, "just copied");
        assert!(note_left(4.0, 4.0 + NOTE_SECONDS / 2.0) > 0.0, "still up");
        assert!(note_left(4.0, 4.0 + NOTE_SECONDS) <= 0.0, "its time is up");
        assert!(note_left(4.0, 400.0) <= 0.0, "and stays gone");
    }

    /// ⚠️ A glyph the bundled fonts do not carry draws as a replacement box.
    /// The button is the *visible* half of this affordance — a right-click menu
    /// cannot be seen until it is tried — so a box is the difference between
    /// "click here" and "something is broken", and nothing on this machine can
    /// look at the window to tell.
    #[test]
    fn the_copy_glyph_is_in_the_bundled_fonts() {
        let ctx = egui::Context::default();
        // The font set is built on the first frame; asking before one has been
        // run reports nothing at all.
        let _ = ctx.run(egui::RawInput::default(), |_| {});
        assert!(
            ctx.fonts(|fonts| fonts.has_glyphs(&egui::FontId::default(), COPY_GLYPH)),
            "the copy button would draw as a replacement box"
        );
    }

    /// ⚠️ An empty source is dropped rather than offered. A "Copy source path"
    /// that put nothing on the clipboard reads as a copy that failed.
    #[test]
    fn an_asset_with_no_disc_file_offers_only_its_name() {
        assert!(Asset::sourced("e_kuribo", Some("")).source.is_none());
        assert!(Asset::sourced("e_kuribo", None).source.is_none());
        assert_eq!(
            Asset::sourced("e_kuribo", Some("files/a/e_kuribo.dat")).source,
            Some("files/a/e_kuribo.dat")
        );

        let bare = Asset::named("chaos");
        assert!(bare.hint().contains("name"), "{}", bare.hint());
        assert!(!bare.hint().contains("disc path"), "{}", bare.hint());
        let sourced = Asset::sourced("loud", Some("files/sound/loud.brstm"));
        assert!(sourced.hint().contains("disc path"), "{}", sourced.hint());
    }
}
