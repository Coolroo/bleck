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
    compiles to the game's own VM, or native code in
    [C or C++](guides/code-mods.md). `bleck mod build` compiles both into the
    `mod.rel` the disc carries.

-   **Change the game's own content**

    Point one of the game's existing event scripts at your code, or hook a game
    function by name — running before it, after it, or in place of it. Both are
    declared in the manifest — no addresses, and a mismatch is refused rather
    than written.

-   **Run it on a Wii**

    Build a [Riivolution patch](guides/hardware.md) instead of a disc image:
    only the files that changed, in seconds rather than minutes.

-   **Change where the game starts**

    Boot straight into any map, and bind actions to named controller button
    combos, from the mod manifest.

</div>


## What it does not do

**Level editing** is deliberately deferred. The map data format is only partly
decoded, so editing it means changing bytes without a visualiser to check them
against.

**Editing a function's *middle*.** A hook takes effect at a function's entry, so
your code can run before it, after it, or instead of it — but not partway
through.

## Requirements

You supply your own disc image. `bleck` does not distribute game data.

!!! warning "No licence yet"

    `bleck` carries no `LICENSE` file, so by default no rights are granted —
    you can read the source and use it yourself, but not redistribute it or a
    build of it. This is unsettled rather than decided, and settling it means
    accounting for the GPLv3 REL loader embedded in every patched `main.dol`.

    Treat the project as **not ready to depend on** until this is resolved.

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

