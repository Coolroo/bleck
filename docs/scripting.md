# Scripting

**Status: working, verified end to end.** A script compiled by `bleck` runs
inside the game at one iteration per frame and survives a map change — measured
by reading the running game's memory from outside the emulator (D43), not by
looking at the screen. [Unproven](#unproven) lists what is still not verified.

---

## The decision, in one line

**The game already contains a scripting VM, so `bleck` compiles to it rather
than shipping one.**

Super Paper Mario ships `evt`: a bytecode interpreter driven by `evtmgrMain()`
every frame, with 120 opcodes, cooperative multitasking across up to 128
concurrent script entries, save-backed variables, and several hundred native
builtins the game already implements. Scripts are ordinary data — `EvtScriptCode
*` fields hang off NPCs, objects, items, doors and maps.

Everything follows from that:

| Problem a shipped VM would have | Why it does not arise |
|---|---|
| Port an interpreter to big-endian PowerPC | The interpreter is already there, and shipped in a retail game |
| GC pauses against a 16.6 ms frame | `evt` has no GC; the scheduler is cooperative and was tuned for this game |
| ~150 KB of injected runtime | A compiled script is a few hundred bytes |
| Hand-write bindings for every game function | `USER_FUNC` already reaches ~444 named builtins |
| A `-nostdlib` libc shim, `setjmp`, an allocator | None of it is needed |

## The pipeline

```
main.evt
  -> lexer      tokens carrying line/column
  -> parser     a syntax tree
  -> compiler   evt bytecode; addresses still symbolic
  -> emit       one C translation unit
  -> devkitPPC  compile, then relocatable link
  -> pyelf2rel  ELF -> REL
  -> overlay    files/mod/mod.rel, via the ordinary mod machinery
```

Only the last three steps need anything installed. Parsing and compiling are
pure Python, which is why `bleck script check` works with no toolchain at all.

### Why generate C instead of an object file

Two reasons, and the second is the important one.

1. It reuses the whole proven REL path (D26, D36) rather than becoming a second
   code generator that has to learn ELF and PowerPC relocations.
2. **It keeps game addresses out of `bleck` entirely.** A script calls
   `evt_mario_set_pos(...)`; the generated C declares
   `extern void evt_mario_set_pos(void);` and takes its address, and `elf2rel`
   binds the name through a symbol list at REL-build time. `bleck` never writes
   an address, never reads the symbol list itself, and therefore never has to
   redistribute one. The licensing decision (D26, still open) stays open.

Verified: `bleck script dump` output contains no `0x80` addresses, asserted by
`tests/test_script.py::TestGeneratedC::test_no_game_addresses_appear`.

## The language

Deliberately small. Every construct has to survive lowering onto a VM with
two-operand instructions and no expression stack, so nothing is offered that
implies unbounded runtime nesting.

```
-- Comments are `--` or `//`; /* block */ also works.

script main {
    wait(120)                      -- yields the frame; does not block it

    var speed = 2.0                -- type comes from the initialiser
    evt_sub_set_game_speed(speed)

    var i = 0
    while i < 3 {
        evt_msg_print(0, "hello", 0, 0)
        wait(30)
        i = i + 1
    }

    if i >= 3 and speed > 1.0 {
        spawn cleanup              -- runs as a child script
    }
}

script cleanup {
    evt_sub_set_game_speed(1.0)
}
```

`main` is the script that runs. Named, not positional, so reordering a file
cannot silently change which script starts.

### How constructs lower

| Source | Bytecode |
|---|---|
| `wait(n)` / `wait_ms(n)` | `WAIT_FRM` / `WAIT_MSEC` |
| `var x = 1` | `SET lw[0], 1` |
| `var x = 1.0` | `SETF lw[0], -239998976` |
| `a + b` (int / float) | `ADD` / `ADDF` into a scratch slot |
| `if a == b` | `IF_EQUAL` … `END_IF` |
| `if …` with float operands | `IFF_EQUAL` … |
| `while cond { }` | `DO 0` + inverted test + `DO_BREAK` … `WHILE` |
| `loop n { }` | `DO n` … `WHILE` |
| `return` | `END_EVT` (ends the script, not the array) |
| `f(a, b)` | `USER_FUNC &f, a, b` |
| `spawn s` | `RUN_CHILD_EVT &s` |
| `gw[3]` | operand `-49999997` |

`evt` has no condition-tested loop — only a counted `DO n` … `WHILE`. `while`
is therefore an unbounded `DO 0` whose first act is to test the negated
condition and `DO_BREAK`. That is why the emitted opcode for `while i < 3` is
`IF_LARGE_EQUAL`, not `IF_SMALL`.

### Two things the encoding forces

**Integers and floats never mix.** `evt` has separate opcodes and no coercion,
so `1.0 + 1` is a compile error rather than a reinterpretation of the operand's
bits.

**Some integers cannot be written literally.** `evt` recovers an operand's
storage class from its *numeric range*: a value near -30000000 **is** `lw[0]`,
as far as the VM is concerned. There is no encoding that distinguishes the two.
So `var a = -30000000` is rejected — the alternative is emitting something that
silently reads a variable. ⚠️ This is stricter than it needs to be: `SETI`
(0x33) takes its operand raw and would encode such literals correctly (D39).
Not yet implemented. Floats are fixed-point (`value * 1024` biased by
-240000000), giving ~3 decimal places and a magnitude ceiling near 48000; over
that is rejected rather than wrapped into the address window.

### Slots

`evt` gives each script 16 local work slots. Declared variables are handed out
from slot 0 upward, scratch for intermediate results from slot 15 downward. They
meet in the middle and running out is a compile error naming the script. `gw[]`,
`gf[]`, `lf[]` and the saved families are reachable explicitly.

⚠️ **`gsw[]` / `gswf[]` persist in the save file** and are what the game's own
progression uses. Writing one can corrupt a playthrough. They are exposed
because reading them is how a script observes story state, but there is no
guard on writing.

## What this is not

Honest scope, because the ceiling is real:

- **`evt` is an event/cutscene language, not a systems language.** It is
  excellent at "wait, move, speak, branch on a flag, spawn a child" and has no
  answer for "run every frame inside the collision solver".
- **It cannot replace a native hook.** `USER_FUNC` only reaches declared evt
  builtins, all of which take `(EvtEntry *, bool)`, so an ordinary game
  function like `mapDataPtr` is unreachable from a script whatever syntax we
  add. ✅ **A mod can now ship C alongside its script** via `code.sources`
  (D46) — that is what reaches those functions, and what lets a mod attach
  behaviour to a map, door, item or NPC by name.
- **`USER_FUNC` is the only escape hatch today.** Whatever the game's builtins
  can do, a script can do; nothing else. ⚠️ The VM *also* has `SET_RAM`/`GET_RAM`
  for arbitrary memory, but **the language exposes no syntax for them** — an
  earlier draft of this document claimed otherwise and was wrong.
- **The language reaches 39 of the VM's 120 opcodes.** Not yet lowered to:
  `SET_RAM`/`GET_RAM` (raw memory), `SWITCH`/`CASE*`, `IF_FLAG`/`IF_NOT_FLAG`,
  `RUN_EVT` (detached spawn), `SET_PRI`/`SET_SPD`, `CHK_EVT`, the `READ` array
  family, `CLAMP_INT`, and the six `DEBUG_*` opcodes. None are blocked by the
  design; they are simply unwritten.
- **Calls are statements, not expressions.** `evt` user funcs return results
  through output slots rather than a return value, so `var x = f()` is rejected
  with an explanation.
- **One code mod per build.** The Gecko loader opens exactly one
  `/mod/mod.rel`. A chain containing two code mods fails loudly rather than
  silently dropping one.
  ⚠️ **`chainrel` is not the answer** — D39 found it to be a three-commit stub
  with its loader body wrapped in `#if 0`. Nobody in this scene has solved
  multi-mod loading, which makes it the clearest unclaimed problem available.

## Symbol lists are not shipped

Resolving `evt_mario_set_pos` to an address needs `spm.<version>.lst` from
[spm-headers](https://github.com/SeekyCt/spm-headers). `bleck` does not vendor
it. Point `BLECK_SYMBOLS_DIR` at a directory containing it, or drop it in
`work/symbols/`.

This is deliberate. Vendoring is *permitted* — `include/`, `decomp/` and
`linker/` are MIT — but D26's licensing question is still open, and the
generated-C design means nothing is blocked by leaving it open. Coverage varies
sharply by version: **eu0 has ~1111 symbols, kr0 only 456.** Anchor to eu0.

## Unproven

Marked explicitly, because the rest of this document reads like settled fact and
these parts are not.

- ✅ **Scripts run** (D43). Verified autonomously: 60 loop iterations per second
  from a `wait(1)` loop, and the script keeps running across a map change.
- ⚠️ **The game shares `gw[]` with your scripts.** `gw[10]` is written by the
  game's own scripts; `gw[30]` was untouched across a full session. Low slots
  are occupied — prefer high ones, and do not assume any slot is yours.
- 🔶 **Only `eu0` has been booted.** Other versions compile but are untested.
- ✅ **`SET` / `SETI` / `SETF` — resolved (D39).** From matching decompiled
  source (`spm-decomp/src/evtmgr_cmd.c`): `SET` runs its source through
  `evtGetValue` (zone-decoded), `SETI` takes it **raw**, `SETF` works in the
  float domain. Our `SET`/`SETF` pairing was correct. ⚠️ And `SETI` is the
  escape hatch for the literals `reject_ambiguous_literal` currently refuses —
  `var a = -30000000` need not be an error. Not yet implemented.
  ⚠️ Also: `check_float` passes values through **unconverted** when above the
  float max, so `SETF` on a non-float operand silently acts as an int copy.
- ⛔ **`_prolog` is far too early to start a script — measured, not guessed
  (D38).** `evtEntry` there returns and schedules nothing. `_prolog` now only
  installs `seq_data` hooks; the script is started from gameplay and re-started
  after anything that resets evt state. The four known hook timings are in
  [`hook-points.md`](hook-points.md).
- ✅ **`evtEntry(script, 0, 0)` is fine** — it returns a valid `EvtEntry *` and
  the script it creates executes (D43). The priority and flags were taken from
  TTYD convention; that guess turned out correct.
- 🔶 **Flag slots are read as integers.** `gf[2]` and `lf[2]` compile to an
  ordinary `IF_EQUAL` against the encoded operand, on the assumption that
  `evtGetValue` decodes the flag windows like any other. The VM has dedicated
  `IF_FLAG`/`IF_NOT_FLAG` opcodes that this does not use, so if flag tests
  misbehave, that is the reason.
- 🔶 **Output parameters are untested.** Many builtins return values by writing
  into a slot passed as an argument — `evt_sub_random(s32 max, s32& ret)`. A
  variable passed by name compiles to exactly that slot operand, so
  `evt_sub_random(10, roll)` *should* leave the result in `roll`. It has never
  been observed doing so.

## Hot reload, and why the architecture allows it later

Not built. Recorded because the design was chosen partly to keep it cheap.

Live-patching literature converges on one rule: **reload is cheap when the unit
of replacement is a value in a dispatch table the runtime owns, and expensive
when it is machine code.** Restoring patched instruction bytes undoes the
branch, but not the allocations, callbacks, spawned entities or globals the code
already touched — the reason Everest (a PC mod loader with a managed runtime)
removed late-loading, and why no console modding toolkit ships code hot reload.

A compiled script is **data**. That puts this on the cheap side of the line.
Two supporting facts, both verified from source by research rather than assumed:

- Dolphin's Riivolution redirection re-opens the host file on **every** disc
  read (`DiscContent::Read` in `DirectoryBlob.cpp`), with no sector cache in
  front of it and `FILE_SHARE_WRITE` on Windows. Editing a file on the host is
  visible to the running game. Real hardware has the same property over RiiFS.
- SPM links `DVDMgrOpen`/`DVDMgrRead`/`DVDMgrClose`, so re-reading a file from
  the running game is ~30 lines.

⛔ **Reloading a rebuilt REL is ruled out**, separately: the symbol list contains
`OSLink` but **no `OSUnlink`**, and SPM's `relmgr` has no unload path at all.

## Files

| Path | What |
|---|---|
| `bleck/script/evt.py` | Opcodes and operand encoding. No addresses |
| `bleck/script/lexer.py` | Hand-written scanner; every token carries a position |
| `bleck/script/syntax.py` | AST. Named `syntax`, never `ast` |
| `bleck/script/parser.py` | Recursive descent, precedence climbing |
| `bleck/script/compiler.py` | Lowering, slot allocation, type checking |
| `bleck/script/emit.py` | Bytecode -> C |
| `bleck/backends/toolchain.py` | Compiler discovery, flags, `pyelf2rel` |
| `bleck/mods/code.py` | Compiling a mod's script into its overlay |
