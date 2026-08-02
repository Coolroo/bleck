---
title: How these were measured
description: Reading a running game's memory from outside Dolphin, and the probe rules that were learned expensively
---

# How these were measured

Almost everything in this section was established the same way: a small
PowerPC module runs **inside** Super Paper Mario, writes numbers to a fixed
address, and a script **outside** Dolphin reads that address while the game is
still running.

This page describes the method, because it is reusable and costs nothing to
share. Nothing here is specific to `bleck` beyond the file names.

## Why not just look at the screen

The decomp ([SeekyCt/spm-decomp](https://github.com/SeekyCt/spm-decomp)) is
about 2.34% matched, so for most of the game there is no source to read. The
obvious alternative — change something, boot it, watch — produced **two wrong
conclusions in three attempts** on this project before the rig existed. A human
watching a screen cannot distinguish "did not happen" from "happened somewhere
I was not looking", and cannot count.

## The rig

1. Compile a REL that the game loads, and give it a `_prolog` that installs
   whatever it needs.
2. Reserve a **report block**: a fixed address the game never touches. The
   module writes counters, addresses and copied strings there.
3. Boot Dolphin headless-ish and unattended.
4. From the host, attach with
   [`dolphin-memory-engine`](https://github.com/aldelaro5/Dolphin-memory-engine)
   and read the block every few seconds while the game runs.
5. Shut Dolphin down. A run costs 2–3 minutes.

### The report block address

`0x80005000` (PAL rev 0, and the same in every region) — inside the **unused TRK
interrupt vector table**. It is free, it is at a fixed address, and the Gecko
REL loader parks its own memcpy at `0x80004000`, well below it. Reading it needs
no symbol and no allocation, and nothing in the game writes there.

Being at a *fixed* address is what makes an outside reader trivial: no pointer
chase, no scanning, no signature matching.

### Count inside; do not sample outside

The single biggest improvement over polling the game's own globals from outside
is that **a counter incremented per frame cannot fall between two samples**.

- Sampling `seqWork` every two seconds from the host missed an entire
  `MAPCHANGE` sequence; hooking all six `seq_data[].main` entries and counting
  frames showed the real order was `LOGO → MAPCHANGE → GAME`, not `LOGO → GAME`
  (D43, corrected by D47).
- Even at 3-second sampling, a later run watched a door being used, a map
  change, and a scripted conversation on the other side — and reported the same
  map name for the whole run, because the emulator was running at ~458 fps and
  the transition fell between two reads (D117).

If a thing can happen for one frame, **count it in the game**; do not look for
it from outside.

## Five rules, each learned by losing a run

!!! warning "A probe must report the precondition it depends on"

    Not just the value it went looking for. Three separate runs measured
    nothing and reported it as a zero (D109): one gated every read on
    `SEQ_TITLE`, which an unattended boot never enters; one returned early on a
    null pointer and left four zeroes behind, indistinguishable from reading
    four zeroes; one moved to the right sequence but still had no player
    session. Each was diagnosable in a single run *only* where a sentinel
    existed — such as `SEQ_SEEN`, a bitmask of which sequences were actually
    observed, added precisely because "stopped at TITLE" and "never reached
    TITLE" produce identical silence.

**A control must be aimed, not merely working.** Two entries concluded that door
descriptors are never registered. Both had controls; both controls passed. They
proved the instruments *worked*, not that they were pointed at the right thing —
one searched for a single function at an argument count taken from a header that
was wrong, and the other hooked the function in three maps that do not contain
the call (D93, D94, corrected by D101/D102). A better control has an expected
value **known in advance from an unrelated run**: reading back
`evt_hitobj_attr_onoff`'s header word as `0x0005005C`, a number measured earlier
for another reason, proves headers are being decoded at the right offset before
any door number is read.

**Before recording that something is absent, check the run visited a map that
has it.** Three times a real measurement read as a capability being missing
because the unattended boot only ever reaches two maps
([the attract demo](attract-demo.md)), and neither registers a door or contains
a single NPC (D94, D101, D107).

**Cross-run agreement, not internal consistency.** A structure's field offsets
were derived from a hex dump that had been reformatted by hand with a one-word
shift. All four offsets came out wrong, and all four looked self-consistent —
right entry, plausible spacing, right order. The stride derived from markers
*inside* the same dump was correct, because the shift cancelled. Only a value
from **outside** that dump exposed it (D111, corrected by D112).

**Report-block fields must be disjoint.** One probe's `STATUS(3)` shared a word
with its frame counter, so the row it was written to was overwritten every
frame and its status was never observed at all (D104).

## Some things do not need a boot

Tables that ship in the binary can be read from `sys/main.dol` directly: no
emulator, no 2-minute run, byte-identical every time. The
[538-entry item table](item-data-table.md) was decoded that way. Reading live
memory is right for tables that are only populated at run time, and wasteful
for ones that are static.

## What the method cannot do

⛔ **Controller input cannot be injected into an *unattended* run** (D48).
Dolphin's emulated Wiimote here binds to a DirectInput keyboard device, and
DirectInput polls device state rather than reading the window message queue —
so `SendKeys` and `PostMessage` are invisible to it. Twelve attempts produced a
run byte-identical to the no-input one.

⚠️ **The narrower statement is the true one.** Injection at scancode level —
`SendInput` with `KEYEVENTF_SCANCODE` — does reach Dolphin, and the test rig can
press buttons that way. But it needs a Windows host with an **unlocked session**
and Dolphin in the **foreground**, so it cannot run in CI or while nobody is
there. Recording the blanket ⛔ for as long as we did closed off
button-triggered work that was reachable all along.

So anything behind a button press still needs a person present: using an item
from a menu, hitting an enemy, walking through a door. Those runs are worth preparing
for with an unattended one first — a "verification boot" whose only purpose was
to check the instrument before spending a human's twenty minutes returned four
findings on its own (D113).

🔶 **Everything here is Dolphin's behaviour.** Nothing in this section has ever
been run on real Wii hardware, including the cache-flush results, which depend
on Dolphin's cache model.
