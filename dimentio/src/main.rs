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
//! # Shape
//!
//! `data` reads what `bleck` exported, `render` turns a mesh into pixels, and
//! `app` is the window: three modes over one export folder — the texture
//! browser, the model viewport, and the effect table with its timeline.

use eframe::egui;

mod app;
mod data;
mod render;

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
            Ok(Box::new(app::Viewer::from_args()))
        }),
    )
}
