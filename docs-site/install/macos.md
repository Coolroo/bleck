---
title: macOS
description: Installing bleck on macOS
---

!!! warning

    **Not yet verified on macOS.** The platform support is implemented and covered
    by tests that run on Linux, but nobody has run it on a Mac. If you do, please
    report back.

1.  **Install uv**

    ```bash
    brew install uv
    ```

1.  **Install Dolphin**

    ```bash
    brew install --cask dolphin
    ```

    `DolphinTool` lives **inside the application bundle** at
    `/Applications/Dolphin.app/Contents/MacOS/DolphinTool`, not on your PATH.
    `bleck` looks inside the bundle automatically.

1.  **Install Wiimms ISO Tools**

    There is no Homebrew formula. Download the macOS build from
    [wit.wiimm.de](https://wit.wiimm.de/) and put `wit` on your PATH, or:

    ```bash
    export BLECK_WIT="/path/to/wit"
    ```

1.  **Clone and sync**

    ```bash
    git clone git@github.com:Coolroo/bleck.git
    cd bleck
    uv sync --extra dev
    ```

1.  **Verify**

    ```bash
    uv run pytest          # expect 164 passed
    uv run bleck --help
    ```
{ .steps }


## For code and script mods

Only needed if you write behaviour rather than swap assets.

1.  **A PowerPC cross-compiler**

    devkitPPC is preferred — it targets the same ABI the game was built with:

    ```bash
    curl -L https://apt.devkitpro.org/install-devkitpro-pacman -o install.sh
    sudo ./install.sh && sudo dkp-pacman -S gamecube-dev
    ```

1.  **wstrt, from Wiimms SZS Toolset**

    This embeds the Gecko loader into the disc, so a code mod runs with no emulator
    configuration at all. It is a **separate package from `wit`** with no distro
    package:

    ```bash
    curl -LO https://szs.wiimm.de/download/szs-v2.42a-r8989-mac64.tar.gz
    tar xf szs-*.tar.gz && cd szs-* && sudo ./install.sh
    ```

    !!! warning

        The macOS build is **x86_64 only**, so Apple Silicon runs it under Rosetta 2.
        Install it with `softwareupdate --install-rosetta` if needed.

1.  **Symbols and the loader codelist**

    Neither ships with `bleck` — both are third-party, and the loader is GPLv3.

    ```bash
    export BLECK_SYMBOLS_DIR=~/spm/symbols   # spm.eu0.lst, from spm-headers
    export BLECK_GECKO_DIR=~/spm/gecko       # loader.eu0.txt, from spm-rel-loader
    ```
{ .steps }


!!! note

    Without `wstrt` a code mod still builds — the loader just is not embedded, and
    `bleck` warns that the mod will only run if the loader is in Dolphin's cheat
    configuration.

## Apple Silicon and Intel

Homebrew installs to a different prefix on each. `bleck` searches both, so
either works without configuration.

| CPU | Homebrew prefix |
|---|---|
| Apple Silicon | `/opt/homebrew` |
| Intel | `/usr/local` |

## Finder clutter is filtered automatically

Browsing an extracted disc in Finder creates `.DS_Store` files, and non-native
volumes collect `._` AppleDouble sidecars.

!!! info

    Left alone, that clutter would be staged into a rebuilt disc — files the real
    game never shipped, with no error to warn you. `bleck` excludes `.DS_Store`,
    `.localized` and `._*` from staging and overlays **on macOS only**. Filtering
    them elsewhere would hide genuine mistakes.
