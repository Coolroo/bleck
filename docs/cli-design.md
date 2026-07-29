# `bleck` — CLI Design

The single entry point for spm-modkit. Named for Count Bleck.

> *"But of course, Count Bleck's tools shall not be so easily understood!"*
> — the opposite of this document's goal.

Status: ✅ **implemented** (v0.1.0) — see D19. Reasoning behind it lives in
[`decision-log.md`](./decision-log.md); format facts in
[`disc-layout.md`](./disc-layout.md).

```bash
pip install -e .        # provides the `bleck` console script
bleck --help
```

Layout: `bleck/` package — `cli.py` (dispatch), `lz77.py`, `u8.py`,
`disc.py` (wraps `wit`/`dolphin-tool`), `formats.py` (detection),
`manifest.py`, `verify_roundtrip.py`.

---

## Why one CLI

Today the operations are scattered across `wit`, `dolphin-tool`, and a handful of
Python modules, each with its own conventions. A modder should not need to know
that map files are LZ77-wrapped U8 archives, that rebuilds require
`--align-files`, or that node order must be preserved to repack cleanly. `bleck`
owns that knowledge so users don't have to.

**Design goal: the common path is one command.** Wrapping an existing tool is
fine when it earns its place (`wit` for disc I/O), but the *interface* is ours.

---

## Command surface

Flat verbs, not nested groups — shorter to type, and the object type is
detectable from the file itself.

```
bleck info    <file>                 identify format, report structure
bleck extract <disc> [dest]          ISO/WBFS/RVZ -> extracted filesystem
bleck build   <dir> <out.iso>        extracted filesystem -> bootable ISO
bleck unpack  <archive> [dest]       LZ77+U8 -> files on disk
bleck pack    <dir> [archive]        files on disk -> LZ77+U8
bleck ls      <archive>              list archive contents
bleck verify  <path>                 round-trip check, no writes
bleck launch  <image>                boot a built image in Dolphin
bleck maps    [--chapter N]          list the game's maps, with chapters
bleck items   [--group NAME]         list the game's items, with ITEM_ID_*
```

Lower-level escape hatches, for when someone needs one layer only:

```
bleck lz decompress <in> [out]
bleck lz compress   <in> [out]
```

Flags added during implementation, beyond the original design:

- `--raw` on `pack` — write uncompressed U8, skipping the LZ77 layer entirely.
  Needed because verifying the container layer independently of compression is
  the fastest way to check a change (compression is ~12 s/MB).
- `--keep-iso` on `extract` — retain the ISO converted from an RVZ instead of
  discarding it, since that conversion costs ~70 s.
- `--launch` on `mod build` — boot the result immediately. The design goal above
  is "the common path is one command", and while the last step of testing lived
  outside `bleck` that was not true of the loop people actually run.
- `--output` on `mod build` — what to leave behind: `iso`, `wbfs`, `rvz`,
  `riivolution` or `none` (D86). These are a **table**
  (`bleck/mods/build/outputs.py`), not a chain of branches, and the flag's
  choices and help text are generated from it, so a fourth delivery route is a
  value rather than a new flag. `--no-image` is `--output none` internally.
- `--map` on `mod build` — boot the built disc straight into a named map,
  without editing the manifest (D64).

The command surface above also grew `bleck mod` (vendor, build, export, import,
schema), `bleck setup` (show, edits, apply) and `bleck mods`. The verbs stayed
flat; only the *object* families are grouped.

### `maps` exists so `code.maps` is usable (D51)

Attaching a script to a map needs the map's exact internal name, and there are
383 of them. Without a listing, writing `code.maps` means guessing or running
`ls` on an extracted disc — a poor answer immediately after shipping the feature
that needs it.

It reads the extracted base rather than shipping a name table, because **a map's
name is its archive's filename**: `files/map/aa4_01.bin` *is* `aa4_01`. The disc
cannot go stale and covers whichever region is extracted.

Map **ids** are the exception: nothing on the disc records them, so they were
dumped once from the game's `mapData[]` and committed as `mapcatalog.json`.

Following `info`'s reasoning below — the tool should answer questions about the
game, not just transform files.

### `items` is the same argument for `item:` selectors (D120)

The same shape as `maps`, one flag renamed: `--search`, `--group NAME` and
`--groups` where maps has `--search`, `--chapter N` and `--areas`. D114 deferred
it explicitly ("worth building when someone needs to browse 538 items"), and
what made it worth building was not browsing — it was that
`scripts/smoke_binary.py` had no way to prove `itemcatalog.json` was bundled,
because nothing on the CLI read it.

Two differences from `maps`, both consequences of where the data lives:

- **It reads no disc.** An item's id is in `itemids.py` and its names in
  `itemcatalog.json`, so it answers on a machine that has never seen the game.
  `maps` needs an extracted base for the names.
- **It has no `--json`.** `maps` has none either, and the CLI's only `--json`
  precedent is `bleck/api/`'s versioned pydantic contract — which D119 keeps
  `ItemId` out of, since an `IntEnum` field would rewrite `"item:fire_burst"` as
  a number on the next save.

### `launch` was added late, and belongs here (D36)

It is not disc I/O, so it does not wrap `wit`; it wraps the emulator. The point
is that every other step of edit → build → boot was a `bleck` command and the
last one was "go find Dolphin yourself".

⚠️ The emulator is a **different binary** from `dolphin-tool`, despite shipping
beside it. They are separate entries in the platform profiles with separate
overrides (`BLECK_DOLPHIN` vs `BLECK_DOLPHIN_TOOL`), because finding one where
the other was meant fails in a way that is hard to read.

### `info` is the discoverability tool

Formats here nest — a map file is LZ77 wrapping U8 wrapping TPL. `bleck info`
should unwrap and report the whole stack, so a user can point it at anything and
learn what they have:

```
$ bleck info work/extracted/eu0/files/map/aa1_01.bin
aa1_01.bin  424,712 bytes
  LZ77 (type 0x10) -> 1,131,524 bytes
    U8 archive, 13 entries (7 files)
      ./dvd/map/aa1_01/map.dat          561,630
      ./dvd/map/aa1_01/texture.tpl      188,576  TPL
      ...
```

---

## Design rules

**1. Auto-detect, never make the user declare the format.**
`unpack` accepts a bare U8 archive or an LZ77-wrapped one and does the right
thing. `tools/u8.py` already un-LZ77s transparently; the CLI generalizes that.

**2. ⚠️ Repacking must preserve node order — this constrains the interface.**
U8 node order is a flat depth-first listing, and D17's bit-exact round-trip
depends on preserving it. **Unpacking to a plain directory loses that order**,
because the filesystem does not preserve it and directory iteration order is not
guaranteed.

So `unpack` **must** write a manifest (`.bleck.json`) recording node order and
the original archive's layout, and `pack` must consume it when present. Without
this, `unpack` → `pack` produces a valid-but-different archive and we lose
byte-exact diffing — the main verification tool we have.

`pack` on a directory with no manifest should still work, emitting a sensible
depth-first order, but must **warn** that byte-exactness is not guaranteed.

**3. Always `--align-files` on rebuild.** Upstream requires it and omitting it
fails subtly. The user should never have to know it exists — `build` passes it
unconditionally.

**4. Destinations are optional and inferred.** `bleck unpack aa1_01.bin` unpacks
to `aa1_01/`. Convenience by default, explicit when needed.

**5. Refuse to overwrite without `--force`.** These operations consume disc
images and produce large artifacts; a silent clobber is expensive.

**6. Exit non-zero on verification failure**, so `verify` is usable in CI.

---

## Implementation notes

- Wraps `wit` for disc extract/build, and `dolphin-tool` for RVZ input (which
  `wit` cannot read — see D7). Both should be probed at startup with a clear
  error naming the missing tool and how to install it.
- Uses our own `lz77.py` / `u8.py`, not external libraries — libWiiPy stays a
  dev-only cross-check (D15/D16).
- Compression is slow (~12 s/MB). Any command that compresses should show
  progress and be skippable via `--store` (all-literals, instant, ~1.125×) for
  fast iteration. **This makes the all-literals encoder a real feature rather
  than a curiosity**, since disc space is abundant and iteration speed is not.
- Python entry point: `bleck` console script over a `bleck/` package; the current
  `tools/*.py` become its modules.

---

## Open questions — all three answered

- ~~Should `build` handle the Gecko loader code and `/mod/mod.rel` placement?~~
  ✅ **`bleck mod build` does**, and the loader is baked into `main.dol` with
  `wstrt --add-sect` rather than left to the emulator's cheat manager (D44).
  `bleck build` stayed a disc-level tool.
- ~~Does `pack` need to reproduce Nintendo's LZ77 exactly?~~ ⛔ **No** — D25
  booted a disc built with our ~0.25%-larger encoding and it rendered correctly.
  This was the untested part at the time; it is not any more.
- ~~Where does the setup-file ambiguity surface in the CLI?~~ ✅ `bleck mod
  build` warns when an overlay touches either copy and **names the one that
  matters** — the standalone `files/setup/<map>.dat` (D62). Better still,
  declare the change under `setup` in `mod.json` and let `bleck` write both.
