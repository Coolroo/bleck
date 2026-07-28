---
title: Code mods
description: Running custom PowerPC code — work in progress
---

!!! note

    **Looking to add behaviour to the game? Start with
    [Scripting](../guides/scripting.md).** It is integrated into `bleck mod build`,
    needs far less setup, and covers event logic — cutscenes, NPCs, items, doors,
    map triggers.

    This page is about **native hooks**: changing how an existing game function
    behaves. Scripting cannot do that, and the two work together in one mod.

Add a `sources` entry to the mod's `code` block:

```json title="mod.json"
{
  "code": {
    "script":  "scripts/main.evt",
    "sources": ["src/hooks.c"],
    "target": "eu0"
  }
}
```

Either half is optional; at least one is required. `bleck mod build` compiles
them into a single `mod.rel`.

## Several code mods on one disc

You can install more than one. `bleck` compiles them **together** into the one
`mod.rel` the disc carries — so a chain like `hard-mode -> extra-enemies` works
the same as a single mod, and both mods' scripts run.

Two mods may both declare `script main`; each gets its own namespace in the
generated module, and every mod's `main` is started.

Three things are decided per **disc** rather than per mod, and `bleck` refuses
rather than picking for you:

| If two mods… | You get |
|---|---|
| both set `code.boot` | an error naming both — a disc starts in one place |
| set different `code.target` | an error — addresses differ per game version, and a mixed build would call the wrong ones without complaining |
| have names that reduce to the same identifier, like `hard-mode` and `hard mode` | an error naming both mods |

!!! note "Why this is unusual"

    Elsewhere in the Super Paper Mario scene, running two code mods at once is
    an unsolved problem — the loader opens exactly one `/mod/mod.rel`, and
    attempts to chain several at runtime have not worked out.

    That limit is real, and `bleck` does not fight it. It produces **one** REL,
    exactly as before; the merging happens at compile time, where there is
    nothing to go wrong at runtime.

!!! note "One `mod_prolog` per disc"

    `bleck` calls `mod_prolog` when the module loads, so a merged disc has
    exactly one. If two mods define it you get an error naming both, rather
    than a linker message about a symbol you did not write.

    Move the extra work into a sequence hook, or combine the two mods.

## Writing a hook

`bleck` owns `_prolog` — it has to install its sequence hooks first. Your code
defines `mod_prolog` instead, and `bleck` calls it:

```c title="src/hooks.c"
extern MapData *mapDataPtr(const char *name);

void mod_prolog(void)
{
    MapData *flipside = mapDataPtr("mac_01");
    /* ... */
}
```

!!! warning

    `mod_prolog` runs at **load time**, when the game is barely up. Patching
    pointers and reading tables is fine; anything touching live engine state is
    not — that belongs in a sequence hook. See the timing table in the
    project's `docs/hook-points.md`.

Function names are resolved by `elf2rel` against the symbol list, exactly like
a script's builtin calls, so no addresses appear in your source.

!!! note

    `BLECK_HEADERS_DIR` supplies `-I` for your sources — point it at
    [spm-headers](https://github.com/SeekyCt/spm-headers)' `include`. Without
    it, declare what you use `extern` yourself.


## What a code mod is

Not a patched executable. Your code becomes a **separate module** loaded
alongside the game, hooking existing functions by address:

```
freestanding PowerPC C/C++
  → compile (no libc)
  → link relocatably against a per-version symbol list
  → ELF → REL
  → placed on the disc as /mod/mod.rel
  → a Gecko code loads and runs it at boot
```

The game itself is never modified.

!!! info

    This is why the community decompilation being ~2.3% complete does not matter.
    Code mods link against **symbol addresses**, not source, so an incomplete decomp
    is a documentation source rather than a blocker.

## Prerequisites

| | |
|---|---|
| PowerPC cross-compiler | `gcc-powerpc-linux-gnu`, or devkitPPC |
| `pyelf2rel` | ELF → REL conversion (pure Python, on PyPI) |
| [`spm-headers`](https://github.com/SeekyCt/spm-headers) | Symbol lists and struct definitions |
| [`spm-rel-loader`](https://github.com/SeekyCt/spm-rel-loader) | The Gecko loader code |

## Building a REL by hand

This works today, verified on Debian's cross-compiler:

```bash
MACHDEP="-mno-sdata -DGEKKO -mcpu=750 -meabi -mhard-float"
NOPIC="-fno-pic -fno-PIE"

powerpc-linux-gnu-gcc -c main.c -o main.o \
    -nostdlib -ffreestanding -ffunction-sections -fdata-sections -O3 -Wall \
    $MACHDEP $NOPIC

powerpc-linux-gnu-gcc main.o -o main.elf \
    -r -e _prolog -u _prolog -u _epilog -u _unresolved \
    -Wl,--gc-sections -nostdlib $MACHDEP

elf2rel -i main.elf -s spm-headers/linker/spm.eu0.lst -o mod.rel --rel-id 2
```

Verify the result with `bleck` itself:

```bash
uv run bleck info mod.rel
```

```
mod.rel  264 bytes
  REL v3 (13 sections)
```

!!! warning

    **`-fno-pic -fno-PIE` is mandatory** with a distro compiler. Debian's GCC
    defaults to PIE and devkitPPC does not; without these flags you get
    `R_PPC_REL16_HA` relocations and `pyelf2rel` fails with:

    ```
    UnsupportedRelocationError: Unsupported relocation type 252
    ```

    The error gives no hint about the cause, so it is worth knowing up front.

Only `-mgcn` from the upstream flag set is rejected — it is devkitPPC-specific
and safe to drop.

## The loader

Placing `mod.rel` on the disc is not enough. A **Gecko code** is what actually
executes it, and it ships pre-assembled per region in
`spm-rel-loader/loader/*.txt`.

For Dolphin, Gecko codes go in `User/GameSettings/R8PP01.ini`.

## Known limitations

??? note "One code mod per disc"

    The loader loads exactly one file, `/mod/mod.rel`. Two mods in a chain both
    wanting code would collide, and unlike an asset conflict the second simply
    would not exist.

    [`chainrel`](https://github.com/SeekyCt/chainrel) solves this properly and
    is planned once single code mods work.

??? note "ABI risk with a distro compiler"

    devkitPPC targets `powerpc-eabi`; Debian's targets `powerpc-linux-gnu`
    (SysV). `-meabi` asks for EABI conventions, but differences around
    small-data registers and struct passing could produce code that builds
    cleanly and misbehaves at runtime.

    **This has not been proven by running it yet.** If it fails, the fallback is
    building on Windows with real devkitPPC and packaging with `bleck` — the
    REL is just a file the overlay places.

??? note "Licensing"

    `spm-rel-loader` is **GPLv3**, including the loader code. `spm-headers` is
    MIT except its `mod/` folder. `bleck` is currently unlicensed, so nothing
    upstream has been vendored into it.
