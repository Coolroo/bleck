---
title: itemDataTable — 538 items, and why the names are romaji
description: The item table's address, stride and exact length, proven two ways, and the three different names every item has
---

# `itemDataTable`: 538 entries, and the names are not English

**PAL rev 0 (`R8PP01`, "eu0").**

| | |
|---|---|
| `itemDataTable` | `0x803F5F98` |
| stride | `0x2C` (from `spm-headers`' `item_data.h`) |
| entries | **538** |

✅ **The length is proven, not assumed.** The next symbol in the PAL symbol list
is `itemEventDataTable` at `0x803FBC10`, and

```
0x803FBC10 - 0x803F5F98 = 0x5C78 = 538 * 0x2C     exactly
```

The table ends precisely where the next one begins. ✅ A second, independent
check: for every id, the `itemName` string read out of the game's `.data`
matches the `ITEM_ID_*` constant at that position in `spm-headers`'
`item_data_ids.h` — including the oddities (see below). Two chains that share
no step agree.

✅ All of this is static `.data`, so it can be read straight out of
`sys/main.dol` with no emulator running.

## ⚠️ `ItemData.itemName` is the developers' romaji name

This is the finding most likely to be assumed the other way round. Every item
has **three** different names, and none is derivable from another:

| id | `itemName` (in the table) | `nameMsg` (a key) | English (from `msg/UK`) |
|---|---|---|---|
| 0x41 | `HONOO_SAKURETU` | `in_honoo_sakuretsu` | Fire Burst |
| 0x42 | `KOORI_NO_IBUKI` | `in_koori_no_ibuki` | Ice Storm |
| 0x45 | `POW_BLOCK` | `in_pow_block` | POW Block |
| 0x47 | `KINKAI_100` | `in_kinkai_100` | Gold Bar |

⚠️ Note `SAKURETU` in the item name against `sakuretsu` in the message key. The
two romanisations of the same word differ, so **the message key cannot be
computed from the item name**. Resolving an English name means reading
[the message files](msg-file-format.md); all 538 keys resolve in
`files/msg/UK`.

## English names are not unique, and are not identifiers

If you are building a name→id lookup, these are the collisions that exist:

- **`Unavailable Item` is the English name of 18 different ids** (every unused
  world item), and **`Door Key` of six**.
- Four *internal* names are shared by two items each — `MARIO`, `PEACH`,
  `KOOPA`, `LUIGI` are each a character item **and** its card.
- English names are not identifiers: `POW Block`, `Gold Bar x3`, `Mistake!`.

✅ Measured, because it is nearly a rule and must not be treated as one: all 538
`itemName` strings equal their `ITEM_ID_*` constant's bare form (constant minus
the `ITEM_ID_` prefix and its group word). The count of disagreements is **0**.
So `itemName` adds no lookup the constants do not already provide — but the
message key, as above, is a genuine third name.

⚠️ `item_data_ids.h` really does spell one constant `ITEM_ID_WORLD_COIN_x3`,
with a lowercase `x`, and the table's `itemName` has the same oddity. It is not
a transcription error in either place.

## Id ranges

From `item_data_ids.h`, and load-bearing when reading a table of ids:

| range | ids |
|---|---|
| `ITEM_ID_USE_*` | 65–119 (`0x41`–`0x77`) |
| `ITEM_ID_COOK_*` | 120–215 (`0x78`–`0xD7`) |

These matter for interpreting
[`itemEventDataTable`](item-event-data-table.md), whose contents are not all
from the "use" range.

## Not established

- 🔶 The table has **not** been cross-checked against a running game. Nothing
  suggests the game rewrites it and both checks above are strong, but "the DOL
  says X" is not "the running game says X". A live read of the *other* item
  table did independently agree on 33 ids and their order.
- 🔶 Only `files/msg/UK` was resolved. The disc carries six other language
  directories.
- The remaining fields of the `0x2C`-byte entry were not investigated here.

*(Sources: bleck decision log D114, D118, D119.)*
