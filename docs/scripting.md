# Scripting

**Status: compiles and links; does not yet run.** `bleck script build` and
`bleck mod build` produce a loadable `mod.rel`, and D38 proved a `bleck`-built
module executes in-game. But **no compiled script has ever been observed
running**, after two attempts at the entry point. Read
[Unproven](#unproven) and [`hook-points.md`](hook-points.md) before trusting
anything here.

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
- **It cannot replace a native hook.** Changing how an existing function behaves
  still means patching code — see [`code-mods.md`](code-mods.md). Scripting and
  native hooks are complementary, and a mod can ship both.
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
`symbols/`.

This is deliberate. Vendoring is *permitted* — `include/`, `decomp/` and
`linker/` are MIT — but D26's licensing question is still open, and the
generated-C design means nothing is blocked by leaving it open. Coverage varies
sharply by version: **eu0 has ~1111 symbols, kr0 only 456.** Anchor to eu0.

## Unproven

Marked explicitly, because the rest of this document reads like settled fact and
these parts are not.

- ⛔ **No compiled script has ever been observed running, after two attempts.**
  This is the one open link in the whole track. The bytecode is verified by hand
  against the opcode table, the module links and loads, and D38 proved custom
  code executes in-game — but nothing has yet made a script *run*. Attempt 1
  (`evtEntry` in `_prolog`) and attempt 2 (`seq_data[SEQ_GAME].init`) both
  produced nothing; attempt 3 (`.main`, which is what the scene actually uses)
  is built and unbooted. See [`hook-points.md`](hook-points.md) and D40.
- ✅ **`SET` / `SETI` / `SETF` — resolved (D39).** From matching decompiled
  source (`spm-decomp/src/evtmgr_cmd.c`): `SET` runs its source through
  `evtGetValue` (zone-decoded), `SETI` takes it **raw**, `SETF` works in the
  float domain. Our `SET`/`SETF` pairing was correct. ⚠️ And `SETI` is the
  escape hatch for the literals `reject_ambiguous_literal` currently refuses —
  `var a = -30000000` need not be an error. Not yet implemented.
  ⚠️ Also: `check_float` passes values through **unconverted** when above the
  float max, so `SETF` on a non-float operand silently acts as an int copy.
- ⛔ **`_prolog` is far too early to start a script — measured, not guessed
  (D38).** `evtEntry` there returns and schedules nothing, because the evt
  manager is not initialised at that point. `_prolog` now only arms a
  `seq_data` hook. The rule, and the four known hook timings, are in
  [`hook-points.md`](hook-points.md).
- 🔶 **`evtEntry(script, 0, 0)`** — priority 0 and flags 0 are taken from TTYD
  convention, not from observed SPM behaviour. **This is now a leading suspect**:
  if the third hook attempt fires but still produces no script, a scheduler that
  creates the entry and immediately filters it out would look exactly like this.
  `EVT_FLAG_START_IMMEDIATE` exists in `evtmgr.h`.
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
