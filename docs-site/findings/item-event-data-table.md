---
title: itemEventDataTable — the 33 items that have a use script
description: The full id list read off the live table, what each script opens with, how much they are shared, and why a third of them are cooked items
---

# `itemEventDataTable`: the 33 items with a use script

**PAL rev 0 (`R8PP01`, "eu0").** `itemEventDataTable` is at `0x803FBC10`, and
holds **33** entries of

```c
struct { s32 itemId; EvtScriptCode *useScript; const char *useMsgName; };
```

An item's "what happens when you use it" script is here, and **only** the items
in this table have one.

## ✅ The full id list, read off the live table

In table order:

```
41 42 43 44 45 46 47 48 49 4A 4B 4C 4D 4E 4F
55 56 57 58 59 5A
A0 A1 92 93 94 95 D0 A3 D6 CE B0 32
```

⚠️ **This is not "all the effect items", which is the natural assumption and is
wrong.** Against the id ranges in `item_data_ids.h` (`USE` = `0x41`–`0x77`,
`COOK` = `0x78`–`0xD7`):

- **21** are from the *use* range (`0x41`–`0x4F` and `0x55`–`0x5A`);
- **11 are cooked items** — `0x92`–`0x95`, `0xA0`, `0xA1`, `0xA3`, `0xB0`,
  `0xCE`, `0xD0`, `0xD6`;
- **1 is from the key range** — `0x32`, `ITEM_ID_KEY_POCKET_DOKAN`, which is
  **Return Pipe** in English. An item with a
  scripted use, which is exactly why it is in a table of use scripts. As a bare
  number it looked like an anomaly; as a name it explains itself.

⛔ Items with no scripted use are simply **absent**. `0x50` (Shroom Shake) and
`0xD4` are not in the table. An experiment that patches an id which is not here
is testing nothing, and looks identical to a mechanism that does not work.

## ✅ Only 19 of the 33 scripts open with a `USER_FUNC`

All 33 entries were guarded against an opening `USER_FUNC` of argc 4. Nineteen
matched; fourteen declined:

| opening word | entries | meaning |
|---|---|---|
| `0x0004005C` | 19 | `USER_FUNC`, argc 4 |
| `0x00020032` | 13 | opcode `0x32`, argc 2 |
| `0x0001000A` | 1 (id `0x32`) | opcode `0x0A`, argc 1 |

The head of item `0x46`'s script, dumped rather than guessed:

```
00020032 FE363C80 00000001      ; opcode 0x32, argc 2  (FE363C80 = LW(0))
0001005F 803FBEF8               ; opcode 0x5F, argc 1
0001005F 803FC868
0003005C                        ; the first USER_FUNC, argc 3, at word 7
```

🔶 Only `0x46` was dumped. That the other thirteen are similarly shaped is an
assumption, not a measurement.

## ⚠️ The scripts are shared

**22 distinct scripts across 33 entries** — eleven entries share a script with
another. Item `0x41`'s script is pointed at by 3 of the 33.

So an item id is *not* a unique target: changing "what Fire Burst does" can
change what two other items do. Anything editing here should count the entries
pointing at the script it touched.

## ✅ The pointers are static and stable

The first eight `useScript` pointers:

```
803FC918  803FCCA4  803FD028  803FD328
803FD6B8  803FDBA8  803FDD60  803FDDF8
```

`0x803F…` is the DOL's own static data, not a loaded REL, so no map has to be
resident for these to be valid. Entry 0 read `803FC918` both at module load time
and during gameplay — the same address, so the table is not rebuilt.

✅ Item `0x41` (Fire Burst)'s script really is what runs when the player uses the
item: with its opening instruction replaced by a call into a loaded module, the
handler was entered the moment a person used a Fire Burst in a real save
session. That needed a human — [input cannot be injected](method.md).

## ⛔ Do not use `getItemUseEvt` to test membership

`spm-headers` notes that it returns *"a fallback if the item isn't in there"*.
So an unknown id gets a plausible non-null script rather than an error, and any
edit made through it lands on something shared by everything. Walk the table.

*(Sources: bleck decision log D91, D92, D113, D115, D118. D109 recorded "all 33
are effect items" and is superseded by D113's live read.)*

## See also

- [`itemDataTable`](item-data-table.md) — the other item table: 538 entries,
  names, and why they are romaji
- [How an evt instruction is encoded](evt-instruction-format.md)
