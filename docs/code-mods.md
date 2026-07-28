# Code Mods — Design

**Status: built.** Scripts (D37, D43) and native sources (D46) both compile
into a mod's `mod.rel` through `bleck mod build`.

> **Read [`scripting.md`](./scripting.md) first.** Most of what this document
> anticipated — compiling into `overlay/files/mod/mod.rel`, the `code` block in
> `mod.json`, the single-slot problem — is implemented, but via a route this
> document did not consider: compiling to the game's own `evt` bytecode VM
> rather than writing C by hand. This document remains the reference for
> **native hooks**, which scripting does not replace.

How `bleck` should build and package compiled PowerPC code, as opposed to the
asset overlays covered in [`mods.md`](./mods.md).

---

## What a code mod actually is

Not a patched executable. The pipeline is:

```
freestanding PowerPC C/C++
  → compile (no libc, -ffreestanding)
  → link relocatably against a per-version symbol list
  → ELF → REL  (Nintendo relocatable module)
  → placed on the disc as /mod/mod.rel
  → a Gecko code loads and runs it at boot, after the game's own REL
```

The game is never modified. Our code is a *separate module* loaded alongside it,
hooking existing functions by address. This is why the decomp being ~2.3%
complete is irrelevant (D1) — we link against symbol addresses, not source.

---

## What already exists upstream

Verified by cloning, not assumed:

| Piece | Source | Status |
|---|---|---|
| Gecko loader code | `spm-rel-loader/loader/*.txt` | **pre-assembled**, one per region |
| Build flags & framework | `spm-rel-loader/rel/` | needs devkitPPC |
| Symbols & structs | `spm-headers` | `linker/spm.eu0.lst`, 33,661 B |
| ELF → REL | **`pyelf2rel`** (PyPI 1.0.9) | ✅ **pure Python, installs cleanly** |

Two findings that materially simplify this:

**`pyelf2rel` replaces the C++ `elf2rel`.** Upstream's Makefile wants
`$(TTYDTOOLS)/bin/elf2rel`, a compiled binary. The same author's `pyelf2rel` is
on PyPI, installed here without incident, and exposes both a CLI and a Python
API — so `bleck` can call it in-process rather than shelling out to a tool the
user must build.

**The Gecko loader needs no assembler.** `spm-rel-loader/loader/` ships
pre-assembled codes per region. The eu0/eu1 one is a `C2` insert at `0x8023E5FC`
with `./mod/mod.rel` embedded as ASCII. We can ship it as data.

### The exact build contract

From `spm-rel-loader/rel/Makefile`:

```
MACHDEP  = -mno-sdata -mgcn -DGEKKO -mcpu=750 -meabi -mhard-float
CFLAGS   = -nostdlib -ffreestanding -ffunction-sections -fdata-sections -O3 $(MACHDEP)
CXXFLAGS = -fno-exceptions -fno-rtti -std=gnu++17 $(CFLAGS)
LDFLAGS  = -r -e _prolog -u _prolog -u _epilog -u _unresolved -Wl,--gc-sections -nostdlib
```

`-r` is the important one: a **relocatable** link, which is what `elf2rel`
consumes. `_prolog`/`_epilog`/`_unresolved` are the REL entry points.

---

## The toolchain — ✅ working without devkitPPC

devkitPPC is not obtainable here (`apt.devkitpro.org` returns 403 and empty
arm64 package lists), but **Debian's `gcc-powerpc-linux-gnu` 14.2.0 produces a
valid REL.** Verified end to end.

Of the upstream flags, only **`-mgcn` is rejected** — it is devkitPPC-specific
multilib selection, and dropping it is safe because `-mcpu=750 -meabi` are passed
explicitly. `-mno-sdata`, `-meabi`, `-mhard-float`, `-mcpu=750` all work.

⚠️ **One addition is mandatory: `-fno-pic -fno-PIE`.**

Debian's GCC defaults to PIE; devkitPPC does not. Without these flags the
compiler emits `R_PPC_REL16_HA` (type 252) relocations for PC-relative
addressing, and `pyelf2rel` rejects them:

    pyelf2rel.error.UnsupportedRelocationError: Unsupported relocation type 252

With them, only `R_PPC_ADDR16_HA`, `R_PPC_ADDR16_LO` and `R_PPC_REL32` appear —
all supported. **This is the single non-obvious thing about using a distro
compiler here.**

### Verified working recipe

```bash
MACHDEP="-mno-sdata -DGEKKO -mcpu=750 -meabi -mhard-float"
NOPIC="-fno-pic -fno-PIE"

powerpc-linux-gnu-gcc -c main.c -o main.o \
    -nostdlib -ffreestanding -ffunction-sections -fdata-sections -O3 -Wall \
    $MACHDEP $NOPIC

powerpc-linux-gnu-gcc main.o -o main.elf \
    -r -e _prolog -u _prolog -u _epilog -u _unresolved \
    -Wl,--gc-sections -nostdlib $MACHDEP

elf2rel -i main.elf -s spm-headers/linker/spm.eu0.lst -o mod.rel --rel-id 2
```

Produces `ELF 32-bit MSB relocatable, PowerPC` → a 264-byte **REL v3**, parsed
successfully by our own `bleck info`. Header checks out: module id 2 (the game
is 1), entry sections 1/3/4 wired up, `bssSize=4`, relocation and import tables
present.

⚠️ **Structural validity is not runtime correctness.** devkitPPC targets
`powerpc-eabi`; Debian's targets `powerpc-linux-gnu` (SysV). `-meabi` asks for
EABI conventions, but differences around small-data registers and struct passing
could still produce code that builds cleanly and misbehaves when run. **This must
be proven by booting it**, exactly as the asset pipeline was (D25).

**Fallback if the ABI gamble fails:** build RELs on Windows with real devkitPPC
and package with `bleck` here. The split is clean — the REL is just a file the
overlay places.

---

## C++ — ✅ builds, 🔶 unproven in-game (D85)

`code.sources` accepts `.c`, `.cpp`, `.cc` and `.cxx`. Which language owns which
suffix, and what each needs, is one table: **`bleck/backends/languages.py`**.
Adding a language means adding a `Language` value there, not a branch in
`toolchain.py`.

`Toolchain.driver(language)` derives the compiler from whichever `gcc` was
located — same directory, same prefix, `gcc` → the language's driver name — so
two installed toolchains can never be mixed. A missing driver is resolved
*before* any unit compiles, and the error names the path it looked for.

### The exact C++ invocation

The shared machine flags, then `Language.extra_flags`:

```
powerpc-eabi-g++ -nostdlib -ffreestanding -ffunction-sections -fdata-sections \
  -mno-sdata -DGEKKO -mcpu=750 -meabi -mhard-float -O2 -Wall -mgcn \
  -fno-exceptions -fno-rtti -std=gnu++17 -I<headers> -c thing.cpp -o 02-thing.o
```

`gnu++17`, not `c++17`: spm-headers' `mod/evt_cmd.h` uses the GNU comma-paste
extension `##__VA_ARGS__`. The three extra flags are exactly what that
repository's own `configure.py` compiles with. `-fno-exceptions -fno-rtti`
because a REL links `-nostdlib` — there is no unwinder and no type-info support
to call into.

The **link driver becomes g++** when any unit is C++ (`Language.link_priority`).
With `-nostdlib` this adds no libraries; it is the driver the toolchain expects
for C++ objects. A C-only mod still links with gcc and its `mod.rel` is
byte-identical to before C++ existed — checked against a worktree at the previous
commit for all nine C-only code mods in `mods/`.

### ⚠️ `mod_prolog` from C++ needs `extern "C"`

`bleck`'s weak `mod_prolog` has C linkage. A C++ definition without
`extern "C"` is mangled, does not override it, and the module loads and does
nothing. `bleck` refuses that at collection time rather than letting it link.

### ✅ C++ static constructors — walked by `_prolog`

A global object's constructor is not called by anything: the compiler emits a
pointer to a per-translation-unit initialiser into **`.ctors`** (devkitPPC uses
the old-style section, not `.init_array`) and expects a C runtime to walk it.
A REL has no such runtime. Left alone, global objects stay zero-initialised —
which looks fine until it does not.

What was measured, on devkitPPC 16.1.0 / binutils 2.46:

- `.ctors` **survives** the `-r --gc-sections` link. `libogc_common.ld` wraps it
  in `KEEP()`, and that script is applied even for `-r`.
- It **survives `elf2rel`**: `pyelf2rel`'s section filter takes `.ctors` by name
  under its ttyd behaviour and by `SHF_ALLOC` under its own.
- There is **no `__CTOR_LIST__`** in a partially-linked object, so bounds have to
  be supplied.

So `runtime_c.CTOR_BLOCK` emits two markers. The start is a plain `.ctors`
object in the generated `mod.c`, which is always first on the link line; the end
is in `.ctors.zzz_bleck_end`, and the script's
`KEEP(*(EXCLUDE_FILE(...) .ctors))` followed by `KEEP(*(SORT_BY_NAME(.ctors.*)))`
puts every contributor's table between them regardless of link order.

The bounds are laundered through empty `__asm__` before the loop. They are two
distinct objects to the compiler; only the linker makes them the ends of one
table, so a constant-folded `start + 1 >= end` could legally delete the loop.

**None of that is trusted.** `toolchain._check_ctor_walk` re-reads the linked ELF
and refuses the build unless there is exactly one `.ctors` output section and the
markers sit at its first and last words. A verified build: `.ctors` is 12 bytes —
start marker, one `R_PPC_ADDR32` to `_GLOBAL__sub_I_*`, end marker.

🔶 **The walk has not run in-game.** Every claim above is about the ELF and the
REL on disk. Whether the constructed objects behave once the loader links the
module is untested — `scripts/ingame.py` is the way to settle it.

Order across translation units is unspecified, as in any C++ program. Within one,
GCC emits a single initialiser calling them in declaration order, so that part is
not left to the linker.

### Not covered

- ⛔ No `.dtors` walk. `_epilog` is empty and a mod's REL is never unloaded.
- 🔶 nw4r's `.hpp` headers. Upstream's README says they are "probably unsafe to
  use with GCC", and its own CI never compiles them.
- No `operator new`/`delete`. The game's allocators are declared as raw mangled
  symbols (`__nw__FUl`, `__dl__FPv`) in `spm/memory.h`; nothing wires them to the
  C++ operators.

---

## Integration with the existing mod system

A code mod is still a mod: `mod.json` plus an overlay. Compiled output lands at
`overlay/files/mod/mod.rel`, which the existing overlay machinery already
handles — no new packaging path.

What is new is a **source** directory and a build step:

```
mods/my-code-mod/
  mod.json
  code/
    source/main.cpp
    include/
  overlay/                    ← mod.rel is generated into here
```

Manifest gains a `code` block:

```json
"code": {
  "script":  "scripts/main.evt",
  "sources": ["src/hooks.c"],
  "target": "eu0",
  "module_id": 2
}
```

`bleck mod build` compiles before staging, so code and assets ship together.

## Patching the game's own scripts

A code mod can also make a **vanilla** `evt` script call into `mod.rel`, without
that script ever having been decompiled. ✅ Measured with a control (D89) and
declarative since D90:

```json
"code": {
  "sources": ["src"],
  "patches": [
    { "script": "map:he1_01", "at": 0, "expect": "DEBUG_PUT_MSG", "call": "on_map_init" }
  ]
}
```

| Field | What |
|---|---|
| `script` | which script, as `<kind>:<name>` — see the selectors below |
| `at` | word offset into the script where the replaced instruction begins |
| `expect` | the opcode expected there. **Required**, and it is the guard |
| `call` | a function in this mod's own sources: `s32 f(EvtEntry *entry, bool firstCall)`, returning **2** so the script advances |

`expect` takes three forms:

- `"DEBUG_PUT_MSG"` — an opcode whose arity `bleck/script/evt.py` knows;
- `"USER_FUNC 4"` — an opcode name *and* its argument count, for a variadic
  opcode where the count is not inferable;
- `"0x00010072"` — the raw header word, for an opcode absent from the table.

### Selectors

| Selector | Resolves to | State |
|---|---|---|
| `map:he1_01` | `mapDataPtr("he1_01")->initScript` | ✅ measured end to end (D89, D90, D92) |
| `item:0x41` | the `itemEventDataTable` entry with that `itemId`, then its `useScript` | ✅ resolves, guard matches, bytes change (D92). 🔶 the hook has never been observed *entering* |
| `door:` | — | ⛔ deferred: `DoorDesc` has no lookup by name, and would need `evt_door_set_door_descs` intercepted (D91) |

⚠️ **Item ids share scripts.** 22 distinct scripts across the 33 table entries
(D91), so patching one id can change several — `item:0x41` was measured to hit a
script three entries point at. The generated code counts them into
`bleck_patch_shared[]`, so a mod can read the number rather than guess it.

`itemEventDataTable` is walked directly rather than calling `getItemUseEvt`,
which `item_event_data.h` says returns *"a fallback if the item isn't in
there"* — an unknown id would otherwise silently patch a shared fallback. An id
the table does not hold gets its own status, `5`, not a refusal.

### Same size, any size

An instruction is a header declaring **M** argument words, then those M words.
The replacement is a `USER_FUNC` header declaring the *same* M, then the pointer
to `call`, then the original's words 2..M carried through untouched. M is read
out of the header the guard just matched, so the replacement cannot be a
different length — which is what keeps every label where it was.

    M = 1   DEBUG_PUT_MSG msg          ->  USER_FUNC f
            00010072 80CB3798              0001005C 80F66038
            (the original's one argument is lost)

    M = 4   USER_FUNC g, a, b, c       ->  USER_FUNC f, a, b, c
            0004005C 80025250 ...          0004005C 80F66084 ...
            (a, b and c are not touched: for a USER_FUNC target this reads as
             "redirect the call, keep its arguments")

The hook reads those carried-through arguments from its `EvtEntry` the way any
of the game's own user funcs does: `pCurData` (`spm/evtmgr.h` +0x14) points at
the first argument and `curDataLength` (+0x09) counts them. ✅ Measured at M = 1
(D92): `pCurData` sat one word past the function pointer with `curDataLength` 0,
so the pointer is consumed and what remains is the user arguments. 🔶 That
`pCurData[0..M-2]` are the arguments for M > 1 is the only reading consistent
with both numbers, but M = 1 has no arguments to observe, so it is untested.

### The guard, at build time and at run time

**Build time.** The only size `bleck` refuses is a **one-word** instruction
(argc 0): the replacement needs a second word for the function pointer, and
there is nowhere to put it. It also refuses an unknown opcode name (with a
suggestion), a variadic opcode with no count, a count that contradicts the arity
table, and a `call` that no collected source defines.

**Run time.** The generated code reads the word at `at` and writes nothing
unless it matches. This is what turns a wrong offset from an undiagnosable
freeze into a clean no-op — D51 spent a long time being exactly that freeze.
Note the guard compares the *whole* header, argument count included.

### Reading the outcome

A small table is generated beside the patches, so "did my patch take" is
answerable without a debugger:

```c
extern unsigned int bleck_patch_status[];   /* one per patch, in manifest order */
extern unsigned int bleck_patch_shared[];   /* how many things point at that script */
extern const unsigned int bleck_patch_count;

/* status: 1 pending, 2 applied, 3 refused by the guard,
           4 the script pointer was null, 5 no such item id in the table */
/* shared: 0xFFFFFFFF where nothing counted (every `map:` patch) */
```

Patches are applied from `_prolog`, **before** `mod_prolog`, so a mod's own C
reads a final value.

### What this does not do

- ⛔ **No insertion or deletion.** Same-size replacement only: anything else
  moves labels, and `jumptable[]` is cached per `EvtEntry` when a script starts
  (D87).
- ⛔ **No pointer swapping.** Repointing `MapData.initScript` deadlocked the map
  loader (D51). This mutates the bytecode the pointer already refers to, which
  creates no new `EvtEntry`.
- ⛔ **No dispatcher or opcode changes**, as `evtpatch` does.
- ⛔ **No `door:`**, and no `npcdrv.h` scripts. Deferred with a reason, not
  merely unimplemented — see the selector table.
- ⚠️ **A patch lasts the whole session**, including maps entered later. It is
  applied once, at load, and not re-applied per arrival.
- 🔶 **A patched item hook has never been seen running.** An item use script
  only runs when the player uses that item, which needs menu navigation, and
  controller input cannot be injected (D48). Settling it needs a save state plus
  `scripts/keys.py`, which is Windows-only and attended.
- No cache flush is needed. This is bytecode read as *data*, unlike patching
  PowerPC instructions, which needs `dcbst`/`sync`/`icbi` — see below.

## Patching the game's own code

Evt patching reaches scripts. Reaching a **C function** needs an instruction
written at a live address, which every module now carries helpers for. ✅
Measured with a control that failed in the expected direction (D94).

```c
/* Generated by bleck. Declare what you use; --gc-sections drops the rest. */
extern void bleck_code_store(void *at, u32 word);   /* store, NO flush */
extern void bleck_code_flush(void *at);             /* dcbst/sync/icbi/isync */
extern void bleck_code_write(void *at, u32 word);   /* store then flush */
extern s32 bleck_code_branch(const void *from, const void *to, u32 *out);
extern s32 bleck_code_hook(void *at, const void *to); /* encode, write, flush */

extern void evt_door_set_door_descs(void);   /* bound by elf2rel, by name */

if (bleck_code_hook((void *) evt_door_set_door_descs, (void *) myHandler) != 0)
    ; /* refused: 1 misaligned, 2 out of range. Nothing was written. */
```

### ⚠️ Why the flush is not optional

A store lands in the **data** cache. The instruction fetcher reads through the
**instruction** cache and cannot see it, so the patched word is visible to a
debugger — and to any load — while the CPU keeps running the old code.

That is not a theoretical hazard. Two identical patches were applied in one run,
differing only in the flush (D94):

| | store only | store + flush |
|---|---|---|
| word read back at the patched address | `48000008` | `48000008` |
| what the function actually returned | **the old value** | **the new one** |

Use `bleck_code_write` or `bleck_code_hook`. `bleck_code_store` exists so that
experiment can be repeated, not so mods can call it.

### The branch encoding, and its refusal

`0x48000000 | ((to - from) & 0x03FFFFFC)` — I-form, opcode 18, a 24-bit word
displacement. The field is 26 bits signed, so roughly ±32 MB.

An out-of-range displacement is **refused**, not masked. Masking would emit a
perfectly valid branch to somewhere else entirely, and `bleck_code_hook` writes
nothing at all when the encode fails. ✅ Exercised in-game, not merely written
(D94): a hook aimed 256 MB away returned `2` and left the target word untouched.

A REL loads around `0x80F6xxxx` and the DOL's text starts at `0x800xxxxx`, so
in practice a hook from a mod into game code is ~15 MB and comfortably in range
— but check the status, because nothing guarantees where the loader puts the
module.

### `code.hooks` — the declarative form

The helpers above are the mechanism; `code.hooks` is how a mod asks for one
without writing an install sequence. ✅ Measured through the declarative path
(D95).

```json
"code": {
  "sources": ["src"],
  "hooks": [
    { "function": "npcDispMain", "call": "count_npcs", "mode": "replace" }
  ]
}
```

- **`function`** — a symbol name resolved against the target's list **at build
  time**, or a raw address (`"0x801adef0"`). Resolving by name is the point: no
  addresses in a manifest, and a rename or the wrong `target` fails the build
  rather than branching into unrelated code. The generated C emits
  `extern void npcDispMain(void);` and `&npcDispMain`, so `elf2rel` still binds
  the address and the symbol list stays the single source of truth.
- **`call`** — a function in the mod's own sources. Checked against what those
  sources define, reusing the same scan `code.patches` uses, so a typo is caught
  before `elf2rel` reports it as a missing *game* symbol.
- **`mode`** — `"replace"`, `"before"` or `"after"`. ✅ All three work (D97).
  `before` runs the mod's function and then the original; `after` runs the
  original and then the mod's function. **Both return the original's value**, so
  a handler cannot change what the caller receives.
  ⛔ The paragraph that used to sit here said `before` and `after` were refused
  at build time for want of a trampoline (D95). That refusal is gone; there is
  still no trampoline — see below.

### ⚠️ `replace` means the original never runs

There is no trampoline. The function's first instruction becomes a branch and
its body is gone for the rest of the session, so **the mod's function is the
whole implementation** — same arguments, same return value, same job. A hook on
`npcDispMain` stops NPCs being drawn; a hook on anything a sequence waits for
stops the sequence.

Reaching for `before` because you want the original to keep working is exactly
the case that must not silently get `replace`, which is why `replace` is written
out rather than defaulted to. Say `before` or `after` and you get interception.

### ✅ `before` and `after` — interception, still without a trampoline

D97. The generated module carries a **PowerPC assembly wrapper per intercepting
hook**, emitted by `bleck/script/emit/runtime_intercept.py`. The branch points at
the wrapper; the wrapper calls the mod's function and the original in the
declared order, and returns the **original's** `r3`.

Reaching the original is D96's *self-healing detour*, unchanged: restore the
first instruction, call, re-install the branch. ⛔ **This is not a trampoline and
one is still not built** — the detour pays two cache flushes per call where a
trampoline would pay none. `replace` codegen is untouched, and every
pre-existing code mod builds byte-identical.

**Why assembly rather than a generated C wrapper.** A hook is resolved from a
symbol *name*, and nothing in the symbol list carries a signature, so a C
wrapper would have to guess one. ⛔ Guessing `(u32, u32, u32, u32)` was ruled out
and is not a near miss: the PowerPC EABI passes floats in `f1-f8`, entirely
separately from `r3-r10`, and C code that never mentions a float may clobber
them freely — so the original would be called with corrupted arguments,
silently, and only for functions that happen to take floats. The assembly
wrapper saves `r3-r10` and `f1-f8`, calls what it needs to, and puts them back.
Nothing in it interprets an argument.

The original is called through `CTR`, not `bl`: a 26-bit relative branch from
the module to the DOL can be out of range.

**Interception needs a derived guard**, because the detour restores that word to
reach the original. So a hook whose address the DOL does not map — a REL address
— is a build **error** under `before`/`after`, where `replace` merely warns and
installs unguarded (see below). Left alone it would build cleanly and recurse
into itself until the stack ran out.

What is still not true:

- ⛔ **More than eight integer arguments cannot be intercepted.** They live in
  the caller's frame and the wrapper builds its own. **Not checked, and cannot
  be** without signatures.
- ⚠️ **The handler's prototype must still match the target.** The wrapper
  protects the *original* from a wrong handler prototype — every register is
  restored from the frame before the original is called — but the handler itself
  reads whatever it declared.
- 🔶 **Dolphin only.** As with every cache-flush result here (D94, D96), this is
  Dolphin's cache model and not a real 750's.

✅ **Measured once, 120 s, `mods/intercept-probe`.** The probe was built to tell
the two modes *apart*, not merely to show a hook installing: the wrapper calls
`bleck_trace_result` when the original returns, so at handler time `lastResult`
holds the previous call's value under `before` and this call's under `after`.

| Word | Value | |
|---|---|---|
| `beforeSaw` | **0** | the original had not run |
| `afterSaw` | **0x901D6248** | the original had returned |
| `afterSaw − arg` | **0xD8** | reproduces D96's `GetBasicPlayer` result |
| `blind`, `depth` | 0, 0 | |
| SEQ_GAME frames | 26,996 | two full `aa4_01` → `ls4_12` cycles |

`beforeSaw = 0` is not vacuous: `traces[0].lastResult` reads `0x80402DE4` at
rest, so the field is written and its being zero means the original genuinely
had not run — the control D70/D73/D74 went without.

### The guard is derived, not declared

`code.patches` makes you write `expect`. A hook cannot: nobody knows the
instruction word at a function's entry off-hand. So `bleck` reads it out of the
base disc's `main.dol` at build time — mapping the address through the DOL's
section table (`bleck/backends/dol.py`) — and generates that word into the
runtime guard.

```c
static const BleckFunctionHook bleck_function_hooks[BLECK_HOOK_COUNT] = {
    {(void *) &npcDispMain, 0x9421FE40u, 1u, (const void *) &count_npcs},
};
```

At run time the word at the address must equal `0x9421FE40` — `npcDispMain`'s
`stwu r1,-0x1C0(r1)` prologue — or nothing is written. A wrong address or the
wrong game version therefore costs a status, not a corrupt branch.

**A guard is never invented.** An address the DOL does not map — a REL address,
say — gets `guarded = 0`, installs unguarded, and the build warns saying exactly
why. ⚠️ Under `before` or `after` that same case is a build **error** instead,
because interception restores the guard word to reach the original and there is
nothing to restore (D97). An address that resolves into the DOL's *data* rather than its text is
guarded but warned about too: eu0's data reaches `0x805B7720`, so a wrong
address can easily look like code.

### Reading the outcome

```c
extern unsigned int bleck_hook_status[];   /* one per declared hook */
extern const unsigned int bleck_hook_count;
```

| Value | Meaning |
|---|---|
| 1 | pending — `bleck_install_hooks` has not run |
| 2 | installed |
| 3 | refused: the word there is not what the build read |
| 4 | misaligned |
| 5 | out of range — the branch cannot be encoded |

Hooks install from `_prolog`, **before** `mod_prolog`, so a mod's own C reads a
final answer.

### Tracing a function instead of replacing it

✅ Measured, D96. A `replace` hook takes the function over, so a handler can
record the arguments and never the return value — and disables the function it
is studying. (`before`/`after` do not have that problem; they are this same
detour, generated. What follows is the hand-written form, which is what you want
when the *instrument* is the point.) The **self-healing detour** gets both back
without a trampoline:

1. record the arguments;
2. **restore** the original first instruction (write + flush);
3. call the function through its own symbol — now unpatched, so control reaches
   the real body instead of coming straight back;
4. **re-install** the branch (write + flush);
5. record the return value and return it.

The word put back in step 2 is the guard `bleck` derived from `main.dol` at
build time. Nothing is re-derived at run time, and **a hook with no derived
guard cannot be traced**: `bleck_trace_open` returns 0 rather than inventing a
word, and the original must then not be called at all.

There is **no manifest surface** for this — deliberately. It is an instrument
for answering a question, not an edit a user declares. What exists is five
helpers emitted beside the hook table and dropped by `--gc-sections` unless a
mod calls them:

```c
extern void bleck_trace_args(u32 index, u32 a0, u32 a1, u32 a2, u32 a3);
extern u32  bleck_trace_open(u32 index);      /* 0 = do NOT call the original */
extern void bleck_trace_close(u32 index);
extern void bleck_trace_result(u32 index, u32 value);
extern u32  bleck_hook_original(u32 index);   /* the derived guard word */
extern BleckTrace bleck_traces[];             /* calls, nested, blind, depth,
                                                 first[4], last[4], results */
```

```c
void *traceMapDataPtr(const char *mapName)
{
    void *result = 0;

    bleck_trace_args(0, (u32) mapName, 0, 0, 0);
    if (bleck_trace_open(0))
    {
        result = mapDataPtr(mapName);   /* unpatched right now */
        bleck_trace_close(0);
    }
    bleck_trace_result(0, (u32) result);
    return result;
}
```

`mods/fn-trace-probe` is the worked example, `mods/fn-trace-guard` the negative,
`mods/fn-trace-somewhere` a three-target investigation. What they found is in
[`function-behaviour.md`](function-behaviour.md).

#### ⚠️ What a trace cannot see

- **Float arguments.** The EABI passes the first eight integer or pointer
  arguments in r3–r10 and floats separately in f1–f8. `bleck_trace_args` takes
  words, so a float is never recorded — and the handler's prototype must *still*
  match the traced function exactly, because the handler forwards. A mismatched
  prototype corrupts the call rather than merely mis-recording it.
- **Float and struct returns.** Only r3 is recorded.
- **Arguments past the eighth**, which are on the caller's stack; the handler
  builds its own frame before forwarding.
- ⛔ **Variadic functions.** CR bit 6 carries "were float arguments passed", and
  a non-variadic handler clears it.
- ⚠️ **Registers are not arguments.** A handler declared with eight `u32`s
  records eight words whatever the function's arity is. `effMain` takes none and
  all four of its recorded arguments read the same residue value.
- ⚠️ **A captured pointer is dereferenced later, not at the call.** Copy the
  bytes at call time if a specific call's string matters.

#### Reentrancy

`bleck_trace_open` **restores before it counts**, so the only window in which a
second entry can reach the handler is between the branch being live and the
restore landing — where writing the same word again is harmless. `close` re-arms
the branch only at depth 0, so an inner frame cannot re-arm it under an outer
one. Skipping the trace when already inside was rejected: it would still have to
return something, and the handler cannot produce the original's return value
without calling it.

While the detour is open the function is **not** hooked, so a recursive call
runs the original directly and is not counted.

⚠️ `depth` should be 0 at rest. A non-zero one means a frame never returned, the
branch was never re-installed, and the counts stopped climbing silently.

#### 🔶 Cost

7–10 time-base ticks per call for the two flushes — about 1.1% on top of
`effMain`, and **infinite** relative overhead on a leaf: `GetBasicPlayer` is one
`addi` and a `blr`, and its own body measured 0 ticks. The detour's cost is
fixed; the traced function's is not.

These are Dolphin's cycle accounting, not hardware. Two `sync` instructions
costing ~9 ticks is not credible on a real 750, which has to drain the pipeline.

### What this does not do yet

- ⛔ **No trampoline.** Still literally true, and the reason to want one is
  unchanged: the detour pays two cache flushes per call where a trampoline pays
  none (D97). ⚠️ **What is no longer true is "replacement is all this is"** — the
  branch replaces, but the original is reached by restoring the instruction
  around the call, whether the mod writes that itself (the trace above) or
  declares `mode: "before"`/`"after"` and gets it generated. Upstream's
  `hookFunction` is not a drop-in for a trampoline either — it blindly copies
  instruction[0], so it breaks on any function starting with a PC-relative
  instruction (D37). Nothing here relocates an instruction, which is why a
  function beginning with a branch traces normally.
- ⛔ **More than eight integer arguments cannot be intercepted** (D97) — they sit
  in the caller's frame. Not checked, and not checkable without signatures.
- ⛔ **No build-time range check.** The loader chooses where the module lands, so
  "can this branch be encoded" is only answerable at run time. The encoder
  refuses rather than masking, and the status says which way it failed.
- ⛔ **`evt_door_set_door_descs` is not the way in to doors.** It was hooked
  successfully and entered **zero** times while Flipside loaded and ran for 90 s,
  with a control hook on `npcDispMain` firing 62,480 times in the same window
  (D94). Two maps, so 🔶 rather than settled — but `door:` stays refused.
- ⛔ **Do not stub `effMain`.** It hangs the map-change sequence (D94).
- 🔶 **Hardware.** Dolphin reproduced the stale instruction fetch, which is the
  interesting direction, but its cache emulation is not the Wii's.

## ✅ The single-slot problem — answered by merging (D78)

**The Gecko loader loads exactly one file: `/mod/mod.rel`.** That limit is real
and unchanged. Our mod system supports chains, so two mods in one chain both
wanting code would collide — and unlike an asset conflict, the second one simply
would not exist.

Three ways out were on the table:

1. **Treat `files/mod/mod.rel` as implicitly exclusive.** Simple, honest, and
   restrictive: one code mod per build.
2. **Use [`chainrel`](https://github.com/SeekyCt/chainrel)**, which chain-loads
   `./mod/chain.rel`. ⛔ **Ruled out** (D39): it is a three-commit stub with its
   loader body wrapped in `#if 0`. Nobody in this scene has solved runtime
   chaining.
3. **Link all code mods into one REL** at build time.

✅ **(3) is what shipped**, and it is verified in game: two mods each declaring
`script main` both ran to completion, each writing its own `gw[]` slot (D78).
Because merging happens at *compile* time, the loader still sees one module and
`chainrel`'s unsolved runtime chaining is not on this path at all. Identifiers
are namespaced per mod (`bleck_<slug>_`); a handful are per-*disc* and must not
be — `_prolog`, `mod_prolog` and the sequence-hook machinery.

🔶 **One gap remains**: two mods that both ship `code.sources` would collide on
`mod_prolog` at link time. Scripts merge cleanly; C does not yet. See
[`plan-merging.md`](./plan-merging.md).

---

## Delivering the Gecko code

Riivolution and ISO rebuilds only put the *file* on the disc. **The Gecko code is
what actually executes it** — without it, `mod.rel` sits there inert.

✅ **Solved by putting the code in the DOL.** `wstrt patch --add-sect` writes the
handler and the loader codes into a new TEXT section of `main.dol` and redirects
the game into it (`bleck/backends/gecko.py`). No `R8PP01.ini`, no cheat manager,
no `.gct` for the user to install — on emulator or on console.

That is why a **Riivolution patch is self-sufficient** (D86): Riivolution
replaces `main.dol` like any other file, so the loader travels with the patch.
See [`hardware.md`](./hardware.md) for the XML, the two ways to get it silently
wrong, and why the REL stays named `mod.rel`.

```
bleck mod build my-mod --output riivolution
```

---

## ⚠️ Licensing — this one matters

**`spm-rel-loader` is GPLv3**, including the Gecko loader code. `spm-headers` is
MIT *except* its `mod/` folder, which is GPLv3 "as it's derived from other GPL
code."

`bleck` is currently unlicensed. Vendoring the loader code or the `mod/` headers
would make derived work GPLv3. Options:

- **Don't vendor.** Fetch or require the user to supply `spm-rel-loader`,
  keeping `bleck` license-clean. Adds a setup step.
- **Vendor and adopt GPLv3** for the code-mod portion, or the whole toolkit.
- **Vendor only the MIT parts** (`spm-headers` `include`/`linker`) and fetch the
  GPL loader separately.

Needs a decision before any upstream code is copied into this repo.

---

## Order of work — all of it done

1. ~~**Prove the toolchain.**~~ ✅ D26. The ABI gamble did not fail.
2. ~~**Get one hook running.**~~ ✅ D38, after three wrong entry points — see
   [`hook-points.md`](./hook-points.md).
3. ~~**Wire into `bleck mod build`.**~~ ✅ D46, D47. C++ followed in D85.
4. ~~**Emit the Dolphin INI.**~~ ⛔ Superseded by D44: the loader is baked into
   `main.dol` instead, so a built disc needs no emulator configuration at all.
5. ~~**Consider `chainrel`.**~~ ⛔ Superseded by D78: mods merge at compile time.

What is left is in [`roadmap.md`](./roadmap.md).

⛔ **This line used to read "the largest item is a trampoline so
`mode: \"before\"`/`\"after\"` can exist".** D97 shipped both modes without one
and explicitly retracts that ranking; a trampoline is now an optimisation worth
two cache flushes per call, ranked accordingly in `roadmap.md`.
