---
title: Overview
description: What bleck needs, on any platform
---

`bleck` is a Python package with **no runtime dependencies**. It shells out to
two external tools for disc I/O.

## Requirements

| | Needed for |
|---|---|
| **Python 3.10+** | `bleck` itself |
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
