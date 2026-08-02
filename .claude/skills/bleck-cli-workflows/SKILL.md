---
name: bleck-cli-workflows
description: Use when running the bleck CLI for anything — checking or building a mod, extracting or rebuilding a disc, exporting textures/models/sounds/effects, listing maps/items/doors/symbols. The command map, the flags that matter, and the traps (--mods-dir, `build` vs `mod build`, --align-files, and one advertised command that does not exist).
---

# `bleck` CLI workflows

Everything runs as `uv run bleck …`. Tool paths come from `.env`, loaded
automatically from anywhere in the checkout — **do not export `BLECK_*` per
command**. Copy `.env.example` if `.env` is missing. The real environment still
wins, so a one-off override works.

## The command map

There is **no `disc`, `emulate` or `inspect` command** — those are module names
in `bleck/cli/commands/`, and their subcommands are registered at the top level.

| group | commands |
|---|---|
| inspect a file | `info`, `verify` |
| game data | `maps`, `items`, `doors`, `setup {show,list}`, `symbols {list,compare,export}` |
| assets | `texture {list,export}`, `model {list,export}`, `effect {list,show,export}`, `sound {list,export}` |
| archives | `ls`, `unpack`, `pack`, `lz` |
| mods | `mod {new,list,vendor,status,chain,pack,install,export,import,schema,check,build}` |
| scripts | `script {check,dump,build,builtins,index}` |
| discs | `extract`, `build`, `launch` |

⚠️ **`bleck build` and `bleck mod build` are different commands.** `build` takes
an extracted filesystem to a disc image; `mod build` takes base + resolved chain
to a disc image or patch. Typing the wrong one is not an error, just a surprise.

## ⚠️ `--mods-dir example-mods`, every time

**Every mod this repo's docs name lives in `example-mods/`, not `mods/`** (D147).
`BLECK_MODS_DIR` defaults to `mods/`, so a bare `bleck mod check mr-l` reports
"no mod named".

```bash
uv run bleck mod check mr-l --mods-dir example-mods
uv run bleck mod build mr-l --mods-dir example-mods --force
```

`--force` and `--mods-dir` are attached to **every** parser, including nested
ones — `bleck/cli/shared.py` exists because a flag that works on `mod list` but
not `mod build` is worse than one that exists nowhere.

⛔ **`scripts/ingame.py` has no `--mods-dir`.** It shells out to `bleck mod build`
without one, so set `BLECK_MODS_DIR` in the environment for that. See
`ingame-testing`.

Write a **new** probe under `mods/` — git-ignored scratch, that is what it is
for. Copy it to `example-mods/` (dropping `overlay/`) only once it earns its keep.

## The mod loop

```bash
uv run bleck mod new my-mod
uv run bleck mod check my-mod                 # resolve + detect conflicts; writes nothing
uv run bleck mod status my-mod                # what it overrides
uv run bleck mod chain my-mod                 # resolved install order
uv run bleck mod build my-mod work/build/my-mod.wbfs --force
```

`mod build` flags worth knowing:

| flag | |
|---|---|
| `--output KIND` | `iso` · `wbfs` (~424 MB, every Dolphin build reads it) · `rvz` (~249 MB, needs Dolphin 5.0-12188+) · `riivolution` (patch XML + changed files, real Wii from SD) · `none` |
| `--map NAME\|ID` | boot straight to a map instead of the attract demo (D52) |
| `--merge-binary` | auto-merge disjoint edits to one binary file. **Off by default**: byte-disjoint edits can still be semantically incompatible |
| `--no-embed-loader` | leave the Gecko loader out of the disc |
| `--base-image PATH` | an untouched image for a Riivolution patch to sit on |
| `--launch` | boot the result once built |

**Share builds as `.wbfs`.** RVZ needs Dolphin 5.0-12188+ (2020); plain 5.0
stable rejects it as "not a GC/Wii ISO".

## Discs

```bash
uv run bleck extract work/roms/spm.wbfs work/extracted/eu0
uv run bleck build work/extracted/eu0 work/build/out.wbfs
uv run bleck launch work/build/out.wbfs
```

- **Work on the extracted filesystem.** ISO/WBFS/RVZ are transport formats —
  convert once, then work on files.
- ⚠️ **`--align-files` is mandatory on every `wit` rebuild** and fails subtly
  when omitted. `bleck/backends/disc.py` already passes it; the trap only bites
  when you call `wit` by hand.
- `wit` cannot read **RVZ**. `bleck extract --keep-iso` keeps the ISO it
  converted from one, since the conversion costs ~70 s.
- **Anchor to PAL rev 0 (`eu0`)** for anything address-dependent.

## Asset exports

```bash
uv run bleck texture export --out work/export --search koopa
uv run bleck model   export --out work/models --min-coverage 95
uv run bleck sound   export --out work/export --seconds 10
uv run bleck effect  export --out work/export
```

- Defaults: `--out work/export` for texture/sound/effect, **`work/models`** for
  model. All but `effect` take `--search`.
- Exports land in directories that **mirror the disc** (D233).
- `sound export` writes the full **566 MB** unless `--seconds` caps each track.
- `model export --min-coverage 95` gives the 132 models known to render
  correctly. `--no-textures`, `--no-animation` and `--dense-morphs` are there
  for viewers that will not read sparse accessors.

## ⛔ `bleck toolchain install` is not a command

It is advertised in **`bleck/backends/toolchain.py:100`** and in all three of
`bleck/platforms/{linux,macos,windows}.py`, and `tests/test_code_mods.py:345`
asserts the string appears. There is no `toolchain` subcommand. This is an
**open bug** (D239, and `docs/macos.md` lists the fix per file), not a
workflow — install devkitPPC directly and point `BLECK_PPC_GCC` at it.

## Related

- `ingame-testing` — booting what you just built and reading it back
- `linting-and-ci` — before finishing any change to `bleck/`
- `arm64-container` — running all of this on Apple Silicon
- `catalog-dumps` — where `maps`, `items` and `doors` get their names
