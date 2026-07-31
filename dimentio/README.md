# Dimentio

**The window onto Super Paper Mario's art**, without building a 460 MB disc
first.

Named for the jester who steps sideways out of the world to watch it.

```bash
cargo run -- ../work/export        # a folder bleck exported into
```

Two modes over the same folder: **Textures** and **Models**.

## ⛔ This program reads no game formats, and never should

`bleck` owns every format on the disc — TPL, U8, LZ77, setup files, evt
bytecode — and is tested against real data. A second implementation here would
drift from that one silently, and the failure mode is a texture that builds
correctly but displays wrongly, or the reverse.

So `bleck` exports PNG and JSON; this renders them. The viewer improves for
free as `bleck` learns more formats, and a format bug has exactly one place to
be fixed. The full reasoning is in [`docs/plan-dimentio.md`](../docs/plan-dimentio.md).

## State: stages 1 and 2

**Textures** — a virtualised grid, search, a format filter, and a detail panel
showing size, format, source disc file and archive member.

⚠️ **Rows are virtualised deliberately.** The disc holds 21,780 textures and
egui uploads every image it draws to the GPU and keeps it, so drawing them all
exhausts texture memory within seconds of scrolling. `show_rows` only calls
back for what is on screen.

**Models** — a searchable model list, and a viewport: drag to orbit, scroll to
zoom, three background presets, and a camera that fits itself to a model's
bounds on load. It reads `models.json` and the Wavefront OBJs that
`bleck model export` writes.

⚠️ **The viewport is a software rasteriser** (`src/render.rs`), not a `wgpu`
surface — perspective projection, a depth buffer, and flat shading from each
face's own normal, all on the CPU into an RGBA buffer that egui uploads as one
texture. That is what makes it testable: `cargo test` asserts on the pixels.

⚠️ **Faces are not culled.** Exported meshes carry no guaranteed winding, so
culling opens holes in them; hidden surfaces are removed by the depth buffer
alone and every face is lit from whichever side is visible.

### What has been checked, and how

`cargo test` — 36 tests, no display required. The renderer's evidence is a
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

🔶 **Still not confirmed by eye.** The window opens, holds, and responds — but
the machine this was written on cannot capture its own interactive desktop, so
nobody has *looked* at either mode. What the pixel tests cannot cover is
whether the drag direction feels right and whether the panels are laid out
sensibly.

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
