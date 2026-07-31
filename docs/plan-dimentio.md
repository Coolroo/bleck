# Dimentio: an asset viewer for textures, models, effects and animations

**What it should be.** `dimentio` — a window with a 3D viewport — orbit the camera, pick a
background, load a sprite or a model, and play the animations the game
associates with it. Cross-platform: Windows, Linux, macOS.

**Why it matters.** `vision.md` wants a full editor. Every editor needs a
viewport, and right now the only way to see whether a change looks right is to
build a 460 MB disc and boot Dolphin — 2–3 minutes per look. A viewer turns
that into a keystroke.

---

## ⛔ Read this before planning any of it

The three things Dimentio shows are in **completely different states**, and
treating them as one project would mean building a 3D viewport with nothing to
put in it.

| | State | Buildable? |
|---|---|---|
| **Textures** | ✅ TPL parsed and decodable (D187) | **Yes, today** |
| **Effect textures** | ✅ Same — `effdata.tpl` is 219 images | **Yes, today** |
| **Effect definitions** | 🔶 `effdata.dat` undecoded, but *small* | Tractable |
| **Effect behaviour** | ✅ 174 named, ⛔ each is DOL code | List only |
| **Models** | 🔶 Container format unidentified | No — needs research first |
| **Animations** | 🔶 Only the *name* of a table is known | No |

### What is actually known about models

`/a` holds 1,687 files in pairs: `name` (model) and `name-` (a TPL texture bank,
✅ confirmed). The model half announces a good deal about itself and decodes to
nothing:

```
$ head -c 48 a/p_wii_mario | xxd
00 01 5f 5c  p_wii_mario\0 ...
```

Readable strings in the first 4 KB: `Mon Jan 29 10:30:46 2007`, then
`R_Arm_skinShape`, `L_Arm_skinShape`, `zentaiShape`, `big_hammerShape`,
`awate_footShape`. Maya shape names, **skinned**, from a dated export.

`map.dat` is the same family and names its own sections (D167):

```
world_root  mesh  information  ver1.02
material_name_table  texture_table  animation_table
curve_table  light_table  fog_table  vcd_table
```

⚠️ **A string table is not a mesh.** These tell us the format has materials,
textures, animations and a vertex-component descriptor (`vcd_table` — a GX term,
so the vertex data is likely in GX display-list form). **No vertex, index,
weight or keyframe has been located.** That is the work, and it is
reverse-engineering measured in weeks, not an afternoon.

✅ **Superseded — the geometry is decoded** (D207, D208, D209). The vertex
format was not found by reading the file; it was read off the game's own draw
code at `0x80048400`, which states it outright: positions and normals are
big-endian float32 XYZ at stride 12, indexed by `u16`. The section table at file
`+0x150` holds the face list, positions, normals, colours and their index
streams, and the loader relocates it in place, so the runtime offsets *are* the
file offsets.

All **864** readable models resolve their indices — 127,076 triangles — and
`bleck model export` writes them as OBJ plus a `models.json` manifest.

⛔ **But each is a fragment** (D211). Median coverage is 13.6% of a file's
vertices; `p_big_kuppa` reaches three of 3,401. One shape record is read and a
character file names dozens, so **the viewport has geometry to draw and not yet
a character to show.**

⚠️ **Two things are still not decoded.** A file holds several shapes and only
the first is read, so an exported OBJ is a part rather than a character; and
animation is still names and pointers, so Stage 5 is unchanged.

⛔ **The old warning below stood for months and was right at the time.** It is
kept because it records what the estimate looked like from the other side of the
problem — "weeks, not an afternoon" was the correct read until `dolscan callers`
existed to ask the question a different way.

⛔ **So: do not start with the 3D viewport.** Camera controls and preset
backgrounds around an empty scene is the most demoralising possible order to
build this in, and none of it can be validated until geometry exists.

---

## Architecture: `bleck` exports, Dimentio renders

The one decision that matters, because getting it wrong is expensive and quiet.

⛔ **Dimentio must not parse a single game format.** If it re-implements TPL,
U8 or LZ77 in Rust, there are immediately two implementations of each, they
drift, and a texture that builds correctly displays wrongly — or worse, the
reverse. `bleck` already owns these and is tested against the real disc.

✅ So `bleck` **exports to standard formats** and Dimentio consumes those:

```
bleck texture export <disc-path> --out art/      ->  PNG
bleck model  export <disc-path> --out art/       ->  glTF   (when decodable)
bleck api    ...                                 ->  JSON   (the catalog)
```

This is not a new idea bolted on — it is what `bleck/api/` was published for,
and what `vision.md` means by "a GUI over the API, any language".

What it buys:

- Dimentio works on any asset `bleck` can decode, and **improves for free**
  as `bleck` learns more formats.
- Format bugs have exactly one place to be fixed, with the existing test suite
  around them.
- Dimentio stays a *renderer*, which is a much smaller and more fun program.
- Anyone can point another tool at the same exports — Blender opens glTF.

⚠️ The cost is a file-format hop and an export step. Acceptable: assets are
small (commonest texture sizes are 64×64, 32×32, 24×24), and an export cache
keyed on the source file's hash makes it a once-per-asset cost.

---

## Language: Rust

✅ **Recommended**, with conditions.

| | |
|---|---|
| **Graphics** | `wgpu` targets Vulkan, Metal and DX12 from one codebase — the three platforms, genuinely, not aspirationally |
| **Windowing** | `winit`, the same story |
| **UI** | `egui` for panels; immediate-mode suits a tool, and it composes with a `wgpu` viewport |
| **Distribution** | One static binary per platform. No runtime for a user to install |

⚠️ **The conditions, which are what keep this from becoming a liability:**

1. **No game-format parsing in Rust**, per the architecture above. This is the
   condition; the rest are hygiene.
2. **A separate crate directory and a separate CI job.** `bleck`'s own build,
   test and lint must not depend on a Rust toolchain being present, or a
   contributor with no interest in Dimentio pays for it on every commit.
3. **Dimentio may not become the only way to do something.** It is a lens on
   the CLI, not a replacement for it — a headless machine has to stay fully
   capable.

⛔ **Rejected: Python + Qt or moderngl.** One language is a real advantage and
it was weighed. But `bleck` ships as a *frozen PyInstaller binary with two
runtime dependencies*, and adding a GUI toolkit plus a GL binding to that is a
significant weight on every user who will never open Dimentio — including CI.
A separate binary keeps the CLI exactly as light as it is now. The JSON-API
boundary already exists precisely so a GUI need not be Python.

⛔ **Rejected: a web UI.** Would remove the install story, but the export step
then needs a local server, and file access from a browser is the least pleasant
part of the problem.

---

## Stages, in the order they pay off

### Stage 1 — a texture browser 🟢 buildable now

No 3D. A grid of every texture on the disc, searchable, with the source path and
format shown. 898 containers, 9,403 images, all decodable today.

This is worth building on its own merits: nothing in this project can currently
*look* at a texture, and the texture-edit work (`plan-textures.md`) has no
preview at all — you declare an `invert` and find out after a disc build.

- [ ] `bleck texture export` writing PNG, with a hash-keyed cache
- [ ] `bleck texture list` over the JSON API
- [ ] Rust + `winit` + `egui`, one window, a scrollable grid
- [ ] Click a texture, see path, format, size, and the mods that edit it

### Stage 2 — the viewport 🔶 needs Stage 4's research

Camera orbit/pan/zoom, preset backgrounds, a grid. Deliberately **after** model
decoding, because it cannot be validated before then. A cube renders fine and
proves nothing.

### Stage 3 — effects 🟢 mostly reachable

⚠️ **An effect is not a file.** It is a C entry point in the DOL that spawns a
live entity — `scripts/dump_effects.py` lists all **174** with their addresses,
and D183 measured one (`robo_beam`) frame by frame. So "display an effect" means
three different things, and only two are reachable:

| | |
|---|---|
| Its **textures** | ✅ `files/eff/effdata.tpl` (219 images), `effect.tpl` (41). Viewable as soon as Stage 1 works |
| Its **definition** | 🔶 `effdata.dat` sits beside `effdata.tpl` and is undecoded. Almost certainly the particle/emitter parameters, and it is *one file*, not a 1,687-file family — a far smaller target than the model container |
| Its **behaviour** | ⛔ Compiled PowerPC. A viewer cannot run it; only the game can. Listing name, address and textures is the honest ceiling |

🟢 So: show every effect by name with its textures, and treat `effdata.dat` as
the next research target after Stage 1 — it is the one that would turn a texture
list into an actual preview.

⚠️ **Do not simulate.** A hand-written approximation of an emitter would look
plausible and be wrong, and nobody would know which. If a preview cannot be
driven by the game's own data, it should say what it knows and stop.

### Stage 3b — sprites and 2D layouts

The `lyt/` layout system, animated. Reachable after Stage 1, independent of
model decoding.

### Stage 4 — decode the model container ⛔ the real blocker

Research, not engineering. What it needs:

- Identify the header and section table. `00 01 5F 5C` at offset 0 of
  `p_wii_mario` is a candidate size or offset — 89,948 against a 291,528-byte
  file.
- Locate `vcd_table` and read it as a GX vertex-component descriptor; that names
  the attributes and their formats, which is the key to everything after.
- Find the display lists, then the joint hierarchy the `*_skinShape` names imply.
- Only then, `animation_table`.

⚠️ **The method that keeps working here is `scripts/dolscan.py`** (D128, D130,
D133, D136): find the string, find who builds its address, read the code that
consumes it. The game's own loader is the specification, and it is on the disc.

### Stage 5 — animation playback

Only once Stage 4 has keyframes.

---

## What "done" means for Stage 1

- [ ] Every one of the 9,403 images exports without an error
- [ ] A texture's PNG round-trips: import it back and the CMPR data is unchanged
      for an identity edit (the same acceptance test as `plan-textures.md`)
- [ ] Dimentio opens on Windows, Linux and macOS from a single `cargo build`
- [ ] `bleck`'s own test suite still runs with no Rust toolchain installed
