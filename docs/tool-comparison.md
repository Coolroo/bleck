# What `bleck` does that the scene does not, and vice versa

Internal. An honest positioning note, written 2026-07-29 against
[`state-of-spm-modding.md`](./state-of-spm-modding.md) and the repo as it
actually stands.

⚠️ **Not for `docs-site/`.** A comparison page written by the newcomer, aimed at
a scene this project has already had friction with, needs a different tone and
probably a different author.

---

## How an SPM mod is built today, without `bleck`

A code mod is a **hand-rolled C/C++ project**: `spm-headers` for structs and
symbols, a Makefile, `elf2rel`, and `spm-rel-loader` (or the newer
`spm-loaders`) to get the REL running. `L5050/SPM-Hard-Mode` is ~105 commits of
exactly that, and it shipped.

Around it sit point tools, each good at one thing:

| Tool | Does | Licence |
|---|---|---|
| [SPME](https://github.com/InconspicuousCactus/SPME) | U8, TPL, map→FBX/GLB, LZSS, OpenGL preview | — |
| [Flint](https://github.com/Luma48/Flint) | Message/text editing with render preview | — |
| [skawo's editor](https://github.com/skawo/Super-Paper-Mario-Level-Editor-Randomizer) | Setup files, enemy spawns, randomiser | — |
| [evtpatch](https://github.com/JohnP55/evtpatch) | Runtime `evt` hooking; adds `Call`/`Return` opcodes | **GPL-3.0** |
| [spm-level-dumper](https://github.com/BraidenPsiuk/spm-level-dumper) | 300+ levels' geometry to `.obj` | — |
| [spm-loaders](https://github.com/SeekyCt/spm-loaders) | `relloader3`: `SPMP` header, per-region filenames, load-method introspection | GPLv3 |

**Nothing joins them up.** There is no "declare a mod, get a disc".

---

## What `bleck` has that nothing else does

### 1. A scripting language that compiles to the game's own VM

The largest single differentiator, and the one most easily forgotten because it
predates everything above:

```
script main {
    var speed = 2.0
    evt_sub_set_game_speed(speed)

    var i = 0
    while i < 3 {
        evt_msg_print(0, "hello", 0, 0)
        wait(30)
        i = i + 1
    }

    if i >= 3 and speed > 1.0 {
        spawn cleanup
    }
}
```

`var`, `while`, `if`/`and`/`or`, `switch`, string comparison, `spawn`, named
scripts, and **443 builtins resolved by name** with arity checking and
did-you-mean on a typo. It lowers onto a two-operand VM with no expression
stack, and the compiler refuses what will not survive lowering (`var x = f()` is
rejected with an explanation, because `evt` user funcs return through output
slots).

The rest of the scene writes `evt` as **C macros** or patches it at runtime.
Nobody else compiles a language to it. See [`scripting.md`](./scripting.md).

### 2. A mod is a declaration, not a build script

`mod.json` + `bleck mod build` → ISO / WBFS / RVZ / Riivolution. No Makefile, no
hand-written cache flush, no hand-written Dolphin INI, no manual `elf2rel`.
Placements, script patches, function hooks, map hooks and button combos are all
declared and generated at build time — **never shipped as baked bytes**, so a
change stays reviewable and undoable.

### 3. Several code mods merge into one `mod.rel`

`state-of-spm-modding.md` calls multiple code mods *"the unclaimed problem"*.
The loader opens exactly one path; `bleck` merges at **compile** time (D78), so
`chainrel`'s unsolved runtime chaining is not on the path.

### 4. It refuses rather than writes

- Every patch carries a **guard word** derived from the base DOL. Mismatch →
  nothing is written (D89, D95).
- Clearing a middle enemy slot is refused: the game stops reading at the first
  empty one (D79).
- Adding a coin to a map at its flag budget is refused (D130, D133).
- A doors table with no `code` block is refused (D134).

Each of those exists because something silently did the wrong thing first.

### 5. Unattended in-game verification

`scripts/ingame.py` builds, boots Dolphin, reads emulated memory, and shuts
down — no human watching. Plus a technique worth more than the rig: **hooking
`__assert2` makes a hang name its own cause** (D130). No equivalent surfaced in
the research.

### 6. A versioned JSON API

`bleck/api/v1/` is a real contract with a published schema, so a GUI or another
tool can drive it without shelling out per keystroke.

### 7. Cross-platform

Linux, Windows and macOS, with platform differences as **data** in
`bleck/platforms/`, not conditionals.

---

## What the scene has that `bleck` does not

**Longer than the list above, and some of it matters.**

| Gap | Who has it | How big |
|---|---|---|
| Instruction insertion / deletion in vanilla scripts, new VM opcodes | evtpatch | **Large** — see below |
| Models, textures, map geometry | SPME | Large; no overlap at all |
| Message/text editing | Flint | Medium |
| A GUI | skawo's editor | Medium; the API exists, the front end does not |
| Modern loader ABI (`SPMP`, per-region filenames, load-method introspection) | spm-loaders | Medium; `bleck` still uses the 2022 `spm-rel-loader` Gecko loader |
| Regions other than `eu0` | Hard Mode et al. | Large, and blocked on a disc |
| Real hardware | Riivolution users | Unknown — `bleck` has **never** run on a Wii |

⚠️ **And the one that matters most: shipped mods.** Hard Mode, Lunatic Pit,
Blocks of Wisdom are mods people played. The largest thing built with `bleck` is
a probe. No amount of architecture closes that gap.

---

## evtpatch specifically

**GPL-3.0.** That decides the shape of everything below.

`bleck` is MIT (D132), and `include/`-only derivation from `spm-headers` is what
keeps it that way (D37). **Vendoring evtpatch, or porting its source, would
force GPL-3 on this entire repository.**

### What it actually does that `bleck` cannot

- `hookEvt`, `hookEvtByOffset`, `hookEvtReplace`, `hookEvtReplaceBlock`,
  `patchEvtInstruction`
- **Adds two opcodes to the VM** — `Call` and `ReturnFromCall`, giving `evt` a
  call stack it lacks — by patching `evtmgrCmd`'s dispatcher and bypassing
  `make_jump_table`'s opcode bound check
- Rebuilds jump tables after mutation, because `make_jump_table` caches `lbl`
  positions at script-entry time

`bleck` does **same-size replacement only** (`code.patches`), which is precisely
the one mutation that moves no label — that is why it needs no jump-table
rebuild and why it stops there.

### Three routes, in order of cost

**1. Let the mod use evtpatch; `bleck` never touches it. — free, available now.**

A mod's `code.sources` can include evtpatch. The resulting `mod.rel` is then a
GPL-3 work, which is the *mod author's* obligation, not `bleck`'s — a compiler
does not inherit the licence of what it compiles. `bleck` stays MIT because no
evtpatch code enters this repo.

⚠️ This should be documented for mod authors rather than left implicit, since
the obligation is real and lands on them.

**2. Whole-script replacement by pointer swap. — ✅ WORKS, MIT-clean.**

`code.patches` mutates *the bytecode a pointer refers to*, which is why it is
limited to same-size replacement. Swapping **the pointer** instead gives
arbitrary logic with no jump-table problem at all, because the replacement is
built whole rather than edited in place.

⛔ **Known not to work for `MapData.initScript`**: D51 swapped it, every
mechanical check passed, and the map froze mid-load. 🔶 The untested explanation
is that the loader waits on the specific `EvtEntry` created from `initScript`.

✅ **And that reasoning does not extend to a door** (D146). A door's interact
script is started by the player, not by the map-load sequence, so nothing waits
on a particular entry. Measured: the swapped-in script ran **63 times** for one
door use — the game's own calls, separated from the harness by a self-test that
fires only past frame 600 — and the map still reached its destination.

So the replacement route works, and it needs no GPL code: build the replacement
whole and write the pointer, with no jump-table problem because nothing moves.

⚠️ **`evtpatch` is still ahead on insertion and deletion**, which this does not
attempt. What it covers is *replacement*, which is most of what the GPL
dependency was wanted for.

🔶 Only a four-instruction replacement has been run. Nothing has tested one
longer than the original, though the mechanism makes size irrelevant in
principle.

**3. Independent implementation of jump-table rebuilding and new opcodes. — expensive.**

Both are derivable from the DOL with the technique D128 established (find a
string, cross-reference it, disassemble). ⚠️ It must be derived from **our own**
analysis of the game, not from reading evtpatch's source — the game is facts,
their implementation is expression.

Only worth it if route 2 fails and a mod genuinely needs insertion or deletion.

---

## The short version

`bleck` is a **language, a pipeline and a safety layer**. Its edge is that a mod
is declared data — reviewable, diffable, mergeable — compiled by a real
toolchain, guarded by checks that refuse rather than emit a broken disc, and
verified by a rig that settles questions instead of arguing them.

It is not a content editor and should not try to become one. SPME owns assets,
Flint owns text, evtpatch owns deep script surgery. The overlap with skawo's
editor is real but narrow — setup files — and `bleck` approaches them
declaratively rather than as a GUI.

The honest weakness is not architectural. It is that nobody has shipped a mod
with it.
