# Scripting

**Status: implemented.** `bleck script build` and `bleck mod build` compile
scripts into a loadable `mod.rel`. Not yet booted in-game — see
[Unproven](#unproven) before trusting any of this.

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
silently reads a variable. Floats are fixed-point (`value * 1024` biased by
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
  silently dropping one. `chainrel` is the eventual answer.

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

- 🔶 **No compiled script has been run in-game.** The bytecode is verified by
  hand against the opcode table and the REL is structurally valid
  (`bleck info` parses it), but structural validity is not runtime correctness —
  the same caveat D26 raised, and D25/D36 are what settled it for assets.
- 🔶 **`SET` (0x32) is assumed to be the integer assignment opcode and `SETF`
  (0x34) the float one.** This follows the `ADD`/`ADDF` pairing and TTYD's macro
  conventions, but `SETI` (0x33) exists and its exact role is not documented in
  `spm-headers`. If integer assignment misbehaves in-game, this is the first
  thing to check.
- 🔶 **`_prolog` starts the script before any map is loaded.** Whether a given
  builtin is safe to call that early is untested; `wait(120)` in the sample mod
  is a guess, not a measurement.
- 🔶 **`evtEntry(script, 0, 0)`** — priority 0 and flags 0 are taken from TTYD
  convention, not from observed SPM behaviour.
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
