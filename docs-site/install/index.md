---
title: Overview
description: What bleck needs, on any platform
---

`bleck` ships two ways: a **single-file executable** that needs no Python, or
the Python package. Either way it shells out to two external tools for disc I/O.

## The binary

Download the build for your platform from the repository's Actions artifacts and
run it — there is nothing to install and no Python needed.

```bash
./bleck --help
```

Builds are produced for Linux x86-64, Windows x86-64 and macOS arm64 on every
change, and each is smoke-tested before it is published: a packaging mistake
produces a binary that starts happily and then reports an empty catalog, which
looks like a corrupt install rather than a build bug.

## The Python package

Needed if you want to work *on* `bleck` rather than with it, or if your platform
has no published build. Python 3.10+, and two small runtime dependencies
(`pydantic` for the JSON API, `pyyaml` for `bleck.yml`).

## Requirements

| | Needed for |
|---|---|
| **Python 3.10+** | `bleck` itself — *not needed for the binary* |
| **`wit`** (Wiimms ISO Tools) | `extract`, `build` |
| **`dolphin-tool`** | Reading and writing RVZ |
| A Super Paper Mario disc image | Everything. Not distributed with `bleck`. |

!!! note

    `dolphin-tool` is only required for RVZ. If you work in ISO or WBFS, `wit`
    alone is enough.

## Pick your platform

<div class="grid cards" markdown>


</div>


## If a tool cannot be found

`bleck` searches your PATH, then platform-specific locations. When it fails it
tells you what it looked for:

```
bleck: dolphin-tool not found (looked for: dolphin-tool, DolphinTool)
  DolphinTool ships inside Dolphin.app
  (/Applications/Dolphin.app/Contents/MacOS/DolphinTool).
  Install with `brew install --cask dolphin`, or set BLECK_DOLPHIN_TOOL to its full path
```

Point at it directly with an environment variable:

=== "Linux / macOS"

    ```bash
    export BLECK_WIT="/path/to/wit"
    export BLECK_DOLPHIN_TOOL="/path/to/dolphin-tool"
    ```

=== "Windows"

    ```powershell
    $env:BLECK_WIT = "C:\path\to\wit.exe"
    $env:BLECK_DOLPHIN_TOOL = "C:\Program Files\Dolphin\DolphinTool.exe"
    ```


Every configurable path is listed in [Environment](../reference/environment.md).
