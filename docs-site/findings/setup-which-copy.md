---
title: Which setup file the game reads
description: Enemy placement files exist twice on the disc, byte-identical. The game reads the standalone one, and we got this backwards once
---

# The game reads the **standalone** `files/setup/<map>.dat`

Enemy placement data exists in **two places** on a Super Paper Mario disc, and
the two copies are byte-identical:

| copy | path |
|---|---|
| standalone | `files/setup/<map>.dat` |
| embedded | `./dvd/setup/<map>.dat`, inside `files/map/<map>.bin` |

`files/setup/aa1_01.dat` and the copy inside `map/aa1_01.bin` are the same
11,204 bytes with matching SHA-256. Of the first 40 map archives, **17 embed a
setup file and 23 do not.**

✅ **The game spawns from the standalone `files/setup/<map>.dat`.** Editing only
the embedded copy is a silent no-op.

## The experiment

Both copies were made to describe a **different enemy**, with every other slot
cleared, so exactly one enemy could appear and its identity would name the
winner:

| copy | enemy placed |
|---|---|
| `files/setup/he1_01.dat` | Squig (`e_octar`, template 148) |
| `map/he1_01.bin` → `./dvd/setup/he1_01.dat` | Sproing-Oing (`e_tekti`, template 144) |

**A Squig appeared.**

## ⛔ We published the opposite first, and the reason is instructive

An earlier measurement established — correctly, and it is still true — that the
**embedded** copy is the one loaded into MEM1, while the standalone copy is
read into MEM2. The inference drawn from that was *MEM1 is the fast working
RAM, therefore MEM1 holds the copy in use*.

That inference was wrong. It was flagged as an untested hypothesis at the time
and then built on anyway, and it took three entries and a purpose-built
experiment to undo.

🔶 The reading that now fits: the MEM1 copy is the map archive's own payload,
decompressed along with everything else the archive ships, and the *separately*
loaded MEM2 copy is what the spawn path walks. **Not tested** — and since
reasoning from residency is exactly what went wrong the first time, it stays a
hypothesis.

*(Sources: bleck decision log D53 ⛔ wrong, D59, D62 ✅ the experiment.)*

## Practical consequence

If you edit enemy placement, write **both** copies. Writing only the standalone
one works today; writing only the embedded one does nothing at all and looks
exactly like a mod that failed to build. Leaving a stale embedded copy behind
also misleads anyone who later inspects the archive.

## See also

- [The setup file format](setup-file-format.md) — what is in the file, and the
  version→stride table
