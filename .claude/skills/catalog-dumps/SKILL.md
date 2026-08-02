---
name: catalog-dumps
description: Use before regenerating any committed catalog (maps, items, NPCs, doors, effects, script builtins) or when wondering where a name in bleck's output came from. Says which dumps need a booted game and which read a file, and why these are generated once and committed rather than recomputed.
---

# Catalog dumps

`bleck` ships several JSON catalogs so a user gets names, not raw ids. **They
are generated once and committed.** The tables they read never change — the
game is from 2007 — so recomputing one costs a two-minute boot to produce bytes
you already have.

Check whether the artifact already exists before regenerating it.

## Which needs a running game

| script | source | output |
|---|---|---|
| `dump_effects.py` | ⚡ **the extracted DOL** — no game | prints; 174 effects |
| `dump_items.py` | ⚡ **the extracted DOL** by default (`--boot` for a game) | `bleck/formats/itemcatalog.json` + `bleck/formats/itemids.py` |
| `dump_builtins.py` | ⚡ **`catalog.json` + `bleck/script/evt.py`** — no game | `docs-site/scripting/{builtins,storage}.md` |
| `dump_maps.py` | 🐌 **a booted game** | `bleck/backends/mapcatalog.json` |
| `dump_npcs.py` | 🐌 **a booted game** | `bleck/formats/npccatalog.json` |
| `dump_doors.py` | 🐌 **a booted game** | `bleck/backends/doorcatalog.json` |

## ⚠️ The booted three do not build anything

They take an **already-built** image out of `work/build/<mod>.wbfs` and refuse
with `no image at …; build one first` otherwise. Build it yourself, and
remember every mod they name lives in `example-mods/` (D147):

```bash
uv run bleck mod build map-hook --mods-dir example-mods --force
uv run python scripts/dump_maps.py  --out bleck/backends/mapcatalog.json
uv run python scripts/dump_npcs.py  --out bleck/formats/npccatalog.json \
    --headers work/upstream/spm-headers/include/spm/npcdrv.h
uv run bleck mod build nop --mods-dir example-mods --force
uv run python scripts/dump_doors.py --out bleck/backends/doorcatalog.json
```

Common flags on all three: `--mod NAME` (which built image to boot),
`--out PATH` (default: stdout), `--seconds N` (default 90).

⚠️ `dump_items.py`'s `--mod` default is `attended`, which is **not** in
`example-mods/`. It only matters under `--boot`; the default DOL path ignores it.

## What each one is actually reading

**`dump_maps.py`** — `mapData[]` at `0x804031B8` (eu0), `MAP_ID_MAX` = `0x1D4`.
Nothing on the disc records the id *ordering*, which is why this needs a game.
The table is filled by the REL prolog long before gameplay, so it does not wait
for a map to load.

**`dump_npcs.py`** — template *and* tribe tables. ⚠️ A setup entry's `type` is a
**template** index, not an `NPC_*` constant from `npcdrv.h`; those are *tribe*
ids. Both are dumped so `setup.type → template.tribeId → tribe.animPoseName`
can be followed.

**`dump_doors.py`** — ⚠️ **a map has TWO door tables and they are not
interchangeable** (D138):

```
DoorDesc     0x58  interact/init/move scripts.  `door:` reaches these
MapDoorDesc  0x20  destMapName/destDoorName.    NO scripts at all
```

Reporting only the first makes a map look emptier than it is. A `door:`
selector's index is a **position in the array a map registers**, not an id and
not visible in game (D103) — a since-deleted probe carried a `door:he1_01:9`
patch that addressed nothing (D137). Needs a game because the descriptor arrays
are reached through `MapData.initScript`, whose address is a constant *inside*
the init script's bytecode; `mapDataPtr` is populated for every map by the REL
prolog (D88), so one boot covers the whole game.

**`dump_items.py`** — `itemDataTable` holds pointers, so names are three lookups
away. Two outputs from **one read**, so they cannot drift; `tests/test_items.py`
regenerates the second from the first to prove it. ⚠️ `itemName` is the
*internal* romaji name (`HONOO_SAKURETU`); the English one is a second lookup
through `nameMsg` into `files/msg/<lang>`, which is why the script reads those
too. `--enum-out` requires `--headers` and says so *before* anything slow.

**`dump_effects.py`** — an effect is a fourth kind of entity and nothing
enumerated them before, which is why the Pure Hearts went unfound through four
exhaustive searches (D171). They are not named assets on the disc: every effect
entry function calls `effEntry` at `0x800616dc` and stores a name pointer into
`EffEntry+0x14`, built `lis`/`addi` — so registers must be tracked, not
pattern-matched (the same reason `dolscan xref` exists). Takes about a second;
there is no reason to cache it.

```bash
uv run python scripts/dump_effects.py --grep beam
```

**`dump_builtins.py`** — regenerates the two language-reference pages.

```bash
uv run python scripts/dump_builtins.py
uv run python scripts/dump_builtins.py --check    # what CI runs
```

⛔ **Never hand-edit `docs-site/scripting/builtins.md` or `storage.md`.** Both
carry a generated header saying so. `--check` regenerates into memory and
compares, so a catalog change not followed by a regeneration fails
`.github/workflows/docs.yml` rather than shipping a quietly-wrong page. The one
non-derived part is the per-module prose in `scripts/module_notes.py`, kept
apart so the single file needing human judgement is the single file a reviewer
reads. ⛔ Per-*function* descriptions are deliberately absent: 443 builtins,
zero upstream descriptions, and a reference is believed (D179).

## The catalogs are what the release smoke test checks

`scripts/smoke_binary.py` asserts that each catalog is bundled in the frozen
binary — reading the expectation out of **that catalog's own first row**, never
a hard-coded name. See `linting-and-ci`.

## Related

- `ingame-testing` — the `Session` these three reuse, and its traps
- `decode-by-disassembly` — how `dump_effects.py`'s technique generalises
- `slow-command-discipline` — before spending a boot
