---
title: The setup/*.dat enemy placement format
description: Fully decoded across all 227 files — always 100 entries, a stride that varies with the version, and the empty-slot rule that silently discards enemies
---

# `setup/*.dat`: the enemy placement format

227 files in `files/setup/`, one per map, named after the map. ✅ **Every byte of
every file is accounted for by the structure below**, validated by parsing all
227 with no exceptions.

```c
struct SetupFile {
    u16 version;           // 1..6
    u16 padding;           // always 0
    Enemy entries[100];    // ALWAYS exactly 100; stride depends on version
    // v6 only, and only when the map places items:
    u32 itemCount;
    u32 itemFormat;        // always 20051201
    Item items[itemCount]; // 16 bytes each
};
```

## ⚠️ The entry stride is a function of the version

This is the part that makes file sizes look arbitrary until you read the header,
and it is the correction that matters most:

| version | entry stride | base size | files |
|---:|---:|---:|---:|
| 1 | 28 | 2,804 | 1 |
| 2 | 96 | 9,604 | 2 |
| 3 | 100 | 10,004 | 10 |
| 4 | 104 | 10,404 | 9 |
| 5 | 108 | 10,804 | 7 |
| 6 | 112 | 11,204 | **198** |

`base size = 4 + 100 * stride` holds **exactly** for every version.

⛔ **The widely-linked document is wrong here.** TCRF's SPM notes link a Google
Doc stating these files are *"consistently 11,204 bytes"* with a fixed 112-byte
stride. That is true of 184 of the 227 files and false of the other 43; across
the whole directory there are **17 distinct sizes**, from 2,804 to 11,980 bytes.
TCRF itself annotates the doc with *"entries aren't always 112 bytes, says
Skawo"* — correct, and the table above is the quantification. The two sources
reconcile once the version field is read: the doc measured v6 files, which
really are 11,204 bytes, and generalised.

⚠️ `spm-docs` says item sections exist in v5 and v6. On this disc **no v5 file
carries one** — all 14 that do are v6. Observed item counts: 4, 5, 6, 10 (×2),
15, 16, 18, 20, 24, 27, 48 (×3). ✅ `itemFormat` is `20051201` on every one,
matching the `SETUPOBJ_FORMAT_VERSION` constant `spm-docs` records.

## The entry (version 6)

Documented upstream in `spm-headers`' `setup_data.h`, confirmed independently by
measuring all 227 files:

| offset | field | note |
|---|---|---|
| 0x00 | `Vec3 pos` | |
| 0x0C | `s32 type` | index into [`npcEnemyTemplates`](npc-enemy-templates.md) |
| 0x10 | `s32 instanceId` | ignored if 0 |
| 0x20–0x5F | `s32 unitWork[16]` | always zero across all 6,438 populated slots |
| 0x6C | `f32 gravityRotation` | degrees anti-clockwise about the z axis |

⚠️ `type` is a **template** id, not an `NPC_*` tribe id — there are 535 tribe
ids against a smaller number of templates, and confusing them silently places
the wrong enemy.

⚠️ **Unused slots are not zero-filled.** They carry a default in an
undocumented field (offset 24, usually `300`), so an "any non-zero byte" test
counts 6,438 slots where only ~1,328 place anything. 🔶 `type == 0` is the
working test; template 0 appears to be a sentinel.

Roughly 70 of the 112 bytes remain undocumented.

## ⛔ Clearing a slot in the middle orphans every slot after it

✅ **The game stops reading entries at the first empty one.**

Two builds, one variable — whether slot 1 is cleared. Both declare the *same*
enemy (template 250) in slots 0 and 2, at vanilla positions:

```
slots 0, 1 (cleared), 2   ->  1 NPC spawned:  slot 0
slots 0,              2   ->  3 NPCs spawned: slot 0, slot 1, slot 2
```

With the gap, slot 2 never spawns — and it is not merely invisible or out of
bounds, it is **absent from the live NPC list**.

This was measured by dumping the game's NPC list and reporting which setup slot
each live NPC came from, which is what turned it from "I walked the whole level
and did not see it" into a settled question. Two earlier hypotheses (the
template is refused in this map; the position is off the visible plane) were
both wrong, and both would have looked the same from the player's side.

*(Sources: bleck decision log D42, D55, D79.)*

## See also

- [Which copy of the setup file the game reads](setup-which-copy.md) — there are
  two, and it matters
