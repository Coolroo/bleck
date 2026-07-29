---
title: What an unattended boot of SPM actually runs
description: No title screen, two maps, no NPCs, no doors and no player session — measured per frame from inside the game, and the reason three "absent" results were wrong
---

# What an unattended boot actually runs

If you boot Super Paper Mario and touch nothing, this is what happens. It
matters because it is the only thing an automated test can observe, and because
three separate correct measurements in this project read as *"the game does not
do X"* when what they really showed was *"the two maps we reached do not do X"*.

## ✅ The sequence, counted per frame

Measured by hooking all six `seq_data[].main` entries and counting frames from
inside the game, over 200 seconds:

```
order        : LOGO -> MAPCHANGE -> GAME -> MAPCHANGE -> GAME
maps loaded  : aa4_01 -> ls4_12

  LOGO         2107
  TITLE           0        <- never ran
  GAME         9227
  MAPCHANGE     196
  GAMEOVER        0
  LOAD            0
```

⛔ **`SEQ_TITLE` gets zero frames.** There is no title screen on this path, so
`seq_data[SEQ_TITLE]` is not a usable hook point unattended — the code exists
(`seq_titleMain`, `0x8017B250`) and a pointer installed there is simply never
called. ⛔ `SEQ_GAMEOVER` and `SEQ_LOAD` never run either.

🔶 The reading is that this is the game's **attract demo**: with no input it
plays the logos for ~2,100 frames (~35 s at 60 fps) and then loads gameplay maps
in sequence. `aa4_01` and `ls4_12` are ordinary map names, not menus. Not proven
— no input was injected to test the alternative, because
[input cannot be injected](method.md).

✅ Gameplay is reached in about **45 seconds** with no input at all, which is
what makes the whole unattended loop possible. Uncapping Dolphin's emulation
speed takes that to ~6 s.

⚠️ Sampling `seqWork` from outside the emulator every two seconds missed the
first `MAPCHANGE` entirely and reported the order as `LOGO -> GAME`. Counting
per frame from inside is what corrected it.

## ⛔ What those two maps do **not** contain

This is the part that costs people runs:

| | |
|---|---|
| doors (`DoorDesc` registrations) | **none** in `aa4_01`, `ls4_12` or Flipside (`mac_01`) |
| NPCs | **none at all** in the attract demo's maps |
| player session | **none** — see below |

Three findings in this project were first recorded as absences on this basis and
later overturned: "door descriptors are never registered from map init scripts"
(twice, for two different instrument reasons) and "NPC behaviour scripts are
runtime-only". Each zero was honest. Each was about map coverage.

**Before recording that something is absent, check the run visited a map that
has it**, and pair the reading with a control that would have looked different
had it been present.

Booting straight into a chosen map avoids this entirely — the game will load any
of its maps unattended if a module calls the map-change function from a hook,
which is what makes anything outside the attract demo testable without a person.

## ⛔ There is no player session

Driving into a map this way leaves **Mario invisible**: no save file was loaded
and no profile was selected, so the player character was never set up. Fine for
reading enemy placement; useless for anything touching player state.

Concretely, in the attract demo the item pouch exists but **refuses items** —
thousands of consecutive refusals across a boot, and then success the moment a
real save session begins. See [the player session page](player-session.md),
which also records two conclusions drawn from that pointer that were both wrong.

*(Sources: bleck decision log D43, D47, D48, D62, D63, D94, D101, D107, D113.)*
