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
`tables/enemies.csv` and `tables/items.csv`, each a comment line and a header
row — which the manifest already points at. Add rows to place enemies or coins;
see [`tables`](manifest.md).

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
