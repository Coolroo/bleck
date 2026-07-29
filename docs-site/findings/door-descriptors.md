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

## Not established

- 🔶 What the `0x1A` opcode at the head of `initScript` does. It was matched and
  patched, not decoded.
- 🔶 One door, in one map. `he1_01` has exactly one `DoorDesc`.
- ⛔ There is **no lookup by name** for a `DoorDesc`, unlike NPCs
  (`npcNameToPtr`). `evtDoorGetActiveDoorDesc()` returns the door currently in
  use, which is null before gameplay. A door is identified by its position in
  the array its map registers.
- ⛔ How many doors a map registers cannot be known without reading the game's
  data — the `count` argument sits beside the array, so a bounds check has to
  happen at run time.
