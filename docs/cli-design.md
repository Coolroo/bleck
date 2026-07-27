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

## Open questions

- Should `build` handle the Gecko loader code and `/mod/mod.rel` placement, or
  stay purely a disc-level tool? Leaning toward a separate `bleck mod` verb once
  the REL workflow is actually exercised.
- Does `pack` need to reproduce Nintendo's LZ77 exactly to be useful? Probably
  not — see D16 — but this is untested against a running game.
- Where does the setup-file ambiguity (D13, two byte-identical copies) surface in
  the CLI? A user editing a setup file needs to be told both copies exist.
