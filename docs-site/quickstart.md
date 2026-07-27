---
title: Quickstart
description: From a clone to a modified disc
---

This walks the whole loop: install, extract a base, change one texture, build a
bootable disc.

!!! note

    You need a Super Paper Mario disc image. `bleck` never distributes game data.

## 1. Install

  === "Linux"

      ```bash
      curl -LsSf https://astral.sh/uv/install.sh | sh
      sudo apt install -y wit dolphin-emu

      git clone git@github.com:Coolroo/bleck.git
      cd bleck
      uv sync --extra dev
      ```
  === "macOS"

      ```bash
      brew install uv
      brew install --cask dolphin

      git clone git@github.com:Coolroo/bleck.git
      cd bleck
      uv sync --extra dev
      ```

      Wiimms ISO Tools has no Homebrew formula — download it from
      [wit.wiimm.de](https://wit.wiimm.de/) and put `wit` on your PATH.
  === "Windows"

      ```powershell
      winget install --id=astral-sh.uv -e

      git clone git@github.com:Coolroo/bleck.git
      cd bleck
      uv sync --extra dev
      ```

      Install [Wiimms ISO Tools](https://wit.wiimm.de/) and
      [Dolphin](https://dolphin-emu.org/), then add both to your PATH.

Check it worked:

```bash
uv run bleck --help
```

## 2. Extract your disc

```bash
uv run bleck extract "Super Paper Mario.rvz" work/extracted/eu0
```

This becomes your **base** — a pristine reference `bleck` never writes to.

## 3. Look inside

```bash
uv run bleck info work/extracted/eu0/files/lyt/title.bin.uk
```

```
title.bin.uk  238,808 bytes
  LZ77  type 0x10 -> 700,896 bytes
    U8  35 entries (31 files)
      arc/timg/mario.tpl  18,880  TPL
      arc/timg/koopa.tpl  19,264  TPL
      ...
```

That is the title screen: an LZ77-compressed U8 archive full of textures.

## 4. Create a mod

```bash
uv run bleck mod new my-first-mod
uv run bleck mod vendor my-first-mod lyt/title.bin.uk/arc/timg/mario.tpl
```

!!! tip

    `vendor` resolves paths **through** archive boundaries. It unpacks the archive,
    pulls out that one texture, and puts it where the overlay expects it — you never
    copy from the base by hand.

## 5. Edit it

Open `mods/my-first-mod/overlay/files/lyt/title.bin.uk/arc/timg/mario.tpl` in a
TPL-capable editor, or invert its pixel data for an unmistakable change. See
[Your first mod](guides/first-mod.md) for a script that does exactly that.

## 6. Build

```bash
uv run bleck mod build my-first-mod work/out/my-mod.wbfs
```

!!! warning

    Share builds as **`.wbfs`**. RVZ is smaller but needs Dolphin 5.0-12188 (2020)
    or newer — older builds reject it as *"not a GC/Wii ISO"*.

## 7. Run it

Open `work/out/my-mod.wbfs` in Dolphin. The title screen should show your change.

<div class="grid cards" markdown>

-   **[Your first mod](guides/first-mod.md)**

    The same walkthrough in detail, with a working texture edit.

-   **[How it works](concepts/pipeline.md)**

    What the nested formats are and why they matter.

</div>

