---
title: Environment variables
description: Everything bleck can be configured with
---

This is the complete list of variables `bleck` reads.

!!! tip

    [`bleck doctor`](cli.md#bleck-doctor) prints all of them with their current
    values, alongside every external tool and whether it runs. A variable
    pointing at a path that does not exist is reported as a misconfiguration,
    naming the variable — `bleck` will not quietly search elsewhere for it.

## Paths

`BLECK_BASE_DIR` <span class="pf-default">default: `work/extracted/eu0`</span>

:   The pristine extracted base game. Never written to.


`BLECK_MODS_DIR` <span class="pf-default">default: `mods`</span>

:   Where mods live. Dependencies resolve against this directory.


`BLECK_BUILD_DIR` <span class="pf-default">default: `build`</span>

:   Where mod staging and output images go.


`BLECK_EXTRACT_ROOT` <span class="pf-default">default: `extracted`</span>

:   Where `bleck extract` writes when no destination is given.


## External tools

`BLECK_WIT`

:   Full path to the `wit` binary, if it is not on PATH.


`BLECK_DOLPHIN_TOOL`

:   Full path to `dolphin-tool` / `DolphinTool.exe`, if it is not on PATH. Used to
    read and write RVZ.


`BLECK_DOLPHIN`

:   Full path to the Dolphin **emulator**, used by `bleck launch`.


!!! warning

    `BLECK_DOLPHIN` and `BLECK_DOLPHIN_TOOL` point at **different executables** that
    ship in the same folder. `DolphinTool` converts and inspects images; `Dolphin`
    boots them. Pointing either at the other's binary fails confusingly.

`BLECK_WSTRT`

:   Full path to `wstrt`, from **Wiimms SZS Toolset** — a separate package from
    `wit`. Used to embed the Gecko loader into a code mod's disc, so the mod runs
    with no emulator configuration.


`BLECK_GECKO_DIR` <span class="pf-default">default: `gecko`</span>

:   Directory holding per-version loader codelists (`loader.eu0.txt`, …). **Not
    shipped with `bleck`** — the SPM loader code is GPLv3. Pre-assembled loaders
    come from
    [spm-rel-loader](https://github.com/SeekyCt/spm-rel-loader) (`loader/`).


`BLECK_PPC_GCC`

:   Full path to the PowerPC cross-compiler used to build code and script mods,
    normally devkitPPC's `powerpc-eabi-gcc`. Only needed when it is not in a
    standard install location.


`BLECK_SYMBOLS_DIR` <span class="pf-default">default: `symbols`</span>

:   Directory holding per-version symbol lists (`spm.eu0.lst`, …). These resolve
    the game functions a script calls, and are **not shipped with `bleck`** —
    get them from
    [spm-headers](https://github.com/SeekyCt/spm-headers) (`linker/`).


## Output

`NO_COLOR`

:   Set to any value to disable coloured output. Follows
    [no-color.org](https://no-color.org).


## Setting them

=== "Linux / macOS"

    ```bash
    export BLECK_BASE_DIR="/mnt/games/spm/eu0"
    export BLECK_DOLPHIN_TOOL="/Applications/Dolphin.app/Contents/MacOS/dolphin-tool"
    export BLECK_DOLPHIN="/Applications/Dolphin.app/Contents/MacOS/Dolphin"
    ```

=== "Windows"

    ```powershell
    $env:BLECK_BASE_DIR = "D:\games\spm\eu0"
    $env:BLECK_DOLPHIN_TOOL = "C:\Program Files\Dolphin\DolphinTool.exe"
    $env:BLECK_DOLPHIN = "C:\Program Files\Dolphin\Dolphin.exe"
    ```


On Windows, use `setx` instead of `$env:` to persist across sessions.

!!! tip

    Tool overrides take priority over PATH, so you can point at a specific build
    without changing your system configuration.
