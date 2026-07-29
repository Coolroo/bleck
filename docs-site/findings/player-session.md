---
title: The pouch, the save files, and the missing player session
description: pouchGetPtr returns a stable address whose contents mean different things at different times — two conclusions drawn from that pointer alone were both wrong
---

# The pouch, the save slots, and the player session

**PAL rev 0 (`R8PP01`, "eu0").**

## ✅ `pouchGetPtr()` is a stable address

It returned **`0x80511A28`** on every frame that was sampled — during the
[attract demo](attract-demo.md) *and* during a real save session started by a
person, in the same boot.

⛔ **A pointer's identity is therefore not a session discriminator.** A probe
written to re-do its work "whenever the pouch pointer moves", on the assumption
that a new session means a new allocation, would never have fired. The pointer
never moved.

## ✅ `pouchAddItem` works from injected code — but not always

| context | result |
|---|---|
| attract demo | **refused**, 3,564 consecutive attempts in one run (~12,000 across a boot in another), no crash |
| real save session | **returned true** on the first attempt, item granted |

Same pointer throughout. So the correct description is *"there is a pouch and it
will not take an item"*, not *"there is no pouch"*.

That a mod can put an item into the player's inventory is useful in itself: a
test that needs a specific item no longer needs a person to go and find one.

## ⚠️ Two conclusions from this pointer, both wrong

Worth stating plainly, because the same trap caught two runs from opposite
directions:

- ⛔ An earlier run recorded `pouchGetPtr()` as **null** "before the load, after
  the load, during gameplay, at every point tried", and built a conclusion on
  it: the demo has no player session, so there is nothing to load into. A later
  run read `0x80511A28` every frame in the same circumstances. **The null it saw
  was real; the pointer it was reading was not the one it named.**
- ⛔ The pointer-moves heuristic above, which would have recorded a working
  capability as impossible. What saved that run was an unrelated rule — retry
  while refused — added for a different reason.

**`pouchGetPtr()` is a stable address whose contents mean different things at
different times.** Read the *behaviour*, not the pointer.

## ✅ The NAND save file array

| | |
|---|---|
| `nandGetSaveFiles()` | `0x80AD4D80`, non-null **from frame 1** |
| slot 0 (written) | flags `0`, checksum **`0x3714`** |
| slots 1–3 (empty) | flags `0x10000`, checksum `0x3FD` — **byte-identical to each other** |
| `nandLoadSave(0)` | safe to call; 4,172 gameplay frames followed, no crash |

✅ **A written slot is distinguishable from an empty one**, which matters because
loading an empty slot would look like it worked. Three slots sharing identical
flags *and* checksum are defaults; the fourth differs.

✅ **On-screen "slot 1" is index 0.** Confirmed against a save a person had just
made in slot 1.

⛔ **`nandLoadSave(slot)` populates the save array, and nothing enters it.** The
game carried on with the attract demo afterwards. Player state is created by the
game's own load path (`seq_load_sub_loadMain`, `0x8017D1AC`, and the `LOAD`
sequence), which an unattended boot never enters. 🔶 Driving the sequence machine
into `LOAD` is the untried route; calling the loader function is not enough.

*(Sources: bleck decision log D108, D109 — whose stated evidence is superseded —
D113, D115.)*
