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
uv run pytest                      # expect 145 passed
uv run python scripts/lint.py
uv run bleck --help
```

## External tools

| Tool | Where from | Needed for |
|---|---|---|
| `wit` | https://wit.wiimm.de/ | `extract`, `build` |
| `DolphinTool` | inside `Dolphin.app` | RVZ read/write |

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
uv run bleck extract ~/roms/spm.rvz extracted/eu0
uv run bleck mod new my-mod
uv run bleck mod vendor my-mod lyt/title.bin.uk/arc/timg/mario.tpl
uv run bleck mod build my-mod out.wbfs
```

Share builds as `.wbfs` — RVZ needs Dolphin 5.0-12188 or newer (D24).
