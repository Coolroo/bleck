---
title: Where a door's scripts live, and what patching one does
description: DoorDesc registration from map init scripts, the three script pointers, what each opens with, and what one use of a door actually runs
---

# Door descriptors: where a door's scripts live

**All addresses are PAL rev 0 (`R8PP01`, "eu0") and do not transfer to other
revisions.**

## ✅ A map registers its doors from its own init script

`MapData.initScript` for a map contains a `USER_FUNC` call to
`evt_door_set_door_descs(descs, count)`, and the descriptor array's address is
**literally in the bytecode**. That means it can be read by walking the init
script — no interception, no hook, no trampoline — and it is readable at module
load time, before gameplay starts.

⚠️ Finding it requires the *correct* argument count:
[the header declares the wrong one](evt-door-argc.md), which is why we
originally recorded that these calls do not exist.

One 90-second scan of loaded map init scripts:

| | |
|---|---|
| `evt_door_set_door_descs` | 1 call (`he1_01`), `DoorDesc *` = `0x80D2FBB0`, count **1** |
| `evt_door_set_map_door_descs` | 3 calls (`he1_01`), `MapDoorDesc *` = `0x80D2F940`, count **3** |
| `evt_door_set_dokan_descs` | 3 calls (`mac_01`) — pipes |
| walks truncated at the 4096-word limit | 0 |

So `he1_01` (Flipside's first house interior area) registers **one door and
three loading zones**, and Flipside itself (`mac_01`) registers pipes.

🔶 Five maps is not the game, and each `count` was read as a literal — a script
that *computed* its count would not be handled by this walk.

## ✅ The two descriptor types are different things

From `spm-headers`' `evt_door.h`, with the offsets confirmed by reading them
back:

| struct | size | what it is |
|---|---|---|
| `DoorDesc` | `0x58` | the door the player interacts with |
| `MapDoorDesc` | `0x20` | a **loading zone** — `destMapName` +0x14, `destDoorName` +0x18 |

`MapDoorDesc[0]` in `he1_01` reads `destMapName` = **`he1_02`** and
`destDoorName` = **`doa1_l`**, both as plain strings. That is what confirms the
pointer and the offsets at once: a wrong pointer does not spell a map name.

## ✅ `DoorDesc` carries three script pointers

| field | offset | `he1_01` door 0 | opens with |
|---|---|---|---|
| `interactScript` | +0x40 | `0x80D2FB78` | `0x0002003C` — **`MULF`**, argc 2 |
| `initScript` | +0x50 | `0x80D2F9E0` | `0x0002001A` — opcode `0x1A`, argc 2 |
| `moveScript` | +0x54 | `0x80D2FB70` | `00000002 00000001` — [an empty script](evt-script-end.md) |

All three pointers were measured **twice, by different probes in different
runs**, which is what confirms the offsets. A wrong offset landing on some other
non-null word would look identical from a single reading.

⚠️ **A door's interact script opens with a float multiply**, not a `USER_FUNC`
and not a `DEBUG_PUT_MSG`. Nobody would guess that, and it means a tool that
verifies "the instruction I am about to replace is what I think it is" has no
useful default for doors — the opening word has to be measured per door.

## ✅ One use of a door runs its interact script many times

Measured with a person actually walking through the door (this cannot be done
unattended — see [the method](method.md)):

| patched script | status | times entered |
|---|---|---|
| `interactScript` | applied | **62** |
| `initScript` | applied | **1** |
| `moveScript` | refused (guard declined; it is one word) | — |
| index 9, past the end | no such script | — |

The 62 entries arrived in a single burst of about one second — roughly one per
frame at 60 fps.

⛔ The obvious worry — that the patch had *broken* the door, leaving the player
standing in it and retriggering — is dead. The player reported: the door opened,
the map changed, and the scripted conversation on the other side ran. So the
repeated entries are real behaviour.

🔶 Whether that is a per-frame restart of the script or a loop inside it is
**not** established. Nothing measured distinguishes the two.

### ⚠️ And the door still worked with its first instruction destroyed

The patch replaced `interactScript`'s opening `MULF` with a `USER_FUNC` of the
same size: the argument *count* and the trailing argument word survive, but the
operation is simply gone. The multiply never happens, and the door opens,
transitions and runs its conversation anyway.

That is a useful data point about the script (the leading multiply is not
load-bearing) and a caution about the technique: **replacing an instruction at
offset 0 destroys it.** It happened to be harmless here.

*(Sources: bleck decision log D101, D102, D103, D104, D116, D117.)*

## ✅ What the interact script actually contains

`he1_01` door 0's `interactScript`, dumped from RAM and decoded, is **four
instructions**:

```
MULF      LW(0), <float constant>
USER_FUNC 0x800ED75C, 0x80CB35EC, 0, LW(0), 0
END_EVT
END_SCRIPT
```

`0xFE363C80` is `-30000000` — evt's encoding for a **local-work variable**, not
a literal. `0x800ED75C` is unnamed in the `eu0` symbol list but sits between
`evt_mapobj_trans` (`0x800ED6C0`) and `evt_mapobj_scale` (`0x800ED7F8`), so it
is an `evt_mapobj_*` transform.

**So the interact script is a per-call animation step**: multiply a local by a
constant, apply it to a map object. `LW(0)` is supplied by whatever starts it.
That is why one use of a door runs it many times — each call is one frame of the
door opening, not one "the player used the door" event.

⚠️ **It contains no branch at all**, so it does not check where the player is.
The requirement to stand on a door and press up lives in whatever *calls* this.

⛔ **The transition is not in it.** Started directly with `evtEntry` — twice,
once with the active door set — it produced a real `EvtEntry`, no assert, and
**no map change**. The destination belongs to the `MapDoorDesc` covering the
same doorway.

## ✅ A game-wide census

Read from every map in one boot (`mapDataPtr` is populated for maps that are not
loaded), so this is the whole game rather than one level:

| | |
|---|---|
| maps registering a door of either kind | **368** |
| maps with a **scriptable** `DoorDesc` | **11** |
| `DoorDesc`s in the entire game | **35** |
| `MapDoorDesc` loading zones | **691** |

Nearly every scriptable door is a house door in Flipside/Flopside (`mac_*`),
named `ie_*_doa` — 家 (*ie*, house) plus *doa*. A map with three visible
doorways may expose **one**; Lineland Road does.

## ✅ `EvtDoorWork`, which upstream marks entirely unknown

`spm-headers` declares `EvtDoorWork` as `u16 flags` followed by
`u8 unknown_0x2[0x57c - 0x2]`. Four of those offsets are now known, read out of
the functions that use them (`evt_door_wp` = `0x805AE020` on eu0):

| offset | what | how it was found |
|---:|---|---|
| `+0x000` | `flags`. **Bit 11 set means the active-door pointer is valid** | `evtDoorGetActiveDoorDesc` tests it |
| `+0x2D8` | the active `DoorDesc *` | `evtDoorGetActiveDoorDesc` returns it |
| `+0x36C` | the `MapDoorDesc` array | `evt_door_set_map_door_descs` stores it |
| `+0x370` | how many | stored beside it |
| `+0x374` | **per-zone event slots**, 2 words each, indexed `+ index*8 + which*4` | `evt_door_set_event` writes here |

## ✅ A loading zone can carry a script after all

`MapDoorDesc` has no script fields — but
`evt_door_set_event(char *door, int which, EvtScriptCode *script)` finds a zone
by its `name_l` and stores a script pointer in the slot array above.

✅ **Watched working.** Both slots read `0` beforehand; after calling it slot 0
held the supplied script; and when the player walked into that zone **the
attached script ran**, one call, immediately before the map changed. The game
uses the same mechanism itself on **13** maps.

⚠️ **An attachment does not survive a map change.** The slots live in per-map
work, so arriving somewhere new replaces them — anything built on this has to
re-attach each time the map is entered.

⚠️ It is an **evt user func**, so it cannot be called from C — it reads its
arguments from an `EvtEntry`. And argc counts the function pointer, so three
arguments is argc **4**.

## ✅ The script pointer can be replaced outright

`interactScript` is an ordinary pointer in a descriptor that lives in map data,
and the address can be read at load time — so it can be **written**, pointing at
a script supplied by a mod. That gives arbitrary logic with no jump-table
problem, because the replacement is built whole rather than patched in place.

Measured on `he1_01` door 0, with a replacement of one `USER_FUNC`:

| | |
|---|---|
| the field, re-resolved every frame during play | still the replacement |
| calls when the player used the door | **63** |
| calls attributable to the test harness | **1** |
| the map still reached | ✅ `he1_06` |

The 63 calls match what this script *is* — a per-call animation step, so a door
opening over about a second at 60fps runs it about sixty times.

⚠️ **The transition still happened**, because it was never in this script.
Replacing a door's interact script changes how it animates, not where it goes.

⛔ **This does not work for a map's init script.** Swapping `MapData.initScript`
passes every mechanical check and freezes the map mid-load — the untested
explanation being that the loader waits on the specific `EvtEntry` it created.
A door's script is started by the player instead, with nothing waiting on it.

## Not established

- 🔶 What the `0x1A` opcode at the head of `initScript` does. It was matched and
  patched, not decoded.
- 🔶 What the second event slot (`which` = 1) means. Only slot 0 was exercised.
- 🔶 Whether the interact script can be replaced with something *longer* than
  the original. The pointer swap makes size irrelevant in principle, and only a
  four-instruction replacement has been run.
- ⛔ There is **no lookup by name** for a `DoorDesc`, unlike NPCs
  (`npcNameToPtr`). `evtDoorGetActiveDoorDesc()` returns the door currently in
  use, which is null before gameplay. A door is identified by its position in
  the array its map registers.
