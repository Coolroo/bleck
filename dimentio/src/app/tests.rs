//! The window, laid out in a real egui frame with no window anywhere.
//!
//! ⚠️ "The window opens" is not evidence anybody can check: the machine this
//! was built on cannot capture its own interactive desktop. Laying the panels
//! out headlessly is what is left — a slider over an empty range, a waveform
//! over a track with no samples, or a panel that borrows itself surfaces here
//! instead of on a screen nobody can photograph.

use super::*;
use crate::data::sounds::Motion;

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

/// ⚠️ The second model carries no `source`, which is the row that proves a
/// "Copy source path" is left off rather than offered as an empty string.
const MODELS: &str = r#"{"schema": 1, "models": [
  {"name": "files/a/e_kuribo.dat", "shape": "kuriboShape", "file": "kuribo.obj",
   "source": "files/a/e_kuribo.dat", "positions": 3, "faces": 1,
   "triangles": 1, "coverage": 1.0, "fragment": false,
   "min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 0.0]},
  {"name": "files/a/sourceless.dat", "shape": "", "file": "sourceless.obj",
   "positions": 3, "faces": 1, "triangles": 1, "coverage": 1.0,
   "fragment": false, "min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 0.0]},
  {"name": "files/a/waving.dat", "shape": "wavingShape", "file": "waving.glb",
   "source": "files/a/waving.dat", "positions": 4, "faces": 2,
   "triangles": 2, "coverage": 1.0, "fragment": false,
   "animated": true, "animations": 2, "animations_dropped": 1,
   "clips": [{"name": "wave", "poses": 2, "seconds": 1.0, "written": true},
             {"name": "jump", "poses": 1, "seconds": 0.0, "written": true},
             {"name": "vast", "poses": 900, "seconds": 15.0, "written": false}],
   "min": [-2.0, -2.0, 0.0], "max": [2.0, 2.0, 0.0]}
]}"#;

/// The smallest thing the OBJ reader accepts, so a selected model has real
/// geometry to frame and rasterise.
const TRIANGLE: &str = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";

/// Four rows covering the shapes the panel has to survive: a track that
/// plays, a shorter one, a file this program refuses, and one with no
/// samples at all.
const SOUNDS: &str = r#"{"schema": 1, "sounds": [
  {"name": "loud", "file": "loud.wav", "source": "files/sound/loud.brstm",
   "rate": 8000, "channels": 2, "seconds": 1.0,
   "loops": true, "loop_start": 4000, "capped": true},
  {"name": "quiet", "file": "quiet.wav", "source": "files/sound/quiet.brstm",
   "rate": 8000, "channels": 1, "seconds": 0.5,
   "loops": false, "loop_start": 0, "capped": false},
  {"name": "floaty", "file": "floaty.wav", "source": "files/sound/floaty.brstm",
   "rate": 8000, "channels": 2, "seconds": 1.0,
   "loops": false, "loop_start": 0, "capped": false},
  {"name": "empty", "file": "empty.wav", "source": "files/sound/empty.brstm",
   "rate": 8000, "channels": 2, "seconds": 0.0,
   "loops": false, "loop_start": 0, "capped": false}
]}"#;

/// ⚠️ The PNGs and WAVs are written for real. `choose_image` decodes the
/// file the catalog names and `select_sound` decodes the file the sound
/// manifest names, so a folder of manifests with nothing behind them would
/// exercise only the failure paths.
/// ⚠️ Tagged per test. One folder shared between them races: a test that
/// deletes an image to reach the failure path would delete it under a test
/// running beside it.
fn export_folder(tag: &str) -> std::path::PathBuf {
    let root = std::env::temp_dir().join(format!("dimentio-ui-{tag}-{}", std::process::id()));
    std::fs::create_dir_all(&root).expect("scratch dir");
    std::fs::write(root.join("effects.json"), EFFECTS).expect("effects.json");
    std::fs::write(root.join("textures.json"), TEXTURES).expect("textures.json");
    std::fs::write(root.join("sounds.json"), SOUNDS).expect("sounds.json");
    std::fs::write(root.join("models.json"), MODELS).expect("models.json");
    for name in ["kuribo.obj", "sourceless.obj"] {
        std::fs::write(root.join(name), TRIANGLE).expect("a real obj");
    }
    // ⚠️ A real `.glb` with real morph targets, not a stub. The transport
    // reads its clip list out of the geometry, so a manifest row with
    // nothing behind it would exercise only the no-animation path.
    std::fs::write(
        root.join("waving.glb"),
        crate::data::gltf::fixtures::animated_quad(),
    )
    .expect("a real glb");
    let texel = crate::data::texture::Texel {
        r: 0,
        g: 220,
        b: 220,
        a: 255,
    };
    for name in ["a.png", "b.png"] {
        std::fs::write(root.join(name), crate::data::texture::png(1, 1, &[texel]))
            .expect("a real png");
    }

    use crate::data::wav;
    let full: Vec<i16> = (0..16_000)
        .map(|at| if at % 2 == 0 { i16::MAX } else { i16::MIN })
        .collect();
    std::fs::write(root.join("loud.wav"), wav::wav(8000, 2, &full)).expect("a real wav");
    std::fs::write(root.join("quiet.wav"), wav::wav(8000, 1, &vec![0i16; 4000]))
        .expect("a real wav");
    // ⚠️ IEEE float, which this program refuses rather than plays.
    std::fs::write(
        root.join("floaty.wav"),
        wav::write_wav(8000, 2, &full, 3, 32),
    )
    .expect("a real wav");
    std::fs::write(root.join("empty.wav"), wav::wav(8000, 2, &[])).expect("a real wav");
    root
}

/// A quarter of a simulated second between drawn frames.
///
/// ⚠️ The clock is fed in rather than measured. `run_sound_clock` asks for
/// an immediate repaint, which makes egui report the *real* time between
/// frames — microseconds in a test loop — so a transport driven by it would
/// never reach the end of a track however many frames were drawn.
const STEP: f64 = 0.25;

/// One egui frame with every sound panel in it, at simulated time `at`, and
/// no window anywhere.
///
/// ⛔ Nothing here opens an audio device, and nothing may. `play_sound` is
/// what reaches the mixer, and the transport is set directly instead — a
/// test suite that seized the sound card would be unrunnable on CI and
/// audible on a desk.
fn draw_sounds(viewer: &mut Viewer, ctx: &egui::Context, at: f64) {
    let input = egui::RawInput {
        time: Some(at),
        ..Default::default()
    };
    let _ = ctx.run(input, |ctx| {
        viewer.top_bar(ctx);
        viewer.run_sound_clock(ctx);
        viewer.sound_list(ctx);
        egui::CentralPanel::default().show(ctx, |ui| viewer.sound_detail(ui));
    });
}

/// The sound clock on its own, at simulated time `at` — no panels, so
/// nothing overwrites the state the caller set up.
fn run_clock(viewer: &mut Viewer, ctx: &egui::Context, at: f64) {
    let input = egui::RawInput {
        time: Some(at),
        ..Default::default()
    };
    let _ = ctx.run(input, |ctx| viewer.run_sound_clock(ctx));
}

fn sound_viewer(tag: &str) -> Viewer {
    let mut viewer = Viewer {
        mode: Mode::Sounds,
        ..Viewer::empty()
    };
    viewer.open(export_folder(tag));
    viewer
}

/// ⚠️ "The window opens" is not evidence anybody can check, and a track
/// playing is evidence nobody here can hear. Laying the panels out
/// headlessly is what is left: a slider over an empty range, a waveform
/// over a track with no samples, or a panel that borrows itself surfaces
/// here instead of on a screen nobody can photograph.
#[test]
fn the_sound_panels_lay_out_and_run_without_a_window() {
    let mut viewer = sound_viewer("sounds");
    assert_eq!(viewer.sounds.library.len(), 4);
    let ctx = egui::Context::default();
    let mut clock = 0.0;

    // Nothing selected is the state the tab opens in.
    draw_sounds(&mut viewer, &ctx, clock);

    viewer.select_sound(0);
    let loaded = viewer.sounds.loaded.as_ref().expect("loud.wav decoded");
    assert_eq!(loaded.audio.channels(), 2);
    assert!(
        !loaded.envelope.is_empty(),
        "a full-scale track has a shape"
    );
    assert!(viewer.sounds.note.is_none());

    // ⚠️ The transport is set here rather than clicked, so no device is
    // opened. The clock, the playhead and the waveform are what is on test.
    viewer.sounds.transport.play();
    clock += STEP;
    draw_sounds(&mut viewer, &ctx, clock);
    assert!(viewer.sounds.frame.is_some(), "no waveform was drawn");
    assert!(
        viewer.sounds.transport.time > 0.0,
        "a drawn frame advances the transport, got {}",
        viewer.sounds.transport.time
    );
    assert!(viewer.sounds.transport.time < 1.0, "and stays in the track");

    // ⚠️ The track ends. A transport that wrapped instead would still be
    // playing here, and a window left alone would loop for ever.
    for _ in 0..8 {
        clock += STEP;
        draw_sounds(&mut viewer, &ctx, clock);
    }
    assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);
    assert_eq!(viewer.sounds.transport.time, 0.0);
}

/// The three files that are not a playable track, drawn through the real
/// panels. Each one is a division by zero or an empty slider range waiting
/// to happen.
#[test]
fn a_refused_or_empty_track_is_named_rather_than_panicking() {
    let mut viewer = sound_viewer("sounds-odd");
    let ctx = egui::Context::default();

    viewer.select_sound(2);
    let why = viewer.sounds.note.as_ref().expect("floaty.wav is refused");
    assert!(why.contains("PCM"), "{why}");
    assert!(viewer.sounds.loaded.is_none(), "nothing was decoded");
    // ⛔ Pressing play on a file that would not decode must not reach the
    // mixer, which is also what keeps this test off the sound card.
    viewer.play_sound();
    assert!(!viewer.sounds.audio.live(), "no device was opened");
    draw_sounds(&mut viewer, &ctx, STEP);

    // A track with no samples: the scrubber would be a slider over an
    // empty range, and the playhead a division by its length.
    viewer.select_sound(3);
    assert!(viewer.sounds.loaded.is_some(), "an empty wav still decodes");
    viewer.sounds.transport.play();
    draw_sounds(&mut viewer, &ctx, STEP * 2.0);
    assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);
    assert_eq!(viewer.sounds.transport.time, 0.0);

    // And an export with no sound manifest at all.
    let mut bare = Viewer {
        mode: Mode::Sounds,
        ..Viewer::empty()
    };
    bare.open(std::env::temp_dir().join("dimentio-ui-absent"));
    assert!(bare.sounds.library.problem().is_some());
    draw_sounds(&mut bare, &ctx, STEP);
}

/// The whole tab against the folder `bleck sound export` actually wrote,
/// when there is one.
///
/// ⚠️ The fixtures above are two-second files this crate writes itself. A
/// 20-second 44.1 kHz stereo track is 3.5 M samples, and the envelope, the
/// list of 135 rows and the panel layout have never met one anywhere else.
#[test]
fn the_real_export_opens_and_draws_a_real_track() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("a parent directory")
        .join("work")
        .join("export");
    if !root.join("sounds.json").is_file() {
        eprintln!("no work/export on this machine; skipped");
        return;
    }
    let mut viewer = Viewer {
        mode: Mode::Sounds,
        ..Viewer::empty()
    };
    viewer.open(root);
    assert!(viewer.sounds.library.len() > 100, "the real manifest");

    let ctx = egui::Context::default();
    viewer.select_sound(0);
    let loaded = viewer.sounds.loaded.as_ref().expect("a real track decodes");
    assert!(loaded.audio.seconds() > 1.0, "a real track has length");
    assert!(!loaded.envelope.is_empty());
    viewer.sounds.transport.play();
    draw_sounds(&mut viewer, &ctx, STEP);
    assert!(viewer.sounds.frame.is_some(), "no waveform was drawn");
    assert!(
        viewer.sounds.transport.playing(),
        "a real track outlasts one frame"
    );
    assert!(!viewer.sounds.audio.live(), "no device was opened");
}

/// ⚠️ A held scrub handle owns the position. The clock runs on every drawn
/// frame, so without this the handle is dragged back out of the user's
/// hand — which looks like a slider that will not move, and is invisible to
/// any check that only draws single frames.
#[test]
fn a_held_scrubber_keeps_its_position_while_frames_go_by() {
    let mut viewer = sound_viewer("sounds-scrub");
    let ctx = egui::Context::default();
    viewer.select_sound(0);
    viewer.sounds.transport.play();
    viewer.sounds.transport.seek(0.6, 1.0);

    // ⛔ The clock alone, not a whole frame: the flag is derived from the
    // widgets on every frame, so a drawn frame with no pointer in it would
    // clear the flag before the clock could be seen ignoring it.
    let mut clock = 0.0;
    for _ in 0..4 {
        clock += STEP;
        viewer.sounds.scrubbing = true;
        run_clock(&mut viewer, &ctx, clock);
        assert_eq!(viewer.sounds.transport.time, 0.6, "the clock moved it");
    }
    assert_eq!(viewer.sounds.transport.motion, Motion::Playing);

    // Letting go hands the position back to the clock.
    viewer.sounds.scrubbing = false;
    clock += STEP;
    run_clock(&mut viewer, &ctx, clock);
    assert!(
        viewer.sounds.transport.time > 0.6,
        "the clock did not resume, got {}",
        viewer.sounds.transport.time
    );

    // ⚠️ And a drawn frame with no pointer in it leaves the flag false, so
    // a scrub that ended outside the window cannot freeze the clock.
    viewer.sounds.scrubbing = true;
    clock += STEP;
    draw_sounds(&mut viewer, &ctx, clock);
    assert!(!viewer.sounds.scrubbing, "nothing is holding the scrubber");
}

/// ⚠️ The two ways a track gets abandoned. Both have to silence it: a
/// stream left running behind a tab nobody is looking at has no visible
/// control to stop it with.
#[test]
fn changing_track_or_leaving_the_tab_stops_what_was_playing() {
    let mut viewer = sound_viewer("sounds-stop");

    viewer.select_sound(0);
    viewer.sounds.transport.play();
    viewer.sounds.transport.seek(0.4, 1.0);
    assert_eq!(viewer.sounds.transport.time, 0.4);

    viewer.select_sound(1);
    assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);
    assert_eq!(viewer.sounds.transport.time, 0.0, "and back to the start");
    assert_eq!(
        viewer
            .sounds
            .loaded
            .as_ref()
            .expect("quiet.wav")
            .audio
            .channels(),
        1,
        "the new track's samples replaced the old ones"
    );

    viewer.sounds.transport.play();
    viewer.mode = Mode::Textures;
    viewer.switched_from(Mode::Sounds);
    assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);

    // Opening another folder drops the pane, and with it the engine.
    viewer.mode = Mode::Sounds;
    viewer.select_sound(0);
    viewer.sounds.transport.play();
    viewer.open(export_folder("sounds-reopen"));
    assert_eq!(viewer.sounds.transport.motion, Motion::Stopped);
    assert!(viewer.sounds.selected.is_none());
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
    let root = export_folder("panels");
    let mut viewer = Viewer {
        mode: Mode::Effects,
        ..Viewer::empty()
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
    viewer.select_effect(0);
    draw(&mut viewer, &ctx);
    let mut bare = Viewer {
        mode: Mode::Effects,
        ..Viewer::empty()
    };
    bare.open(std::env::temp_dir().join("dimentio-ui-absent"));
    assert!(bare.effects.library.problem().is_some());
    draw(&mut bare, &ctx);
}

/// The viewport's plumbing, end to end through the window: an effect is
/// picked, a frame is rasterised, and a bank image the user clicked reaches
/// the part they chose.
///
/// ⛔ The pairing is the user's. Nothing here reads an image out of the
/// effect data, and `render::effect`'s own tests are what prove the chosen
/// image changes the pixels — this only proves the window can deliver it.
#[test]
fn the_viewport_rasterises_and_takes_a_manually_chosen_image() {
    let root = export_folder("stage");
    let mut viewer = Viewer {
        mode: Mode::Effects,
        ..Viewer::empty()
    };
    viewer.open(root);
    let ctx = egui::Context::default();

    viewer.select_effect(0);
    assert!(!viewer.effects.stage.drawn(), "nothing has been drawn yet");
    draw(&mut viewer, &ctx);
    assert!(viewer.effects.stage.drawn(), "the viewport drew no frame");
    assert_eq!(
        viewer.effects.stage.previewing(),
        None,
        "nothing was picked"
    );

    let image = viewer.effects.bank[0];
    viewer.choose_image(image);
    assert_eq!(
        viewer.effects.stage.previewing(),
        Some(("files/eff/effdata.tpl#0", 0)),
        "the clicked image did not reach the chosen part"
    );
    draw(&mut viewer, &ctx);

    // A catalog entry whose PNG is not on disk must say so rather than
    // silently keeping the last image.
    std::fs::remove_file(&viewer.catalog.entries()[image].path).expect("the png");
    viewer.choose_image(image);
    assert_eq!(viewer.effects.stage.previewing(), None);
    draw(&mut viewer, &ctx);
}

/// ⚠️ **egui repaints on far more than the timeline moving** — a mouse crossing
/// the window is enough — and the effect viewport used to rasterise on every one
/// of them, which is a full software render of the effect per mouse move. The
/// pixels are identical either way, so nothing but a count can see this.
#[test]
fn a_repaint_that_changes_nothing_re_uses_the_frame_it_already_drew() {
    let root = export_folder("held");
    let mut viewer = Viewer {
        mode: Mode::Effects,
        ..Viewer::empty()
    };
    viewer.open(root);
    let ctx = egui::Context::default();

    // ⚠️ egui settles a panel's size over its first repaints, and the frame is
    // rasterised at that size — so the count is taken once the layout has
    // stopped moving rather than after the very first pass.
    viewer.select_effect(0);
    for _ in 0..3 {
        draw(&mut viewer, &ctx);
    }
    let first = viewer.effects.stage.rasterised();
    assert!(first > 0, "the viewport drew no frame at all");

    for _ in 0..5 {
        draw(&mut viewer, &ctx);
    }
    assert_eq!(
        viewer.effects.stage.rasterised(),
        first,
        "a repaint with nothing moved rasterised again"
    );

    // The control: the rig has to be able to see a redraw happen, or the
    // assertion above passes for a viewport that has simply stopped working.
    viewer.effects.play.time += 0.25;
    draw(&mut viewer, &ctx);
    assert_eq!(
        viewer.effects.stage.rasterised(),
        first + 1,
        "moving the scrubber did not redraw"
    );

    viewer.effects.stage.view.background = render::Background::Gradient;
    draw(&mut viewer, &ctx);
    assert_eq!(
        viewer.effects.stage.rasterised(),
        first + 2,
        "changing the background did not redraw"
    );
}

/// One egui frame with every texture panel in it, and no window anywhere.
fn draw_textures(viewer: &mut Viewer, ctx: &egui::Context) {
    let _ = ctx.run(egui::RawInput::default(), |ctx| {
        viewer.top_bar(ctx);
        viewer.detail_panel(ctx);
        egui::CentralPanel::default().show(ctx, |ui| viewer.grid(ui));
    });
}

/// One egui frame with every model panel in it, and no window anywhere.
fn draw_models(viewer: &mut Viewer, ctx: &egui::Context) {
    draw_models_at(viewer, ctx, 0.0);
}

/// One model frame at simulated time `at`, with the animation clock and
/// the transport in it — the same panels `update` runs, in the same order.
fn draw_models_at(viewer: &mut Viewer, ctx: &egui::Context, at: f64) {
    let input = egui::RawInput {
        time: Some(at),
        ..Default::default()
    };
    let _ = ctx.run(input, |ctx| {
        viewer.top_bar(ctx);
        viewer.run_model_clock(ctx);
        viewer.model_list(ctx);
        viewer.model_facts(ctx);
        viewer.model_transport(ctx);
        viewer.hold_pose();
        egui::CentralPanel::default().show(ctx, |ui| viewer.viewport(ui));
    });
}

/// The index of the animated row in `MODELS`.
const WAVING: usize = 2;

fn model_viewer(tag: &str) -> Viewer {
    let mut viewer = Viewer {
        mode: Mode::Models,
        ..Viewer::empty()
    };
    viewer.open(export_folder(tag));
    viewer
}

/// ⚠️ **Paused on the first frame**, which is what was asked for: a model
/// that started animating the moment it was picked would never sit still
/// long enough to look at.
#[test]
fn a_newly_selected_model_is_paused_at_the_first_frame_of_its_first_clip() {
    let mut viewer = model_viewer("anim-default");
    let ctx = egui::Context::default();
    viewer.select_model(WAVING);
    draw_models(&mut viewer, &ctx);

    assert!(!viewer.models.play.playing, "it started playing by itself");
    assert_eq!(viewer.models.play.time, 0.0);
    assert_eq!(viewer.models.clip, 0);
    let animation = viewer.models.mesh.animation().expect("the glb has clips");
    assert_eq!(animation.clips().len(), 2);
    assert_eq!(animation.clips()[0].name, "wave");
    // The first pose is held, not the rest geometry: vertex 0 is lifted.
    let rest = viewer.models.mesh.rest_positions().to_vec();
    assert_ne!(viewer.models.mesh.positions()[0], rest[0]);
}

/// A model with no clip must behave exactly as it did: no transport, no
/// pose, and the geometry the file carried.
#[test]
fn a_model_with_no_animation_is_left_alone() {
    let mut viewer = model_viewer("anim-none");
    let ctx = egui::Context::default();
    viewer.select_model(0);
    draw_models(&mut viewer, &ctx);
    assert!(viewer.models.mesh.animation().is_none());
    assert_eq!(viewer.models.posed, None, "nothing was posed");
    assert_eq!(
        viewer.models.mesh.positions(),
        viewer.models.mesh.rest_positions()
    );
}

/// Playing moves the clip on, and moving it re-poses the geometry.
#[test]
fn playing_advances_the_clip_and_displaces_the_mesh() {
    let mut viewer = model_viewer("anim-play");
    let ctx = egui::Context::default();
    viewer.select_model(WAVING);
    draw_models_at(&mut viewer, &ctx, 0.0);
    let first = viewer.models.mesh.positions().to_vec();

    viewer.models.play.playing = true;
    for step in 1..6 {
        draw_models_at(&mut viewer, &ctx, f64::from(step) * STEP);
    }
    assert!(viewer.models.play.time > 0.0, "the clock did not run");
    assert_ne!(
        viewer.models.mesh.positions(),
        first,
        "the geometry did not follow the clock"
    );
}

/// Picking another clip rewinds: the old position may be past the end of
/// the new one, and a clip that opened halfway through would look wrong.
#[test]
fn choosing_another_clip_rewinds_to_its_start() {
    let mut viewer = model_viewer("anim-pick");
    let ctx = egui::Context::default();
    viewer.select_model(WAVING);
    draw_models(&mut viewer, &ctx);
    viewer.models.play.time = 0.75;
    viewer.models.clip = 1;
    viewer.models.play.rewind();
    draw_models(&mut viewer, &ctx);
    assert_eq!(viewer.models.play.time, 0.0);
    // `jump` is a single key: nothing to scrub, and nothing to divide by.
    assert!(!viewer.models.play.playing);
}

/// Scrubbing past the end, onto a clip that does not exist, and through a
/// clip of zero length are all reachable from the window.
#[test]
fn a_scrub_past_the_end_or_onto_a_missing_clip_does_not_panic() {
    let mut viewer = model_viewer("anim-edges");
    let ctx = egui::Context::default();
    viewer.select_model(WAVING);
    for (clip, time) in [(0, 900.0), (0, -3.0), (1, 5.0), (9, 0.5)] {
        viewer.models.clip = clip;
        viewer.models.play.time = time;
        draw_models(&mut viewer, &ctx);
    }
    assert!(!viewer.models.mesh.positions().is_empty());
}

/// All four tabs, laid out with the copy widgets in them.
///
/// ⚠️ Every one of these is a layout change: a fact row now holds a
/// frameless button and a copy button where it held a label, a grid cell
/// holds two widgets instead of one, and each row carries a context menu.
/// Layout is the only part of this window anything here can see.
#[test]
fn every_tab_lays_out_with_the_copy_widgets_present() {
    let mut viewer = Viewer::empty();
    viewer.open(export_folder("copy-layout"));
    let ctx = egui::Context::default();

    assert_eq!(viewer.catalog.len(), 2);
    draw_textures(&mut viewer, &ctx);
    viewer.selected = Some(0);
    draw_textures(&mut viewer, &ctx);

    viewer.mode = Mode::Models;
    assert_eq!(viewer.models.library.len(), 3);
    draw_models(&mut viewer, &ctx);
    viewer.select_model(0);
    draw_models(&mut viewer, &ctx);
    // The animated row, which lays out a clip picker and a transport the
    // other two do not have.
    viewer.select_model(WAVING);
    draw_models(&mut viewer, &ctx);
    // ⚠️ The row with no `source`. Its facts strip and its menu must come
    // out one item shorter rather than offering an empty path.
    viewer.select_model(1);
    assert!(viewer.models.library.entries()[1].source_text().is_none());
    draw_models(&mut viewer, &ctx);

    viewer.mode = Mode::Effects;
    viewer.select_effect(0);
    draw(&mut viewer, &ctx);

    viewer.mode = Mode::Sounds;
    viewer.select_sound(0);
    draw_sounds(&mut viewer, &ctx, STEP);
}
