---
title: Running on a Wii
description: Build a Riivolution patch instead of a whole disc image
---

A disc image is 4.5 GB, and rebuilding one costs minutes per iteration. If you
are testing on real hardware — or just want a faster loop — `bleck` can emit a
**Riivolution patch** instead: a small XML plus only the files your mod changes.

```bash
bleck mod build my-mod --output riivolution
```

```
work/build/my-mod-riivolution/
  riivolution/my-mod.xml     the patch definition
  my-mod/files/...           only what differs from the base game
  my-mod/sys/main.dol
  my-mod.json                for Dolphin; ignored on hardware
```

For a code-only mod that is usually a few megabytes: the compiled module and the
game's executable.

## Putting it on a Wii

Copy the **contents** of that directory to the root of an SD card, so you end up
with `/riivolution/my-mod.xml` and `/my-mod/...` on the card. Insert it, launch
the Riivolution homebrew channel, and enable the patch on the Super Paper Mario
page.

The patch replaces `main.dol` as well as adding your module, and the code that
loads the module travels inside that executable — so there is no Gecko code
list, `.gct` or cheat manager to set up separately.

!!! warning "The console path is untested"

    `bleck`'s Riivolution output is written against the documented patch format
    and is exercised in Dolphin, which has its own Riivolution support. Nobody
    has yet run it from an SD card on a Wii. If you do, expect to be the first —
    and please say how it went.

## Trying it in Dolphin

Dolphin has built-in Riivolution support (Tools → Start with Riivolution
Patches), and it can take a whole configuration from the command line. `bleck`
writes that configuration beside the patch:

```bash
Dolphin.exe -b -e work/build/my-mod-riivolution/my-mod.json
```

The `.json` points back at your extracted base game, so no image needs to exist.
If you have an untouched retail disc image, that is the better-trodden route:

```bash
bleck mod build my-mod --output riivolution --base-image path/to/spm.wbfs
```

`bleck mod build --output riivolution --launch` does the same thing in one step.

## What a patch cannot express

Riivolution replaces files; it cannot remove them, and it cannot reach the disc
header or filesystem table. `bleck mod build` prints a warning naming any change
of that shape, so you know to build an image for those.

## Choosing an output

`--output` selects what a build produces:

| Kind | Result |
|---|---|
| `iso`, `wbfs`, `rvz` | A disc image — see [Disc formats](../concepts/disc-formats.md) |
| `riivolution` | A patch directory, as above |
| `none` | Stage only, write nothing |

`bleck mod build --help` lists them with a one-line description each.
