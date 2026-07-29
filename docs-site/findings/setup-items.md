---
title: How placed items load, and the 512 ceiling
description: The item half of setup/*.dat traced through the DOL — a fixed 8192-byte buffer, an asserted version, and why giving items to a map that ships none hangs the game
---

# Placed items: the load path, and its limits

The [setup file format](setup-file-format.md) ends with an optional item
section. **14 of the game's 227 maps have one**, and every one of the 1,299
items across them is the same thing: `type` 0, `flags` 0x11 — a coin.

This page traces what the game does with that section, read out of the PAL rev 0
DOL. Addresses are `eu0`.

## ⛔ A map that ships no item section cannot be given one

Adding an item section to one of the 213 maps without one **hangs the game** —
the map never renders. Measured on Lineland Road (`he1_01`): three coins,
written as a section byte-for-byte the shape a map with coins ships, and it
never loaded.

This is worth stating plainly because the obvious reasoning says it should work,
and that reasoning is wrong:

> `setupReadItemInfo` reads the count unconditionally, so for a file with no
> section it reads past the end and lands on zeroed padding. Writing a real
> count at that offset should therefore be read the same way.

Every step of that is true. The conclusion still does not hold. The read path
does succeed; what fails is later, spawning a coin in a map that has not loaded
whatever a coin needs.

## `setupReadItemInfo` — no length check at all

`0x80029730`. Given a loaded setup file, it hands back the count, the version
and a pointer to the array:

```
80029784  lwz  r7, 11204(r3)   ; *(file + 0x2BC4) -> itemCount
80029788  addi r0, r3, 11212   ;   file + 0x2BCC  -> items
8002978c  stw  r7, 0(r4)
80029790  lwz  r3, 11208(r3)   ; *(file + 0x2BC8) -> itemVersion
80029798  stw  r0, 0(r6)
```

There is **no check that the file is long enough**. A v6 file with no item
section is exactly `0x2BC4` bytes, so all three reads are past its end. It works
only because the memory there happens to be zero.

v5 files use `0x2A34` / `0x2A38` / `0x2A3C` for the same three fields. Anything
outside v5–v6 hits an assert in `setup_data.c`.

## ⚠️ 512 items is a hard ceiling

The caller at `0x8017A9C8` allocates a fixed buffer and then trusts the file:

```
8017a9c8  li    r0, 512        ; default count
8017a9d4  li    r4, 8192       ; 512 * sizeof(SetupItem)
8017a9d8  bl    <alloc>
8017aa0c  bl    setupReadItemInfo   ; count OVERWRITTEN from the file
8017aa14  cmpwi r8, 0 ; ble ...     ; count <= 0 -> skip everything
8017aa24  cmplwi r0, 0xF501         ; assert version == 20051201
8017aa54  slwi  r5, r0, 4 ; bl memcpy   ; count * 16 into the 8192 buffer
8017aa8c  bl    setupSpawnItems
```

Nothing clamps the count between reading it and the `memcpy`. **A file claiming
more than 512 items overruns the allocation** rather than being truncated. The
busiest map the game ships places 48.

Two other things fall out of that listing:

- **A count of 0 is completely inert.** `cmpwi r8, 0 ; ble` skips the version
  check, the copy and the spawn. A well-formed section holding zero items does
  nothing at all.
- **`itemVersion` is asserted, not tolerated.** `setup_data.c:355` panics unless
  it is exactly `20051201`. A hand-edited file with a wrong version hangs rather
  than having its items ignored.

## `setupSpawnItems` — and what a coin actually is

`0x80029680`, looping over the copied array:

```
800296ac  lhz  r3, 0(r28)      ; flags: bit 0 AND bit 4 required, else skip
800296c0  lhz  r3, 2(r28)      ; type
800296c4  lhz  r0, 0(r30)      ; setupItemTemplates[0].id
800296cc  bne  -> NULL -> skip
800296e4  lhz  r4, 2(r3)       ; template.itemTemplateId
800296ec  lfs  f1, 4(r28)      ; x, y, z
80029704  bl   0x80078b3c      ; spawn
```

**An unrecognised `type` is skipped, not fatal** — it simply never spawns.
Likewise `flags` without `0x10 | 0x1`.

`setupItemTemplates` resolves through `r13 = 0x805B5F00` to `0x805ADF08`, and
holds exactly one entry:

```
00 00 00 01   ->  { id: 0, itemTemplateId: 1 }
```

Item **1** is `ITEM_ID_WORLD_COIN`. So the full chain is: a setup entry of
`type` 0 becomes item template 1, a world coin, spawned at its `(x, y, z)`.

## Method

`eu0`'s public symbol list contains **two** setup symbols, so none of the
functions above could be looked up by name. They were found by following
strings back to their references:

- `setup_data.c` at `0x80323BB0` — an assert `__FILE__`, whose single
  cross-reference lands inside `setupReadItemInfo`
- `%s/setup/%s.dat` at `0x8033627B` — the path format, whose reference is the
  loader

The game materialises addresses as a base register plus an offset rather than a
single `lis`/`addi` pair, so a naive two-instruction search finds nothing. A
cross-referencer that tracks register values across `lis`/`addis`/`addi` finds
all of them.

## ⛔ What exactly fails: isolated to one byte

Five unattended runs on Lineland Road, reading the game's sequence state out of
emulated memory. Reaching gameplay reads `SEQ_GAME` stage 1; a hang reads
`SEQ_MAPCHANGE` stage 13.

| `he1_01` setup section | result |
|---|---|
| untouched (control) | gameplay, 3 NPCs |
| present, **count 0** | gameplay, 3 NPCs |
| count 1, **type 1** | gameplay, 3 NPCs |
| count 1, **type 0** | ⛔ stuck in `SEQ_MAPCHANGE` stage 13, 0 NPCs |
| `he1_03`, 5 coins -> 7 | gameplay |

The third and fourth rows differ by **one byte** — offset `0x2BCF`, the item's
`type`. Both have `count` 1, so both exercise the version assert and the
`memcpy`. Only the one whose type matches `setupItemTemplates[0].id` reaches the
spawn, and only that one hangs.

So:

- **Growing the file is harmless.** A zero-item section is inert, exactly as the
  `cmpwi r8, 0 ; ble` branch says.
- **The version assert and the copy are harmless** at `count` 1.
- **The hang is the coin spawn itself**, and it happens *before* NPCs are
  created — the map never finishes loading.
- **Adding coins to a map that already has them works.** `he1_03` went from 5 to
  7 and reached gameplay.

## Still open

What the coin spawn needs that a map without coins has not loaded. `0x80078b3c`
entered with `r7 = 0` is where to look. Whether the added coins on a map that
already has them are *visible and collectible* also still needs a human — the
instrument used here reads NPC state and cannot see items.
