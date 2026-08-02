---
title: CLI reference
description: Every bleck command
---

```
bleck <command> [options]
```

All commands accept `--force` to overwrite existing output.

## Inspection

### `bleck info`

```bash
bleck info <file>
```

Identify a file and unwrap its nested formats. Works on disc images, archives,
compressed streams, textures and REL modules.

```bash
bleck info work/extracted/eu0/files/map/aa1_01.bin
```

### `bleck verify`

```bash
bleck verify <path>
```

Round-trip check: unpack and repack each archive, confirming the result is
byte-identical. Writes nothing. Accepts a file or a directory of `.bin` files.

Exits non-zero on mismatch, so it works in CI.

### `bleck maps`

```bash
bleck maps [--chapter N] [--search TEXT] [--areas]
```

Lists the game's maps by their internal names — the exact strings `code.maps`
takes.

```
$ bleck maps --chapter 5
  186  sp1_01     Ch 5-1  Land of the Cragnons
  187  sp1_02     Ch 5-1  Land of the Cragnons
```

The leading number is the game's own map id. `--areas` summarises every area in
playthrough order:

```
$ bleck maps --areas
  mac          19 maps  Flipside / Flopside
  he    Ch 1   35 maps  Lineland
  mi    Ch 2   43 maps  Gloam Valley
```

!!! note

    Reads the extracted base, so it needs `bleck extract` to have been run. Map
    names come from the disc itself — `files/map/sp1_01.bin` *is* the map
    `sp1_01`.

### `bleck items`

```bash
bleck items [--search TEXT] [--group NAME] [--groups]
```

Lists the game's 538 items — the ids and names an `item:` selector in
[`code.patches`](manifest.md) accepts.

```
$ bleck items --search fire_burst
  0x041  Fire Burst                 ITEM_ID_USE_HONOO_SAKURETU

1 of 538 items
```

Three columns: the id in hex, the way you would write it in a manifest; the
English name; and the game's own `ITEM_ID_*` constant. Any of the three — plus
the internal romaji name, here `HONOO_SAKURETU` — can be written as the
selector.

!!! note

    The **English column comes from your extracted disc**, read from
    `files/msg` under [`BLECK_BASE_DIR`](environment.md). `bleck` ships each
    item's message key rather than the game's own words, so with no disc
    extracted that column shows the internal name instead — and an English
    spelling like `fire_burst` matches nothing until one is. Ids, constants
    and internal names never need a disc.

`--search` matches on a substring of any of them, so a family comes back
together:

```
$ bleck items --search fire
  0x020  Fire Tablet                ITEM_ID_KEY_STG5_SEKIBAN3
  0x041  Fire Burst                 ITEM_ID_USE_HONOO_SAKURETU
  0x139  Fire Bro                   ITEM_ID_CARD_FIRE_BROS
  0x13c  Dark Fire Bro              ITEM_ID_CARD_MD_FIRE_BROS_BLK

4 of 538 items
```

A name it does not recognise gets the same suggestions a `mod.json` typo does,
and exits non-zero:

```
$ bleck items --search fire_brust
nothing matching 'fire_brust' in 538 items
  Did you mean 'fire_burst', 'fire_bros', 'fire_bro'?
```

`--groups` summarises by the constant's family, and `--group NAME` lists one:

```
$ bleck items --groups
538 items, by ITEM_ID_* group:

  CARD        256 items
  COOK         96 items
  USE          55 items
```

!!! note

    Unlike `bleck maps`, this needs **no extracted disc**: an item's id and its
    names both ship inside `bleck`. If the English names are unavailable the
    command says so and still lists every id and `ITEM_ID_*` constant.

### `bleck doors`

```bash
bleck doors [<map>]
```

What doors a map registers — the indices a [`door:`](manifest.md) selector
takes. With no map, lists every map that has one.

```
$ bleck doors he1_01
he1_01:
  1 scriptable door(s) -- `door:he1_01:<index>`
    [0] ie_doa in ie_naka  (interact, init, move)
  3 loading zone(s), which carry a destination
  and no scripts, so they cannot be patched:
    [0] doa2_l -> he1_02
    [1] doa1_l -> he1_01
    [2] ie_doa_02 -> he1_06
```

!!! warning "Two kinds of door, and only one is patchable"

    A **`DoorDesc`** has interact/init/move scripts and is what `door:` reaches.
    A **`MapDoorDesc`** is a loading zone: it carries a destination and **no
    scripts at all**, so there is nothing in it to patch.

    Across the whole game that is **35 scriptable doors** against **691 loading
    zones**, on 11 maps out of 368. A map with three visible doorways may expose
    one — Lineland Road does.

An index is a **position in the order the map registers its doors**, not an id
and nothing visible in game. `bleck` checks it when building, so a selector that
can never match is an error rather than a silent no-op at run time.

### `bleck model`

```bash
bleck model list [--search <text>] [--limit <n>]
bleck model export [--out <dir>] [--search <text>] [--min-coverage <pct>]
                   [--no-textures] [--no-animation] [--dense-morphs]
```

The game's character geometry. `list` shows every model whose mesh can be read;
`export` writes each as **glTF 2.0** (`.glb`) with its textures and animation
embedded, plus a `models.json` manifest that
[Dimentio](#dimentio-and-the-manifests) reads.

!!! tip "A `.glb` opens in software you already have"

    Double-click it in **Windows 3D Viewer**, or import it into **Blender** or
    any browser-based viewer. ⚠️ Blender opens in **Solid** viewport shading,
    which renders flat grey — switch to **Material Preview** (press `Z`) to see
    textures.

```
$ bleck model list --search mario --limit 3
p_wii_mario              R_Arm_skinShape                     324 verts     96 faces
```

Positions and normals are float32, and faces are polygons — mostly quads and
triangles, with occasional n-gons — cut into triangles on export. **864** of
the disc's models read; the six that fail a consistency check are skipped rather
than exported as noise.

!!! success "Whole models, and the coverage number that says so"

    Every shape in a file is exported, each indexing the slice of the vertex
    arrays the file says it does. **Median coverage is 100%** of a file's
    vertices and the mean 99.8%; `p_big_kuppa` reaches 99.9% of its 3,401.

    Every command prints the coverage and the manifest carries `"fragment":
    true` for the **4 models** still under 95% — those carry points no face
    draws. **Pass `--min-coverage 95`** to skip them.

#### One primitive per shape

A model file groups its faces into **shapes**, and each becomes its own glTF
primitive rather than being welded into one mesh — `e_lui_robo` exports as 91,
`e_2D_manera6` as 31. In Blender they arrive as separate material slots you can
isolate; in Dimentio the toolbar says how many there are and lets you hide any
of them.

!!! tip "A shape that looks wrong is usually a shape you can turn off"

    `e_lui_robo` carries a flat quad 130 units from the character. It is really
    in the file — a third-party rip of the same model simply left it out — and
    merged into one mesh it read as broken geometry attached to the robot. Split
    out, it is one checkbox.

#### Each shape draws with its own image

The image a shape is painted with is **read from the model file**, not guessed:
a shape lists the texture layers it draws with, each layer names a material, and
a material names its place in the texture bank stored beside the model. An
export carries one glTF material per image its shapes reach — `e_lui_robo`
writes 15 over 92 primitives — so a model arrives fully textured rather than
with one picture stretched across all of it.

**823 of 864 models export with textures.** The remaining 41 name no image at
all: every shape in them is drawn with vertex colour, which the file says
outright. `--no-textures` skips the images entirely for smaller files.

How each image is *sampled* is read from the file too. A layer states whether
each axis clamps, repeats or mirrors, and that becomes a real glTF sampler —
most of the game clamps, and an export that assumed repeating tiled art that was
never meant to tile. A layer may also carry a UV offset, scale or rotation, which
is written as `KHR_texture_transform`; Blender and three.js honour it, and a
reader that does not simply draws the untransformed image.

#### The texture is tinted per vertex, and the tint travels with it

Much of the game's art is stored **greyscale and coloured at draw time**: one
panel with rivets on it becomes the red one, the blue one and the green one
depending on a colour the model stores per vertex. An export carries that as
glTF `COLOR_0`, which every reader multiplies into the base colour — **4,609
shapes across 336 models**. Without it Brobot renders as a white robot with all
its detail intact and none of its paint; with it, a Luigi-green cap, red
thrusters and a brown moustache.

This is also how the **41 models that name no image at all** are drawn: the
game colours those from the vertices alone, and so does Dimentio.

Models whose vertices are all plain white carry nothing extra; that is 524 of
the 864, and a multiply by one is what glTF already assumes.

!!! note "40 shapes carry a second texture, and it is a mask"

    Four effect models — the two `MOBJ_EFF_mahojin` magic circles,
    `MOBJ_EFF_queen_tornade` and `MOBJ_EFF_uranoko` — have shapes that draw with
    two layers. The second one's **alpha** multiplies the first; its colour is
    never used. glTF has no slot that means this, so it is declared as
    `material.extras.spmMaskTexture` and only Dimentio composites it. **In
    Blender those shapes show the first layer**, which is as much as the format
    can honestly say.

!!! tip "Blender opens in Solid shading"

    Press `Z` and pick **Material Preview** — until then everything renders flat
    grey whether it carries a texture or not.

#### Animation

Animation in this game is **per-vertex morphing**, not skeletal — the engine
adds per-vertex offsets to a copy of the position array. That maps onto glTF
**morph targets**, so an exported `.glb` plays in any viewer with no skeleton
involved. In Blender the poses also appear as **Shape Keys**.

**Every clip the disc holds is written**, each as its own named glTF animation:
a full export writes **all 3,079 clips across 218 models**, where the previous
budget managed 2,256 and dropped 823.

Most targets are written in full; the ones that move only part of a shape are
written as glTF **sparse accessors**, and a pose that misses a shape entirely
becomes an accessor with no buffer view, which the specification defines as
zeros and which costs nothing. Pass **`--dense-morphs`** to write every target
in full for a viewer that will not follow a sparse accessor — the old shape,
and the old budget with it.

!!! warning "There is still a budget, and it says what it dropped"

    Every keyframe carries a weight for **every target in the file**, so a
    file's animation grows with the *square* of its clip count — 2,048 targets
    is 16 MB of weights before a single delta. Each file is capped at **2,048
    targets or 12 MiB of morph data**, whichever binds first, and clips are kept
    in file order until the budget runs out. Nothing on this disc reaches either
    cap; the largest is `p_luigi` at 10.2 MiB for its 1,466 poses.

    The command prints how many clips were written and how many were dropped,
    and `models.json` lists every clip with `"written": true` or `false`.

    With `--dense-morphs` the caps go back to **256 targets or 2 MiB**, which
    drops 823 clips — a dense target costs `vertices × 12` bytes whatever it
    moves.

Key times are **frames at 60 Hz** in the file and are written to the `.glb` as
seconds, since that is what glTF's samplers are defined in. The manifest carries
both.

A pose in this format is an **increment** on the pose before it, not a
standalone shape — the engine walks every track up to the current frame into one
buffer — and each of its offsets is a **sixteenth** of a unit. An export
accumulates them, so a clip plays as the game plays it. An earlier export did
neither, and every clip threw its vertices roughly two and a half times the
model's own width.

### `bleck effect`

```bash
bleck effect list [--search <text>] [--limit <n>]
bleck effect show <name> [--limit <n>]
bleck effect export [--out <dir>]
```

The 139 effects in `files/eff/effdata.dat` — what each is assembled from, how
long each part lasts, and the transform rows that place them.

```
$ bleck effect show chaos
chaos  (4 part(s))
  part   61  chaosA                              0  181
  part   62  chaosC                              1   61
  row   497     0.0000     0.0000     1.0000     0.0000  unit
  row   498     0.3090     0.9511     0.0000     0.0000  unit
```

The fourth column is a **duration in frames** at 60 Hz, counted inclusively —
181 is three seconds, 61 is one, and **1 is zero**. Five effects are entirely
single-frame, so a viewer treating the end as exclusive shows nothing at all
for them.

An effect's images are the 219 in `files/eff/effdata.tpl`, which
`bleck texture export` writes out. **Which of them a part draws is known**, and
so is **the shape it draws** — `effect export` records both. Each part gets a
`draws` list; each draw names an image (with its wrap mode and the material's
RGBA tint) and a `mesh`, indexing a `meshes` table at the top of the manifest.

!!! note "Effects are real geometry, not sprites on a quad"

    A mesh is one of the game's own GX display lists, exported as indexed
    triangles: `positions` (three per vertex, in the file's own units),
    `triangles`, and `uvs`/`colours`/`normals` where the geometry carries them.
    2,960 draws share just 360 display lists, which is why they are a shared
    table rather than a field on each draw.

    Dimentio's attack really is a four-pointed star with concave sides, built
    from one concave quadrant placed four times — the shape is geometry, and the
    texture only colours it.

!!! note "A part issues a set of draws, not one"

    560 of the 704 parts reach exactly one image; 35 reach none at all, and the
    rest reach up to twelve. `draws` is therefore a list, and a draw whose
    `image` is `-1` is a fact about that part rather than a gap in the data —
    the material says so explicitly. **`-1`, not `0`**: image 0 is a real
    image.

    The reference is not a field on the part. It is five sections away:
    `part → node → draw → subdraw → material → texture → image`, which is why
    seven candidate fields were ruled out before it was found.

### Dimentio, and the manifests

`texture export`, `model export`, `sound export` and `effect export` each write
a JSON manifest at the export root. Point them all at one folder and Dimentio —
the asset viewer that ships in this repo — can open it:

```bash
bleck texture export --out work/export
bleck model export   --out work/export
bleck sound export   --out work/export
bleck effect export  --out work/export
```

Each kind gets its own subtree, and inside it the disc's own directory layout is
mirrored, so an exported file sits where the file it came from does:

```
work/export/
  textures.json  models.json  sounds.json  effects.json
  textures/files/eff/effdata.tpl/0.png
  textures/files/map/aa1_01.bin/aa1_01/tex/wall.tpl/0.png
  models/files/a/p_wii_mario.glb
  sounds/files/sound/sys_title1_44k_lp.wav
```

A TPL becomes a *directory* because it holds several images; the leaf is the
image's index within it. A model or a stream is one file in and one file out, so
it keeps its name.

!!! note "Why not one folder"

    A full export is about **22,800 files** — 21,780 PNGs alone. Flat, that is a
    directory nothing opens usefully.

Characters a path component cannot legally hold — `<>:"|?*`, a trailing dot, a
reserved name like `nul` — are percent-escaped rather than dropped, so no two
disc paths can land on the same file and nothing is written outside the export
root.

The manifest is still the contract, not the directory listing: a path cannot say
what format an image was stored in, or how many faces a mesh had. Its `file`
field is a path relative to the export root.

### Rendering a model without opening anything

Dimentio can also render a model straight to a PNG and exit, which needs no
window, no GPU and no display — useful over SSH, in CI, or when you would rather
not open a viewer to check one file:

```bash
cargo run --release --manifest-path dimentio/Cargo.toml -- \
  shot work/export/models/files/a/p_wii_mario.glb --out mario.png
```

| option | |
|---|---|
| `--out <file.png>` | where to write. Required |
| `--size 512` | edge of one view, in pixels |
| `--angles 4` | views around the model, laid out as one contact sheet |
| `--clip 0 --frame 4` | hold one keyframe of one animation clip |
| `--background checkerboard` | `dark-grey`, `checkerboard` or `gradient` |

Four angles in one image rather than four files: most model defects — a stray
shape off to the side, a face that vanishes from behind, one part left
untextured — only show from one direction.

It also prints what it drew: triangle, shape and image counts, how much of the
sheet the model covers, and a **colour spread** figure — how far the drawn
pixels scatter about their mean tint, with brightness divided out.

!!! warning "Colour spread says the frame is not flat, and nothing more"

    It cannot tell a textured model from an untextured one, because **41 models
    carry no image at all and are coloured from their vertices** — `e_big_nok`
    has ten distinct tints and no texture whatever. Whether an image reached the
    surface is read from the file and printed as the image count; spread is
    there to catch a model that came out uniformly flat when it should not have.
    A greyscale texture reads as one tint too.

!!! warning "The backdrop is never white"

    A texture that decoded to near-white and a texture that failed to decode
    look identical against a white page. That is the case worth catching, so the
    default backdrop is a dark checkerboard.

### Rendering an effect across its timeline

A model's question is what it looks like from every side. An effect's is *when*
its parts run, so effects get their own command: one camera, several instants,
laid out in the same grid — or written as a looping animation.

```bash
cargo run --release --manifest-path dimentio/Cargo.toml --   reel --effect chaos --export work/export --out chaos.png
```

| option | |
|---|---|
| `--effect <name>` | which effect, as `bleck effect list` names it. Required |
| `--out <file.png>` | where to write. Required |
| `--export <dir>` | folder holding `effects.json`. Default `work/export` |
| `--frames 9` | frames sampled across the range, into one sheet |
| `--from 1` / `--to 46` | game frames to sample between, 1-based and inclusive |
| `--size 320` | edge of one frame, in pixels |

!!! tip "Write to a `.gif` and it animates"

    One cell per frame, looping. A model animation sweeps keyframes the same
    way — `dimentio shot model.glb --out m.gif --clip 0 --frame 0 --to 7` walks
    the clip from one fixed view rather than turning the model.

    A contact sheet is the wrong instrument for fast motion: `dmen_magic`'s
    spine wave has a five-frame period, and a nine-cell reel over 65 frames
    samples every eighth one and nearly aliases it away.

!!! warning "A GIF's unit is a whole centisecond"

    One game frame is 1.67 cs, so a 60 Hz effect cannot play at rate — the
    delay rounds up and the run reports the rate it really used. A GIF playing
    at two-thirds speed otherwise reads as a slow effect.

    Colour is quantised to 256 too. Use a GIF to watch motion and a PNG sheet
    to judge colour.

!!! warning "Frame 1 is often the least informative one"

    Effect scales rise from zero on their own curves, so **44% of draws are
    flat at frame 1** and 26 of the 139 effects draw nothing there at all.
    `item_fire` needs frame 10. If an effect looks empty, move the window with
    `--from` before believing it.

```
chaos — 4 part(s), 3.00s, 181 frame(s) long
  frame    1 at  0.000s — 4 active, 4 painted, 5.2% drawn
  frame   69 at  1.125s — 2 active, 2 painted, 2.5% drawn
  frame  136 at  2.250s — 1 active, 1 painted, 1.5% drawn
2 of 8 frame pair(s) differ
4 of 4 part(s) drew a decoded image
```

Frames run left to right, top to bottom, and the number of them is clamped to
the effect's real length — nine views of a one-frame effect would be nine
identical pictures.

!!! warning "The shapes are real; the arrangement is not"

    Each part is drawn as its own geometry, with the image it actually draws.
    **Where one part sits relative to another is not decoded** — the effect's
    node transforms are read but not yet applied, so a reel is an *exploded
    view*, with the parts deliberately separated so they can be told apart.
    Read a reel for *what* an effect draws and *when*, never for where it
    appears on screen.

    The report says so on every run, and also flags an effect whose geometry is
    far deeper than it is wide — one of the file's 360 display lists is 92×
    deeper than wide, so a fitted camera draws its visible face small.

!!! note "An empty frame has three possible causes"

    Five effects — `damage_star`, `sinigami_cannon`, `map_SOS`, `event_fly` and
    `mini_gameover` — draw no image on any part, and say so. Much of the effect
    bank is also very sparse art: one lightning sprite lights 20 of its 512
    pixels, and at a small `--size` a quad can miss every lit one. **Re-run at
    `--size 320` before concluding an effect is broken**; the report flags a
    blank frame and says the same.

Running `dimentio` with anything else — a folder, or nothing at all — opens the
window as usual.

## Archives

### `bleck ls`

```bash
bleck ls <archive>
```

List an archive's contents. Handles LZ77-wrapped archives transparently.

### `bleck unpack`

```bash
bleck unpack <archive> [dest]
```

Unpack to files on disk. Writes a `.bleck.json` manifest recording node order.

!!! warning

    Do not delete `.bleck.json`. U8 node order cannot be recovered from a directory
    listing, and byte-exact repacking depends on it. `pack` warns if it is missing.

### `bleck pack`

```bash
bleck pack <dir> [archive] [--store] [--raw]
```

| Flag | Effect |
|---|---|
| `--store` | Instant all-literals encoding, ~1.125× size |
| `--raw` | Write uncompressed U8, no LZ77 layer |

## Discs

### `bleck extract`

```bash
bleck extract <disc> [dest] [--keep-iso]
```

Extract a disc image's data partition. Accepts ISO, WBFS and RVZ; RVZ is
converted first, and `--keep-iso` retains that intermediate.

Defaults to `extracted/<name>`.

### `bleck build`

```bash
bleck build <dir> <out> [--format {iso,rvz,wbfs}] [--keep-iso]
```

Rebuild an extracted filesystem into a disc image. Format is inferred from the
output extension. `--align-files` is always passed to `wit`.

## Emulation

### `bleck launch`

```bash
bleck launch <image> [--batch] [--wait]
```

Boot a disc image in Dolphin. Returns as soon as the emulator starts, so it can
be chained after a build without pinning your terminal.

| Flag | Effect |
|---|---|
| `--batch` | Boot straight into the game, skipping Dolphin's game list |
| `--wait` | Block until the emulator exits, and return its exit code |
| `--fast` | Uncap emulation speed — see the warning below |
| `--state` | Load a Dolphin save state instead of booting cold |

```bash
bleck mod build my-mod work/out/my-mod.wbfs && bleck launch --batch work/out/my-mod.wbfs
```

!!! note

    This needs the Dolphin **emulator**, found via `BLECK_DOLPHIN` — a different
    executable from the `DolphinTool` used to convert images.

!!! warning "`--fast` stays fast"

    `--fast` uncaps the emulator so a cold boot reaches gameplay in about 6
    seconds instead of 45. It uncaps the **entire session**, gameplay included,
    and Dolphin offers no way to restore the cap part-way through — so a game
    launched this way is not playable, only observable.

    It is meant for unattended runs. To reach a level quickly and still play
    it, build with [`--map`](#bleck-mod-build) instead.

## Streams

### `bleck lz`

```bash
bleck lz {compress,decompress} <input> [output] [--store]
```

Raw LZ77, one layer only. Prints sizes if no output is given.

## Mods

### `bleck mod new`

```bash
bleck mod new <name> [--description ...] [--author ...]
```

Writes `mod.json`, an empty `overlay/`, and an empty table per kind —
`tables/enemies.csv` and `tables/coins.csv`, each a comment line and a header
row — which the manifest already points at. Add rows to place enemies or coins;
see [`tables`](manifest.md). A `doors` table is added by hand, since it needs a
`code` block alongside it.

### `bleck mod list`

Every registered mod, what it overrides, and its dependencies.

### `bleck mod vendor`

```bash
bleck mod vendor <name> <disc-path>
```

Copy a file from the base into the mod's overlay, resolving through archive
boundaries.

```bash
bleck mod vendor my-mod lyt/title.bin.uk/arc/timg/mario.tpl
```

!!! tip

    The leading `files/` is optional — `lyt/title.bin.uk` and
    `files/lyt/title.bin.uk` both work.

### `bleck mod status`

What a mod overrides, marked by kind — whole file, archive member, exclusive
claim or removal.

### `bleck mod chain`

The resolved install order, dependencies first.

### `bleck mod check`

```bash
bleck mod check <name> [--merge-binary] [--map NAME|ID]
```

Resolve and detect conflicts. **Writes nothing** — the fast inner-loop command.

### `bleck mod build`

```bash
bleck mod build <name> [out] [--output KIND] [--launch] [--map NAME|ID]
                       [--format {iso,rvz,wbfs}] [--merge-binary]
```

Stage the base, apply the chain, and write a disc image or a patch.

| Flag | Effect |
|---|---|
| `--output` | What to produce: `iso`, `wbfs`, `rvz`, `riivolution`, `none` |
| `--no-image` | Stage only, skip writing a disc image (same as `--output none`) |
| `--launch` | Boot the result in Dolphin once it is built |
| `--format` | Override the inferred image format |
| `--merge-binary` | Auto-merge disjoint edits to the same binary file |
| `--map` | Start the game at this map instead of the attract demo |

`--output riivolution` writes a patch and only the changed files instead of a
4.5 GB image — see [Running on a Wii](../guides/hardware.md). Without
`--output`, the kind is inferred from the output filename's extension.

`--launch` makes the whole edit-build-boot loop a single command:

```bash
bleck mod build my-mod work/out/my-mod.wbfs --force --launch
```

If the mod declares a `code` block, its script is compiled first and the
resulting module is packaged automatically.

`--map` takes a map name or the game's own id — `bleck maps` prints both —
and works on any mod, including one that ships nothing but a texture. It is
the same thing as `code.boot` in `mod.json`, set for one build:

```bash
bleck mod build my-mod --map he1_01 --launch    # by name
bleck mod build my-mod --map 26     --launch    # the same map, by id
```

## Scripts

Scripts compile to the game's own `evt` bytecode VM. See
[Scripting](../guides/scripting.md).

### `bleck script builtins`

```bash
bleck script builtins [--search TEXT]
```

List the game functions a script can call, grouped by subsystem, with argument
counts and documented signatures where upstream provides them.

### `bleck script index`

```bash
bleck script index <path-to-spm-headers/include>
```

Regenerate the builtin catalog from a `spm-headers` checkout. Rarely needed —
a catalog ships with `bleck` — but useful when upstream documents more
functions.

### `bleck script check`

```bash
bleck script check <file.evt>
```

Parse and compile a script, reporting the scripts it declares and the game
functions it calls. **Needs no compiler and no symbol list**, which makes it the
fast inner loop — most iterations are a syntax error or a mistyped name, and
neither needs a disc to find.

### `bleck script dump`

```bash
bleck script dump <file.evt>
```

Print the C that the script compiles to. Useful for understanding how a
construct lowers, and for reporting bugs.

### `bleck script build`

```bash
bleck script build <file.evt> [-o out.rel] [--target eu0] [--module-id 2]
```

Compile a script all the way to a loadable `.rel` module.

| Flag | Effect |
|---|---|
| `-o`, `--output` | Where to write the module (default: alongside the script) |
| `--target` | Game version to resolve function names against (default `eu0`) |
| `--module-id` | REL module id; the game's own REL is 1 (default `2`) |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | User-fixable error, or verification failure |
| `130` | Interrupted |

## Placements

### `bleck setup`

```bash
bleck setup show <map> [--all] [--json]
bleck setup list [--min-enemies N]
```

What a map places, and which maps place anything. Reads the extracted base,
so it needs no build and no emulator.

#### JSON in, JSON out

Three subcommands exist for programs rather than people. Every document is
validated against a published schema, so an integration finds out about a typo
immediately rather than at build time.

```bash
bleck setup show <map> --json     # what a map currently places
bleck setup edits <mod> --json    # what a mod declares
bleck setup apply <mod> --json FILE   # write declared edits back; - for stdin
bleck setup schema --of edits     # JSON Schema for the above
```

A whole edit loop, without touching `mod.json` by hand:

```bash
bleck setup edits hard-lineland --json > edits.json
# ...change it in your editor, or your program...
bleck setup apply hard-lineland --json edits.json
```

or piped straight through:

```bash
bleck setup edits hard-lineland --json | your-tool | bleck setup apply hard-lineland --json -
```

!!! note "Reading and editing are different shapes"

    `show` returns **every** slot with the enemy name resolved; `edits` returns
    only the slots a mod changes. A read is not an edit turned around — sending
    a whole map back would rewrite a hundred slots to change one, and lose the
    difference between "left alone" and "deliberately set to what it already
    was".

!!! warning "`apply` replaces, it does not merge"

    The mod's whole `setup` block is replaced by the document you send. Merging
    would need a rule for "the incoming JSON omits a map — delete it or keep
    it?", and either answer surprises half of callers. An editor holds the whole
    document anyway.
