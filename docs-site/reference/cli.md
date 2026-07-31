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
                   [--no-textures] [--no-animation]
```

The game's character geometry. `list` shows every model whose mesh can be read;
`export` writes each as **glTF 2.0** (`.glb`) with its texture and animation
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
triangles, with occasional n-gons — fanned into triangles on export. **864** of
the disc's models read; the six that fail a consistency check are skipped rather
than exported as noise.

!!! danger "Most are fragments, and a fragment renders as stretched geometry"

    One shape record is read per file, and a character file names dozens.
    **Median coverage is 13.6%** of a file's vertices — `p_big_kuppa` reaches
    three of its 3,401, and looks like a stretched mess. Every command prints
    the coverage and the manifest carries `"fragment": true`.

    **Pass `--min-coverage 95`** for the **132 models known to render
    correctly**.

#### Animation

Animation in this game is **per-vertex morphing**, not skeletal — the engine
adds per-vertex offsets to a copy of the position array. That maps onto glTF
**morph targets**, so an exported `.glb` plays in any viewer with no skeleton
involved. In Blender the poses also appear as **Shape Keys**.

One clip per file is written; extra clips are another full set of dense targets.
Textures come from image 0 of the bank beside each model — ⚠️ **which image a
shape actually uses is not decoded**, so a bank holding several may pair the
wrong one.

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

!!! warning "Which image a part draws is not known"

    An effect's images are the 219 in `files/eff/effdata.tpl`, which
    `bleck texture export` writes out. **Nothing yet says which of them a given
    part uses.** Six candidate fields have been ruled out; the structure,
    timing and image bank are all readable, and the binding between them is not.

### Dimentio, and the manifests

`texture export`, `model export` and `effect export` each write a JSON manifest
beside their output. Point all three at one folder and Dimentio — the asset
viewer that ships in this repo — can open it:

```bash
bleck texture export --out work/export
bleck model export   --out work/export
bleck effect export  --out work/export
```

The manifest is the contract, not the directory listing: a filename cannot say
which disc file an asset came from, which archive member, or what format it was
stored in.

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
