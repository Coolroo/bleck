# macOS Setup

macOS is a supported target (D30).

⚠️ **Not yet verified on macOS.** The platform profile is written from the
documented layouts and covered by tests that run on Linux. Running
`uv run pytest` on a Mac is what turns "should work" into "does".

---

## Install

```bash
brew install uv          # or: curl -LsSf https://astral.sh/uv/install.sh | sh

git clone git@github.com:Coolroo/bleck.git
cd bleck
uv sync --extra dev
```

## Verify

```bash
uv run pytest                      # expect 164 passed
uv run python scripts/lint.py
uv run bleck --help
```

## External tools

| Tool | Where from | Needed for |
|---|---|---|
| `wit` | https://wit.wiimm.de/ | `extract`, `build` |
| `DolphinTool` | inside `Dolphin.app` | RVZ read/write |
| `Dolphin` | inside `Dolphin.app` | `bleck launch` |
| **`wstrt`** | **Wiimms SZS Toolset** — a *separate* package from `wit` | embedding the loader into a code mod's disc |
| **`powerpc-eabi-gcc`** | **devkitPPC** | compiling scripts and code mods |

**Dolphin is an application bundle**, so its tools are not on PATH. `bleck`
looks inside it automatically:

- `/Applications/Dolphin.app/Contents/MacOS`
- `~/Applications/Dolphin.app/Contents/MacOS`

**Homebrew's prefix depends on the CPU** — `/opt/homebrew` on Apple Silicon,
`/usr/local` on Intel. Both are searched, so either works.

**Wiimms ISO Tools has no Homebrew formula.** Download the macOS build and put
`wit` on PATH, or point at it directly:

```bash
export BLECK_WIT="/path/to/wit"
export BLECK_DOLPHIN_TOOL="/Applications/Dolphin.app/Contents/MacOS/DolphinTool"
```

## For code and script mods

Only needed if you write behaviour rather than swap assets.

**devkitPPC** supplies the cross-compiler. It installs to `/opt/devkitpro`,
which `bleck` searches:

```bash
curl -L https://apt.devkitpro.org/install-devkitpro-pacman -o install.sh
sudo ./install.sh && sudo dkp-pacman -S gamecube-dev
```

**Wiimms SZS Toolset** supplies `wstrt`, which embeds the Gecko loader into the
disc so a code mod runs with no emulator configuration. It is a **different
download from `wit`**, with no Homebrew formula:

```bash
curl -LO https://szs.wiimm.de/download/szs-v2.42a-r8989-mac64.tar.gz
tar xf szs-*.tar.gz && cd szs-* && sudo ./install.sh
```

⚠️ **The macOS build is x86_64 only**, so Apple Silicon runs it under Rosetta 2.
Install Rosetta with `softwareupdate --install-rosetta` if it is missing.

You also need a symbol list and a loader codelist, neither of which ships with
`bleck` — both are third-party and one is GPLv3. See
[`scripting.md`](./scripting.md).

```bash
export BLECK_WSTRT="/usr/local/bin/wstrt"
export BLECK_SYMBOLS_DIR="$HOME/spm/symbols"   # spm.eu0.lst
export BLECK_GECKO_DIR="$HOME/spm/gecko"       # loader.eu0.txt
```

Every configurable path is declared in
[`bleck/common/env.py`](../bleck/common/env.py).

## Finder clutter is filtered automatically

Browsing an extracted disc in Finder creates `.DS_Store` files, and non-native
volumes collect `._` AppleDouble sidecars. Without handling, that clutter would
be staged into a rebuilt disc — files the real game never shipped.

`bleck` excludes `.DS_Store`, `.localized` and `._*` from staging and from mod
overlays **on macOS only**. Filtering them on Linux or Windows would hide
genuine mistakes, so the behaviour is per-platform.

## Use

```bash
uv run bleck extract ~/roms/spm.rvz work/extracted/eu0
uv run bleck mod new my-mod
uv run bleck mod vendor my-mod lyt/title.bin.uk/arc/timg/mario.tpl
uv run bleck mod build my-mod work/out/my-mod.wbfs
```

Share builds as `.wbfs` — RVZ needs Dolphin 5.0-12188 or newer (D24).
