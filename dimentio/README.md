# Dimentio

**The window onto Super Paper Mario's art**, without building a 460 MB disc
first.

Named for the jester who steps sideways out of the world to watch it.

```bash
cargo run -- ../work/export        # a folder bleck exported into
```

Four modes over the same folder: **Textures**, **Models**, **Effects** and
**Sounds**.

## Without a screen: `dimentio shot` and `dimentio reel`

Render straight to a PNG and exit. No window, no GPU, no display — the same
software rasteriser the viewport draws through, writing a file instead of a
texture handle (D253, D257).

`shot` takes a **model** and gives you one instant from several angles. `reel`
takes an **effect** and gives you one angle at several instants. The split
follows what there is to check: a model's problem is its shape from some
direction, an effect's is *when* its parts run.

```bash
cargo run --release -- shot ../work/export/models/files/a/e_lui_robo.glb --out robo.png
```

| option | |
|---|---|
| `--out <file.png>` | where to write. Required |
| `--size 512` | edge of one view |
| `--angles 4` | views around the model, laid out as one contact sheet |
| `--clip 0 --frame 4` | hold one keyframe of one morph clip |
| `--background checkerboard` | `dark-grey`, `checkerboard` or `gradient` |

⚠️ **Four angles into one image, not four files.** Most defects show from one
direction only — a stray shape off to the side, a face that vanishes from
behind, one part left untextured — and the file nobody opens is the one that
showed it.

⚠️ **The backdrop is never white.** A texture that decoded to near-white and a
texture that failed to decode are the same picture on a white page.

The run also prints what it drew, so a caller that cannot see the file still
learns something from it:

```
3358 triangle(s), 92 shape(s), 15 image(s)
rest pose
4 angle(s) into 1026x1026
model covers 4.5% of the sheet
colour spread 0.758, neighbour step 0.045 — an image reached it
```

⛔ **Colour spread does not mean "an image reached it"** — 41 models name no
image and are painted entirely by vertex colour, and `e_big_nok` is the most
colourful thing in the export at 1.426 with nothing bound to it. The image
count, read from the file, is what the verdict uses.

### `dimentio reel` — an effect across its own timeline

```bash
cargo run --release -- reel --effect chaos --export ../work/export --out chaos.png
```

| option | |
|---|---|
| `--effect <name>` | which effect, as `bleck effect list` names it. Required |
| `--out <file.png>` | where to write. Required |
| `--export <dir>` | folder holding `effects.json`. Default `work/export` |
| `--frames 9` | frames sampled across the range, into one sheet |
| `--from 1` / `--to 46` | game frames to sample between, 1-based and inclusive |
| `--size 320` | edge of one frame |
| `--background checkerboard` | as above |

**Write to a `.gif` and it animates instead**, looping, one cell per frame.
A model sweeps keyframes the same way: `shot m.glb --out m.gif --frame 0 --to 7`.

⚠️ **A GIF delay is a whole centisecond**, so a 60 Hz effect cannot play at
rate — one game frame is 1.67 cs. The report names the rate it really used.

⚠️ **Frame 1 is often the least informative one.** Effect scales rise from
zero, so 44% of draws are flat there and 26 effects draw nothing at all. If an
effect looks empty, try `--from 10` before believing it.

```
chaos — 4 part(s), 3.00s, 181 frame(s) long
9 frame(s) sampled into 664x664
  frame    1 at  0.000s — 4 active, 4 painted, 5.2% drawn
  frame   69 at  1.125s — 2 active, 2 painted, 2.5% drawn
  frame  136 at  2.250s — 1 active, 1 painted, 1.5% drawn
2 of 8 frame pair(s) differ
4 of 4 part(s) drew a decoded image (D258)
```

✅ **The images are real** (D258). A part's image is five sections past its
record — node → draw → subdraw → material → texture — and `bleck` resolves it
into the export. `sweat` renders as a blue droplet; `system`'s parts land on the
noise fields and white square they are named after.

✅ **And where the parts sit is real too.** Each draw carries the chain of nodes
above it; every one is posed at the frame — its static transform with any curve
of its own written over the top — and the results multiplied parent-first. That
is the game's own scheme, transcribed from its evaluator.

✅ **And so is how visible it is** (D280). A draw is multiplied by its
material's own colour register and by the drawing node's alpha at that frame,
and a draw those two leave at zero alpha is not drawn at all. 291 of the file's
524 materials are not white and 660 drawing nodes carry an alpha curve, so this
is most of the corpus rather than an edge case: `explosion` goes from a solid
red starburst that never fades to a yellow fireball that does.

⛔ **A node's alpha is not inherited by its children.** Whether it should be is
untested, and 15 further draws would fade to nothing on the assumption that it
is. Each node's own alpha, and nothing else.

⚠️ **`N faded out` in a frame's row is draws left out for having no alpha
left**, and it is the only trace they leave. An effect where every draw fades
out — `spindash`, whose one material is `(255, 255, 255, 0)` — says so instead
of blaming a stale export.

⚠️ **An effect that draws nothing at frame 1 is usually correct.** Scales rise
from zero, so 44% of draws are flat there and 26 of the 139 effects draw nothing
at all. Move the window with `--from 10` before believing one is empty.

⚠️ **`chaos` is grey gradient ramps as *artwork*** — its shape is display-list
geometry, which the viewer now draws. Do not use "does it look right?" on an
effect whose textures are abstract; that test nearly refuted the correct
decoding of the image binding.

What the report settles is that the manifest and the renderer agree: the parts
called running are the parts that reach the pixels, every part declaring a
picture gets one, and the drawn area falls as parts end.

⛔ **Colour spread does not separate a textured model from a bare one**, and the
0.015 threshold this paragraph used to quote is dead. D251 taught the renderer to
draw `COLOR_0`, and 41 models that name no image are painted entirely from their
vertices — `e_big_nok` reaches **1.426** with nothing bound to it, against
`e_lui_robo`'s 0.758 with fifteen images. The verdict reads the **image count**
from the file; spread only says the frame is not one flat tint. ⚠️ A greyscale
image still spreads like a bare model — `OFF_doorL` is 0.011. ⛔ **Neighbour step
decides nothing**; D253 records the two measurements that took it out.

Every other command line still opens the window, unchanged.

## ⛔ This program reads no game formats, and never should

`bleck` owns every format on the disc — TPL, U8, LZ77, setup files, evt
bytecode — and is tested against real data. A second implementation here would
drift from that one silently, and the failure mode is a texture that builds
correctly but displays wrongly, or the reverse.

So `bleck` exports PNG and JSON; this renders them. The viewer improves for
free as `bleck` learns more formats, and a format bug has exactly one place to
be fixed. The full reasoning is in [`docs/plan-dimentio.md`](../docs/plan-dimentio.md).

## State: stages 1, 2, 3 and 4

**Textures** — a virtualised grid, search, a format filter, and a detail panel
showing size, format, source disc file and archive member.

⚠️ **Rows are virtualised deliberately.** The disc holds 21,780 textures and
egui uploads every image it draws to the GPU and keeps it, so drawing them all
exhausts texture memory within seconds of scrolling. `show_rows` only calls
back for what is on screen.

**Models** — a searchable model list, and a viewport: drag to orbit, scroll to
zoom, three background presets, and a camera that fits itself to a model's
bounds on load. It reads `models.json` and the binary glTF that
`bleck model export` writes.

**Animation** — a model that carries clips gets a clip picker, play/pause,
rewind and a scrub bar, **paused on the first frame** when it is selected.
Animation in this game is per-vertex morphing, so playing a clip is a weighted
sum of position deltas over the rest pose (`src/data/morph.rs`).

⚠️ **Weights are interpolated the way glTF's `LINEAR` sampler is defined.**
`bleck` writes one pose at weight 1 at a time, and a reader that assumed that
shape would be right today and wrong the moment anything blends.

⚠️ **Bounds are measured once, from the rest pose**, so the camera does not
refit itself on every frame of a clip.

⚠️ **The viewport is a software rasteriser** (`src/render/`), not a `wgpu`
surface — perspective projection, a depth buffer, and flat shading from each
face's own normal, all on the CPU into an RGBA buffer that egui uploads as one
texture. That is what makes it testable: `cargo test` asserts on the pixels.

⚠️ **Faces are not culled.** Exported meshes carry no guaranteed winding, so
culling opens holes in them; hidden surfaces are removed by the depth buffer
alone and every face is lit from whichever side is visible.

**Effects** — the 139 effects from `effects.json`: a searchable list, each
effect's parts and transform rows, and a timeline that plays and scrubs over
the effect's own duration, marking which parts are still running.

⚠️ **Durations are frames at 60 Hz, counted inclusively** — 61 frames is one
second, so a 1-frame part lasts zero and the timeline's end is inclusive. An
exclusive end would make every single-frame part invisible at every time.

⛔ **Nothing is simulated.** The timeline plays the durations the exported data
records and says which parts are running; an effect's behaviour is compiled
PowerPC, and an approximation of an emitter would look plausible and be wrong.

✅ **Which image a part draws is decoded** (`docs/decision-log.md` D258), so a
part is drawn with its own artwork and the parts table lists its image indices.
The 219 images from `files/eff/effdata.tpl` are still shown as a bank strip —
that is the browser, in catalog order, and clicking one previews it on a part as
an explicit override rather than as a claim.

✅ **Where the parts sit is decoded**, and posed per frame from the file's own
curves. ⛔ What is left in amber: a draw with **no geometry** falls back to a
camera-facing quad on an even ring, because there is no measured position to put
it at instead — and the run reports how many did.

**Sounds** — the 135 tracks from `sounds.json`: a searchable, virtualised list,
the facts `bleck` recorded about each one, play / pause / stop with a seek
scrubber and a volume control, and the whole track drawn as a waveform with a
playhead on it. Pressing anywhere in the waveform moves the playhead there.

⚠️ **A scrub moves the transport on every frame, and the mixer once** — on the
frame the pointer comes up. Requeueing the mixer per frame restarts the sound as
fast as frames are drawn, and each restart blocks the UI thread until the
mixer's queue drains.

⚠️ **`capped` means the file is shorter than the game's track.** The exporter
truncates at `--seconds`, so the duration shown is the *export's* duration and
the panel says so in amber.

⚠️ **Only 16-bit PCM is read**, because that is all `bleck` writes. A float or
24-bit WAV is refused by name rather than played: read as integers, either one
is full-scale noise, which looks like a bug in `bleck`'s BRSTM decoder rather
than in this reader.

⚠️ **The audio device is opened on the first play, not when the folder is.** A
window opened to look at textures does not seize the sound card, a machine
without one says so instead of ignoring the play button, and `cargo test` never
touches audio hardware at all.

⛔ **Every `rodio` type stays inside `src/app/audio.rs`.** The rest of the
window deals in seconds and a `Transport`, which is what lets play, pause, stop
and seek be tested with no device present.

### What has been checked, and how

`cargo test` — 253 tests, no display required and no sound card. The renderer's
evidence is a
rendered cube covering **29.1%** of a 200×200 frame in exactly **4 colours**
(background plus the three faces a cube shows from a general direction), a
centroid at 97.4, 102.6 against a centre of 99.5, and corners left untouched.

Against a real export of **864 models**: all 864 parse, every triangle count
matches the manifest, and none renders blank. Coverage of a 120×120 frame runs
from 0.7% for the thinnest sliver to 29.1%, median 19.6%.

⚠️ **15 of those 864 rendered blank at first**, and the cause was framing, not
rasterising: their faces reference a handful of positions out of thousands, so
a camera fitted to the whole position pool put the geometry under one pixel.
`Bounds::around` now spans only the positions some face refers to. 733 of the
864 models carry positions no face uses, so this is the common case, not an
edge case.

The suite was checked against five deliberate breakages, each caught:

| Break | Test that failed |
|---|---|
| Depth compare removed | `the_depth_buffer_keeps_the_nearer_face_whatever_the_draw_order` |
| Edge test removed (bounding boxes filled) | `a_triangle_covers_only_its_own_half_of_its_bounding_box` |
| Two-sided shading removed | `shading_darkens_a_face_turned_away_from_the_light` |
| Camera fit margin wrong | `a_fitted_model_never_reaches_the_corners`, and two more |
| Near-plane cull removed | `geometry_behind_the_camera_is_dropped` |

Against the real export the effect loader reads **139 effects, 704 parts and
4,048 transform rows**, and the bank filter picks **219 of 21,780** catalog
images — every one of them from `files/eff/effdata.tpl`.

The effect panels are laid out in a real egui frame with no window at all
(`the_effect_panels_lay_out_and_play_without_a_window`), which is what covers
the two cases a screenshot would have had to catch: playback advancing on a
drawn frame, and a zero-length effect, whose scrubber would otherwise be a
slider over an empty range. Deleting that guard fails the test.

Against the real export the sound loader reads **135 tracks** — 2,084 s in
total, every one stereo, at 32,000 / 32,028 / 32,728 / 44,100 Hz, all 135 capped
and 102 of them looping. All 135 WAVs decode, and the first 24 checked in detail
agree with their manifest row on rate, channels and duration to within 10 ms.

The waveform is a function over the samples, so it is checked on pixels: silence
draws as a one-pixel line through the centre of every column, a full-scale track
reaches both edges of every column, and a track that swells draws wider on the
right than the left. The playhead's time → column mapping is asserted at the
start, the middle and the end.

| Break | Test that failed |
|---|---|
| Playhead's duration divisor dropped | `the_playhead_maps_time_to_a_column`, `a_playhead_outside_the_track_is_pinned_or_absent`, `the_playhead_is_drawn_in_the_column_the_mapping_names` |
| `Transport::play` rewinds instead of resuming | `pause_then_play_resumes_rather_than_restarting` |

⛔ **Playback itself is unverified.** Nothing in the suite opens an audio device
— on purpose, since a test that seized the sound card could not run on CI — so
what has been checked is the transport, the decode, the waveform and the layout.
Whether sound comes out of the speakers, at the right pitch, in the right order,
has to be checked by a person with ears.

🔶 **Still not confirmed by eye.** The window opens, holds, and responds — but
the machine this was written on cannot capture its own interactive desktop, so
nobody has *looked* at any mode. What the tests cannot cover is whether the
drag direction feels right, whether playback looks smooth, and whether the
panels are laid out sensibly.

## Where the source is

Four top-level modules, and nothing else at the top level but `main.rs`:

| module | what it owns |
|---|---|
| `src/data/` | reading what `bleck` exported — manifests, glTF, PNG, WAV. **No game format is decoded anywhere in this program** |
| `src/render/` | the software rasteriser: camera, triangles, blending, backdrops, waveforms |
| `src/app/` | the window — one file per mode, plus the state they share |
| `src/headless/` | `shot` and `reel`: the same rendering written to a file instead of a screen |

⚠️ **A module with more than a page of tests is a directory**, with its tests in
a file beside the code they cover — `data/mesh/tests.rs`,
`render/raster/texture_tests.rs`, `headless/reel/real_export_tests.rs`. There
are no `#[path]` attributes: a test file lives where its module lives.

⚠️ **Dependencies run one way.** Inside `data/mesh`, `geometry` knows nothing of
materials and `paint` nothing of files; inside `headless`, `shot` and `reel`
share `args`, `sheet` and `encode` and neither reads the other. A submodule that
reaches back into its parent's siblings is the seam being in the wrong place.

## Why Rust, and what that must not cost

`wgpu` reaches Vulkan, Metal and DX12 from one codebase, and the result is a
single static binary per platform with no runtime to install.

⚠️ The conditions that keep it from becoming a liability:

1. **No game-format parsing here** — the rule above.
2. **`bleck`'s own build, test and lint never require a Rust toolchain.** This
   crate has its own CI job for that reason.
3. **Dimentio is a lens on the CLI, never the only way to do something.** A
   headless machine stays fully capable.

## Building

Needs a recent stable Rust. `Cargo.lock` is committed, and `image` is pinned to
0.25.5 because 0.25.10 requires rustc 1.88 while this was written against 1.87 —
raise it once the toolchain floor moves.

⚠️ **Linux needs ALSA's development headers** (`libasound2-dev` on Debian and
Ubuntu). `rodio` builds on `cpal`, which links against them; without them the
build fails in `alsa-sys` rather than in this crate.
