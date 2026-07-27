---
title: How it works
description: The nested formats bleck handles for you
---

Super Paper Mario's assets are wrapped in layers. A single title-screen texture
sits inside an archive, inside a compressed stream, inside a disc image.

```
disc image  (ISO / RVZ / WBFS)
  └── files/lyt/title.bin.uk
        └── LZ77 compression
              └── U8 archive
                    └── arc/timg/mario.tpl   ← the texture
```

`bleck` unwraps and rewraps all of it.

## The formats

??? note "LZ77 — compression"

    Nintendo's LZ77 (type `0x10`). A four-byte header, then blocks of literal
    bytes and back-references.

    Every map file and every REL module on the disc is compressed this way.
    `bleck` both decompresses and compresses it.

??? note "U8 — archives"

    A standard Nintendo archive holding a flat file tree. Map files and layout
    files are U8 archives once decompressed.

    Repacking is **byte-exact**: all 383 map archives on the PAL disc survive
    unpack and repack unchanged.

??? note "TPL — textures"

    Standard Nintendo texture format. `bleck` identifies TPL files; editing
    their pixel data is done with external tools.

??? note "REL — code modules"

    Nintendo's relocatable module format. The game's own code ships as RELs, and
    custom code mods are built as one. See [Code mods](../guides/code-mods.md).

!!! tip

    None of these are bespoke. Every format on the disc is a stock Nintendo one,
    which is why `bleck` is mostly about composing layers rather than reverse
    engineering them.

## Seeing it yourself

`bleck info` unwraps the whole stack:

```bash
bleck info work/extracted/eu0/files/map/aa1_01.bin
```

```
aa1_01.bin  424,712 bytes
  LZ77  type 0x10 -> 1,131,524 bytes
    U8  13 entries (7 files)
      ./dvd/map/aa1_01/map.dat          561,630
      ./dvd/map/aa1_01/texture.tpl      188,576  TPL
      ./dvd/bg/aa1_01_00.tpl            122,944  TPL
      ./dvd/setup/aa1_01.dat             11,204
```

Those `./dvd/...` paths are the original developer build tree, preserved on the
retail disc.

## Compression is not bit-exact, and that is fine

`bleck`'s compressor produces output about **0.25% larger** than Nintendo's,
with different internal token boundaries.

!!! success

    A disc built this way **boots and renders correctly** — verified in Dolphin.
    Matching Nintendo's exact output would be satisfying but is not required.

For fast iteration, `--store` skips the search entirely and encodes everything
as literals. It is instant, at roughly 1.125× size. On an 89%-empty disc that
costs nothing.
