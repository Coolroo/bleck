---
title: Linux
description: Installing bleck on Linux
---

1.  **Install uv**

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

    Or use pip if you prefer — see [the alternative](#without-uv) below.

1.  **Install the external tools**

    ```bash
    sudo apt install -y wit dolphin-emu
    ```

    On Debian and Ubuntu, `dolphin-tool` lands in `/usr/games`, which is not
    always on PATH. `bleck` looks there anyway.

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
    ```
{ .steps }


## For code and script mods

Only needed if you write behaviour rather than swap assets.

1.  **A PowerPC cross-compiler**

    devkitPPC is preferred — it targets the same ABI the game was built with:

    ```bash
    wget https://apt.devkitpro.org/install-devkitpro-pacman
    chmod +x install-devkitpro-pacman && sudo ./install-devkitpro-pacman
    sudo dkp-pacman -S gamecube-dev
    ```

    Your distro's `gcc-powerpc-linux-gnu` also works, but needs `-fno-pic -fno-PIE`
    and rejects `-mgcn`. `bleck` detects which one it found and adjusts.

1.  **wstrt, from Wiimms SZS Toolset**

    This embeds the Gecko loader into the disc, so a code mod runs with no emulator
    configuration at all. It is a **separate package from `wit`** with no distro
    package:

    ```bash
    wget https://szs.wiimm.de/download/szs-v2.42a-r8989-x86_64.tar.gz
    tar xf szs-*.tar.gz && cd szs-* && sudo ./install.sh
    ```

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

## Without uv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Both workflows are supported. With a venv active, drop the `uv run` prefix from
every command.

## Architecture support

`bleck` runs on both x86-64 and aarch64 Linux.

!!! note

    Dolphin needs a desktop-class machine to run a Wii game at usable speed, so
    do your visual testing there. See [Testing](../guides/testing.md).
