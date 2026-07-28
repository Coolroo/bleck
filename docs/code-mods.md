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
  PowerPC instructions, which needs `dcbst`/`sync`/`icbi`.

### ⚠️ The single-slot problem — this needs a decision

**The Gecko loader loads exactly one file: `/mod/mod.rel`.** Our mod system
supports chains, so two mods in one chain both wanting code would collide — and
unlike an asset conflict, the second one simply would not exist.

Three ways out:

1. **Treat `files/mod/mod.rel` as implicitly exclusive.** Simple, honest, and
   restrictive: one code mod per build. Detected by existing machinery.
2. **Use [`chainrel`](https://github.com/SeekyCt/chainrel)** (same author, active
   2026-02), which chain-loads `./mod/chain.rel`. Proper multi-module support,
   more moving parts.
3. **Link all code mods into one REL** at build time. Best result, hardest —
   symbol collisions and initialisation order become our problem.

**Recommendation: start with (1)**, and treat `chainrel` as the follow-up once a
single code mod demonstrably works. Shipping a broken multi-mod story is worse
than declining to support it.

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

## Proposed order of work

1. ~~**Prove the toolchain.**~~ ✅ **Done** — see above and D26.
2. **Get one hook running.** Simplest observable effect, verified by booting.
3. **Wire into `bleck mod build`** — compile step, `mod.rel` into the overlay.
4. **Emit the Dolphin INI** so testing needs no manual steps.
5. **Then** consider `chainrel` for multiple code mods.

Step 1 is the gate. If the Debian compiler produces bad code, everything shifts
to building on Windows and the design here is unaffected — only where it runs.
