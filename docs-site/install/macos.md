---
title: macOS
description: Installing bleck on macOS
---

!!! note

    macOS support is implemented and covered by the test suite, but it sees less
    real-world use than Linux and Windows. Issue reports are welcome.

1.  **Install uv**

    ```bash
    brew install uv
    ```

1.  **Install Dolphin**

    ```bash
    brew install --cask dolphin
    ```

    That gives you the emulator, which is what `bleck launch` needs.

    !!! warning "RVZ disc images need one extra step on macOS"

        The distributed `Dolphin.app` contains the emulator and **nothing else**
        — not `dolphin-tool`, which is the only program `bleck` knows that reads
        RVZ. Dolphin builds it as `Binaries/dolphin-tool`, a *sibling* of the
        app, and never copies it inside. `wit` cannot read RVZ either.

        Convert the image once, then work from the result — `.iso` and `.wbfs`
        are what `wit` reads natively, and what builds are shared as anyway:

        ```bash
        cargo install --locked nodtool
        nodtool convert game.rvz game.iso    # always writes ISO
        ```

        Or `npx dolphin-tool convert -f iso -i game.rvz -o game.iso`, or
        right-click the game in Dolphin and choose *Convert File…*.

        ⛔ **Do not set `BLECK_DOLPHIN_TOOL` to a path inside `Dolphin.app`.**
        Nothing is there, and earlier versions of this page told you to — which
        is how the setting became a crash rather than a missing feature. Point
        it at a real `dolphin-tool` (the `npx` package installs one for arm64,
        and a source build produces one) or leave it unset.

1.  **Check your setup at any point**

    ```bash
    uv run bleck doctor
    ```

    Reports every external tool `bleck` uses: whether it is installed, where it
    was found, whether it actually runs, and which commands it gates. A tool you
    have not installed is reported and is **not** an error — it only limits
    which commands work. A setting pointing at a path that does not exist, or a
    tool that will not run, exits non-zero.

    !!! tip "Apple Silicon kills unsigned binaries silently"

        `bleck doctor` runs each tool it finds, because being on disk is not the
        same as being usable. If one was killed rather than run, `doctor` says so
        and prints the `codesign` command that repairs it.

1.  **Install Wiimms ISO Tools**

    There is no Homebrew formula. Download **v3.05a or later** from
    [wit.wiimm.de](https://wit.wiimm.de/download.html) and put `wit` on your
    PATH, or:

    ```bash
    export BLECK_WIT="/path/to/wit"
    ```

    !!! warning "Apple Silicon"

        v3.05a is the first release with an arm64 slice — earlier macOS builds
        are x86_64 only. If `wit version` reports `Killed: 9`, macOS has rejected
        the signature; users report an ad-hoc re-sign fixes it, applied **after**
        `install.sh` and to every binary in the toolset's `bin/`:

        ```bash
        sudo codesign --sign - --force \
          --preserve-metadata=entitlements,requirements,flags,runtime /usr/local/bin/wit
        ```

1.  **Clone and sync**

    ```bash
    git clone git@github.com:Coolroo/bleck.git
    cd bleck
    uv sync --extra dev
    ```

1.  **Verify**

    ```bash
    uv run pytest
    uv run bleck --help
    uv run bleck doctor
    ```
{ .steps }


## For code and script mods

Only needed if you write behaviour rather than swap assets.

1.  **A PowerPC cross-compiler**

    devkitPPC is preferred — it targets the same ABI the game was built with.
    On macOS it installs from a `.pkg`: download
    `devkitpro-pacman-installer.pkg` from
    [devkitPro/pacman releases](https://github.com/devkitPro/pacman/releases/latest)
    (latest v6.0.2), open it, then:

    ```bash
    sudo dkp-pacman -S gamecube-dev
    ```

    !!! warning

        ⛔ **Do not use `apt.devkitpro.org/install-devkitpro-pacman`** — that is
        the Debian/Ubuntu installer, and the Linux page is where it belongs.

        devkitPro publishes **no arm64 macOS build**: its precompiled toolchains
        are Linux x86_64 and macOS x86_64
        ([devkitPro setup](https://switchbrew.org/wiki/Setting_up_Development_Environment)).
        Apple Silicon therefore needs Rosetta 2 —
        `softwareupdate --install-rosetta` — and Homebrew packages no PowerPC
        cross-compiler as an alternative.

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
volumes collect `._` AppleDouble sidecars. Left alone, they would be staged into
a rebuilt disc with no error to warn you.

!!! info

    `bleck` excludes `.DS_Store`, `.localized` and `._*` from staging and overlays
    **on macOS only**. Filtering them elsewhere would hide genuine mistakes.
