# Code Mods — Design

**Status: toolchain proven (D26); the *scripting* path is now built (D37).**

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

**`g++-powerpc-linux-gnu` is a separate package** and is not installed. Upstream
uses C++17, so it will be needed for anything beyond C.

**Fallback if the ABI gamble fails:** build RELs on Windows with real devkitPPC
and package with `bleck` here. The split is clean — the REL is just a file the
overlay places.

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
  "sources": ["code/source"],
  "target": "eu0",
  "rel_id": 2
}
```

`bleck mod build` compiles before staging, so code and assets ship together.

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

For Dolphin this is automatable: codes live in
`User/GameSettings/R8PP01.ini` under `[Gecko]`. `bleck` can emit that INI beside
the built image, so testing is turnkey:

```
work/build/my-mod.wbfs
work/build/my-mod.R8PP01.ini      ← drop into Dolphin's GameSettings
```

For real hardware, the same code goes into a `.gct` via Riivolution or a code
manager — out of scope initially, but the data is identical.

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
