---
title: Overview
description: What bleck needs, on any platform
---

`bleck` ships two ways: a **single-file executable** that needs no Python, or
the Python package. Either way it shells out to two external tools for disc I/O.

## The binary

Download the archive for your platform from the
[latest release](https://github.com/Coolroo/bleck/releases/latest), unpack it,
and run it — there is nothing to install and no Python needed.

=== "Linux / macOS"

    ```bash
    tar -xzf bleck-*-linux-x86_64.tar.gz
    ./bleck --help
    ```

=== "Windows"

    ```powershell
    Expand-Archive bleck-*-windows-x86_64.zip -DestinationPath .
    .\bleck.exe --help
    ```

Builds are produced for Linux x86-64, Windows x86-64 and macOS arm64.

Each release also carries a `SHA256SUMS` file, so you can check a download
before you run it:

=== "Linux / macOS"

    ```bash
    sha256sum -c SHA256SUMS --ignore-missing
    ```

=== "Windows"

    ```powershell
    Get-FileHash bleck-*-windows-x86_64.zip -Algorithm SHA256
    ```

!!! note "The builds are unsigned"

    macOS will refuse a downloaded binary until the quarantine flag is cleared
    (`xattr -d com.apple.quarantine ./bleck`), and Windows SmartScreen shows a
    warning the first time. Code signing needs a paid certificate on both
    platforms; building from source avoids it entirely.

Untagged builds of `main` are also available as Actions artifacts, if you want
a change before it is released.

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

-   :material-linux: **[Linux](linux.md)**

    ---

    Package manager or a source build for `wit`; Dolphin from Flatpak.

-   :material-apple: **[macOS](macos.md)**

    ---

    Homebrew for both tools. `DolphinTool` lives inside `Dolphin.app`.

-   :material-microsoft-windows: **[Windows](windows.md)**

    ---

    Both tools are plain `.exe` downloads.

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
