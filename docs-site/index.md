---
title: bleck
description: A modding toolkit for Super Paper Mario (Wii)
---

`bleck` reads, edits and rebuilds Super Paper Mario discs. It handles the
game's nested container formats so you can change one texture without thinking
about compression, archives, or disc layout.

!!! note

    Named for Count Bleck. The toolkit is command-line only.

## What it does today

<div class="grid cards" markdown>

-   **Read any disc file**

    Unwraps nested formats automatically — LZ77 compression, U8 archives, TPL
    textures and REL modules.

-   **Build bootable discs**

    Extract, modify and rebuild to ISO, RVZ or WBFS. Verified: a disc built by
    `bleck` boots and renders modified textures.

-   **Mods as overlays**

    A mod contains only what changed. The extracted base game is never
    modified, so you always have a clean reference.

-   **Dependency chains**

    Mods can depend on other mods, resolved into one install order with
    conflict detection between independent edits.

</div>


## What it does not do yet

!!! warning

    **Code injection is in progress.** The PowerPC toolchain is proven — `bleck`
    can build a valid REL module — but compiling code into a mod is not yet wired
    into the CLI. See [Code mods](guides/code-mods.md).

**Level editing** is deliberately deferred. The map data format is partly
understood, but editing it without a visualiser means changing bytes and hoping.

## Requirements

You supply your own disc image. `bleck` does not distribute game data.

!!! info

    Development targets **PAL rev 0** (`R8PP01`), the build every upstream research
    project documents. It is a strict superset of the US build — no content is
    lost by working from it.

<div class="grid cards" markdown>

-   **[Quickstart](quickstart.md)**

    From clone to a modified title screen.

-   **[Install](install/index.md)**

    Linux, macOS and Windows.

</div>

