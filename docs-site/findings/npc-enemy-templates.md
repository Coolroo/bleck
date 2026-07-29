---
title: npcEnemyTemplates — enemy behaviour scripts, and how heavily they are shared
description: The static template table's stride and script offsets, measured because NPCTemplate is in no header, and the sharing that makes a Goomba patch fire on a Squiglet
---

# `npcEnemyTemplates`: where enemy behaviour scripts live

**All addresses are PAL rev 0 (`R8PP01`, "eu0").**

An NPC's behaviour scripts — init, move, on-hit, death — are `EvtScriptCode *`
fields on a live `NPCEntry`, copied in when the NPC spawns. They are **also**
in a static table that ships in `main.dol`, which means they are reachable
before anything spawns.

## ✅ The table

`npcEnemyTemplates` is at `0x80449888`. ⚠️ `NPCTemplate` is in **no header** —
the type is referenced only in `npcdrv.h` comments — so everything below was
measured, not read.

| | |
|---|---|
| stride | **`0x68`** (104 bytes) |
| entry *n* | template id *n* |
| `initScript` | **+0x34** |
| `moveScript` | **+0x38** |
| `onHitScript` | **+0x3C** |
| `deathScript` | **+0x48** |

### How the offsets were established

Not by guessing a layout. Four script addresses were first read off a **live**
`NPCEntry` during gameplay in `he1_01`:

| script | address |
|---|---|
| init | `0x8043B8F8` |
| move | `0x804938E8` |
| on-hit | `0x80494E28` |
| death | `0x80439F10` |

Then 16,384 words from `npcEnemyTemplates` were scanned for **those four known
values**, at module load time with no map loaded. All four are present. Four
distinct 32-bit addresses, measured off a live entry during gameplay in one map
and then found in static data at load time with no map loaded, is not a
coincidence available to chance.

The stride came from three unrelated markers repeating at a fixed interval —
the constant `0x01010000` at bytes 4, 108 and 212, and name-string pointers at
32, 136 and 240. Both give 104.

⚠️ **A first pass got every offset 4 bytes too high**, because it was derived
from a hex dump reformatted by hand with a one-word shift. All four were wrong
and all four looked self-consistent — right entry, plausible spacing, right
order — and the *stride* was still correct, because the shift cancelled within
the same dump. Only a value from outside that dump exposed it. The table above
is the corrected one, cross-checked against the live-entry addresses.

✅ The scripts themselves live in DOL static data (`0x8043…`–`0x8049…`), so the
bytecode is at a fixed address even though the pointer is on a live entry. The
init script's first word is `0x0002005C` — a `USER_FUNC` with a sane argument
count, which is the evidence that these are bytecode and not merely four
non-null numbers.

✅ Entry *n* really is template id *n*: `he1_01` places template **2** (Goomba,
per its setup file), and entry 2 is where the four addresses landed.

## ⚠️ The scripts are shared, to an extreme degree

This is the finding most likely to bite someone.

| | |
|---|---|
| templates sharing template 2's **death** script | **280** |
| templates sharing template 2's **on-hit** script | **40** |

Patching template 2's death script changes the death behaviour of 280 templates
— most of the game's enemies.

### ✅ Confirmed in a live game, by accident

A patch aimed at `npcEnemyTemplates[2]` (Goomba) fired when the player hit a
**Squiglet**, which is template **250**. The Goombas in that map were behind a
wall and were never touched. The death handler ran; the on-hit handler did not,
which is consistent — 280 templates share the death script, only 40 share the
on-hit one, and the Squiglet is evidently not among those 40.

Anyone editing enemy behaviour by template needs to count what else points at
the same script first, or they will change most of the game's enemies believing
they changed a Goomba — and find out from an unrelated enemy.

*(Sources: bleck decision log D107, D110, D111, D112, D115.)*

## What is not established

- 🔶 **How many templates the table holds.** 512 was a *search* bound in our
  code, not a measured size. The table's end was never found.
- 🔶 `NPCEntry` carries ten `templateXxxScript` fields (pickup, throw,
  kouraKick, atk, misc and others). Only four were located in the template,
  because only four had addresses known in advance to search for.
- ⛔ `NPCWork.num` is **80 and constant** — the array's **capacity**, not a live
  count (`npcGetMaxEntries` is a separate symbol). Reading slot 0 and finding
  nulls says nothing; liveness is per entry.
- ⛔ `NPCWork.setupFile` (+0x18) read **0** on every frame in every map tried.
  Either the offset is wrong or it is populated on a path these runs did not
  take. Unexplained.
- ⛔ **The attract demo's maps contain no NPCs at all**, so two earlier runs
  read zero for that reason alone. See [the attract demo](attract-demo.md).
