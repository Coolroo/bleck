---
title: bleck
description: A modding toolkit for Super Paper Mario (Wii)
---

`bleck` is a command-line toolkit that reads, edits and rebuilds Super Paper
Mario discs. It handles the game's nested container formats so you can change
one texture without thinking about compression, archives, or disc layout.

## What it does

<div class="grid cards" markdown>

-   **Read any disc file**

    Unwraps nested formats automatically — LZ77 compression, U8 archives, TPL
    textures and REL modules.

-   **Build bootable discs**

    Extract, modify and rebuild to ISO, RVZ or WBFS, with your modified assets
    in place.

-   **Mods as overlays**

    A mod contains only what changed. The extracted base game is never
    modified, so you always have a clean reference.

-   **Dependency chains**

    Mods can depend on other mods, resolved into one install order with
    conflict detection between independent edits.

-   **Custom behaviour**

    Write event logic in a [scripting language](guides/scripting.md) that
    compiles to the game's own VM, or native
    [PowerPC hooks](guides/code-mods.md) in C. `bleck mod build` compiles both
    into the `mod.rel` the disc carries.

-   **Change where the game starts**

    Boot straight into any map, and bind actions to named controller button
    combos, from the mod manifest.

</div>


## What it does not do

**Level editing** is deliberately deferred. The map data format is only partly
decoded, so editing it means changing bytes without a visualiser to check them
against.

## Requirements

You supply your own disc image. `bleck` does not distribute game data.

!!! info

    Target **PAL rev 0** (`R8PP01`), the build every upstream research project
    documents. It is a strict superset of the US build — no content is lost by
    working from it.

<div class="grid cards" markdown>

-   **[Quickstart](quickstart.md)**

    From clone to a modified title screen.

-   **[Install](install/index.md)**

    Linux, macOS and Windows.

</div>

