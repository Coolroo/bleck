---
title: Code mods
description: Compile custom PowerPC code into a module the game loads at boot
---

!!! note

    **Looking to add behaviour to the game? Start with
    [Scripting](../guides/scripting.md).** It is integrated into `bleck mod build`,
    needs far less setup, and covers event logic — cutscenes, NPCs, items, doors,
    map triggers.

    This page is about **native hooks**: changing how an existing game function
    behaves. Scripting cannot do that, and the two work together in one mod.

Add a `sources` entry to the mod's `code` block:

```json title="mod.json"
{
  "code": {
    "script":  "scripts/main.evt",
    "sources": ["src/hooks.c"],
    "target": "eu0"
  }
}
```

Either half is optional; at least one is required. `bleck mod build` compiles
them into a single `mod.rel`.

## What a code mod is

Not a patched executable. Your code becomes a **separate module** loaded
alongside the game, hooking existing functions by address:

```
freestanding PowerPC C/C++
  → compile (no libc)
  → link relocatably against a per-version symbol list
  → ELF → REL
  → placed on the disc as /mod/mod.rel
  → a Gecko code loads and runs it at boot
```

The game itself is never modified. Your code links against **symbol addresses**,
not against decompiled source, so the community decompilation is a
documentation source rather than a dependency.

## Several code mods on one disc

You can install more than one. `bleck` compiles them **together** into the one
`mod.rel` the disc carries — so a chain like `hard-mode -> extra-enemies` works
the same as a single mod, and both mods' scripts run. The merging happens at
compile time; the disc still carries exactly one REL, which is all the loader
opens.

Two mods may both declare `script main`; each gets its own namespace in the
generated module, and every mod's `main` is started.

Three things are decided per **disc** rather than per mod, and `bleck` refuses
rather than picking for you:

| If two mods… | You get |
|---|---|
| both set `code.boot` | an error naming both — a disc starts in one place |
| set different `code.target` | an error — addresses differ per game version, and a mixed build would call the wrong ones without complaining |
| have names that reduce to the same identifier, like `hard-mode` and `hard mode` | an error naming both mods |

!!! note "One `mod_prolog` per disc"

    `bleck` calls `mod_prolog` when the module loads, so a merged disc has
    exactly one. If two mods define it you get an error naming both, rather
    than a linker message about a symbol you did not write.

    Move the extra work into a sequence hook, or combine the two mods.

## Writing a hook

`bleck` owns `_prolog` — it has to install its sequence hooks first. Your code
defines `mod_prolog` instead, and `bleck` calls it:

```c title="src/hooks.c"
extern MapData *mapDataPtr(const char *name);

void mod_prolog(void)
{
    MapData *flipside = mapDataPtr("mac_01");
    /* ... */
}
```

!!! warning

    `mod_prolog` runs at **load time**, when the game is barely up. Patching
    pointers and reading tables is fine; anything touching live engine state is
    not — that belongs in a sequence hook.

Function names are resolved by `elf2rel` against the symbol list, exactly like
a script's builtin calls, so no addresses appear in your source.

## Making the game's own scripts call your code

Super Paper Mario runs its own event scripts for things like map setup, and a
mod can take one of their instructions over. Declare it and `bleck` writes the
code:

```json title="mod.json"
"code": {
  "sources": ["src"],
  "patches": [
    {
      "script": "map:he1_01",
      "at": 0,
      "expect": "DEBUG_PUT_MSG",
      "call": "on_map_init"
    }
  ]
}
```

```c title="src/hooks.c"
/* evt's user-func signature. Return 2 so the script carries on. */
int on_map_init(void *entry, int firstCall)
{
    /* ... */
    return 2;
}
```

`expect` is the instruction you believe is at that offset, and it is a guard:
nothing is written unless the word actually there matches. So a wrong offset
costs you a status rather than a corrupted script.

The replacement is a `USER_FUNC` calling your function, and it declares the
**same number of arguments** as the instruction it overwrites — so it is always
exactly the same size, and patches never insert or delete. Your function pointer
takes the first argument slot; the original's remaining arguments stay where
they are and reach your code through the `EvtEntry`. The one thing `bleck`
refuses is a single-word instruction, where the pointer would not fit.

### Which scripts you can reach

```json
{ "script": "map:he1_01", "at": 0, "expect": "DEBUG_PUT_MSG", "call": "on_map_init" }
{ "script": "item:0x41",  "at": 0, "expect": "USER_FUNC 4",   "call": "on_item_use" }
```

`map:<name>` is a map's init script; `item:<id>` is an item's use script.
`door:` is not supported — the game gives no way to look a door's scripts up by
name.

!!! warning "Items share scripts"

    The game's item table has 33 entries but only 22 distinct scripts, so
    patching one item id can change other items too. `bleck_patch_shared[]`
    tells you how many entries point at the script you hit.

Your code can read what happened:

```c
extern unsigned int bleck_patch_status[];
/* 1 pending, 2 applied, 3 refused by the guard, 4 no script, 5 no such item id */

extern unsigned int bleck_patch_shared[];
/* how many things point at that script; 0xFFFFFFFF where nothing counted */
```

Full field reference: [`code.patches`](../reference/manifest.md).

## Replacing one of the game's own functions

`code.patches` reaches the game's *scripts*. `code.hooks` reaches its **C
functions**: name one, name yours, and the module points the game at yours when
it loads.

```json
"code": {
  "sources": ["src"],
  "hooks": [
    { "function": "npcDispMain", "call": "count_npcs", "mode": "replace" }
  ]
}
```

```c
/* Your function takes over completely, so it matches what it replaces. */
void count_npcs(void) { ... }
```

- `function` — a game symbol by name, resolved against your `target`'s symbol
  list while the mod builds. A name that is not there fails the build, with a
  suggestion. A raw address (`"0x801adef0"`) works too, for something unnamed.
- `call` — a function in your own `code.sources`.
- `mode` — `"replace"`. That is the only one that exists.

!!! danger "`replace` means the original never runs"

    The function's first instruction becomes a branch into your code, and its
    body is gone for the rest of the session. **Your function is now the whole
    implementation** — same arguments, same return value, same responsibilities.
    Hooking `npcDispMain` stops NPCs being drawn; hooking something a sequence
    waits on stops the game.

    `"before"` and `"after"` are **refused** at build time rather than quietly
    treated as `"replace"`. If you want the original to keep running, that is
    the thing `bleck` cannot do yet, and it will say so.

You do not write a guard. `bleck` reads the instruction word actually at that
address out of the base disc's `main.dol` while building, and the hook refuses
to install unless the running game has the same word — so a wrong address, or a
mod built against a different game version, is a clean refusal rather than a
branch into the middle of something else. If the address is not in the DOL at
all, the build **warns** that the hook is going in unguarded rather than
inventing a guard.

Your C can read what happened:

```c
extern unsigned int bleck_hook_status[];
/* 1 pending, 2 installed, 3 refused by the guard,
   4 misaligned, 5 out of range */

extern const unsigned int bleck_hook_count;
```

Hooks install before your `mod_prolog`, so that read is final.

Full field reference: [`code.hooks`](../reference/manifest.md).

## Watching a function instead of taking it over

Sometimes the question is "what is this function handed, and what does it hand
back" — and replacing it destroys the answer. There is no manifest key for this;
it is a pattern you write over a `code.hooks` entry, using helpers `bleck`
generates beside the hook table.

Your handler restores the original instruction, calls the function normally
while it is unpatched, and puts the branch back:

```c
extern void bleck_trace_args(unsigned index, unsigned a0, unsigned a1,
                             unsigned a2, unsigned a3);
extern unsigned bleck_trace_open(unsigned index);   /* 0 = do NOT call it */
extern void bleck_trace_close(unsigned index);
extern void bleck_trace_result(unsigned index, unsigned value);

extern void *mapDataPtr(const char *mapName);

void *traceMapDataPtr(const char *mapName)
{
    void *result = 0;

    bleck_trace_args(0, (unsigned) mapName, 0, 0, 0);
    if (bleck_trace_open(0))
    {
        result = mapDataPtr(mapName);   /* unpatched right now */
        bleck_trace_close(0);
    }
    bleck_trace_result(0, (unsigned) result);
    return result;
}
```

`bleck_traces[]` then holds, per hook: the call count, the first call's
arguments, the most recent call's arguments, both return values, and counters
for anything that went wrong. Read them from a per-frame hook into a probe block
and `scripts/ingame.py --words` prints them.

`bleck_trace_open` returns 0 when there is nothing to restore — an unguarded
hook, or one the guard refused. **Do not call the original then**: its first
instruction is still the branch back into your handler.

!!! danger "Your handler's prototype must match the function exactly"

    The handler *forwards* its arguments to the original, so a wrong prototype
    corrupts the call rather than merely mis-recording it.

    Only integer and pointer arguments are recorded, and only the first four.
    **Floating-point arguments are invisible** — the ABI passes them in separate
    registers — and so is a floating-point return value. So is anything past the
    eighth integer argument. Do not trace a variadic function.

    A handler declared with more parameters than the function actually takes
    records leftover register contents for the extras. They are not arguments.

!!! warning "It costs two cache flushes per call"

    Fine on a function called a few times per map load; measurable on one called
    every frame; and on a one-instruction leaf the overhead is larger than the
    function. Measure rather than assume.

`mods/fn-trace-probe` in the repository is the worked example.

## Writing the branch yourself

`code.hooks` covers the declarative case. The same helpers are available
directly, for a hook you want to install conditionally or somewhere the
manifest cannot name:

```c
extern int  bleck_code_hook(void *at, const void *to);   /* encode, write, flush */
extern void bleck_code_write(void *at, unsigned int word);
extern int  bleck_code_branch(const void *from, const void *to, unsigned int *out);

extern void someGameFunction(void);   /* resolved from the symbol list, by name */

void mod_prolog(void)
{
    if (bleck_code_hook((void *) someGameFunction, (void *) myHandler) != 0)
        return;   /* 1 misaligned, 2 out of range. Nothing was written. */
}
```

The branch is a plain `b`, so its reach is about ±32 MB. Out of range is
**refused**, never truncated — a masked displacement would be a valid branch to
the wrong place.

Written this way there is **no guard** — nothing checks what was at the address
before overwriting it. `code.hooks` derives one for you, which is the reason to
prefer it.

!!! warning "Never store an instruction without flushing"

    `bleck_code_write` and `bleck_code_hook` issue `dcbst`/`sync`/`icbi`/`isync`.
    Without that the word is in memory — a debugger will show your patch — but
    the CPU keeps fetching the old instruction and nothing changes. This was
    measured, not assumed: the unflushed half of the experiment did nothing at
    all while reading back as correctly patched.

    `bleck_code_store` deliberately omits the flush so that experiment can be
    repeated. Do not use it in a mod.

## C++

`code.sources` takes `.cpp`, `.cc` and `.cxx` as well as `.c`, and a mod may mix
both in one build. C++ units compile with the `g++` beside whichever `gcc`
`bleck` found — never a separately located one, so the two halves always come
from the same toolchain.

The environment is freestanding: **no libstdc++, no exceptions, no RTTI.** Units
build with `-fno-exceptions -fno-rtti -std=gnu++17`, matching what
[spm-headers](https://github.com/SeekyCt/spm-headers) itself uses.

```cpp title="src/thing.cpp"
#include <spm/seqdrv.h>

class Counter {
public:
    Counter() : value_(0) {}
    unsigned int bump() { return ++value_; }
private:
    unsigned int value_;
};

static Counter g_counter;

extern "C" void mod_prolog(void)
{
    g_counter.bump();
}
```

!!! warning "A C++ `mod_prolog` needs C linkage"

    Without it the name is mangled, `bleck`'s own definition wins, and your code
    never runs. `bleck` refuses the build rather than letting that happen.

!!! note "Global objects"

    Nothing in a REL walks the constructor table on its own, so `bleck` emits a
    walk into `_prolog` and checks after linking that it covers every entry.
    Constructor order *across* source files is unspecified, as in any C++
    program; within one file it follows declaration order.

    This has not been exercised in a running game. If a global object matters to
    your mod, confirm it is what you expect before relying on it.

!!! note

    `BLECK_HEADERS_DIR` supplies `-I` for your sources — point it at
    [spm-headers](https://github.com/SeekyCt/spm-headers)' `include`. Without
    it, declare what you use `extern` yourself.

## Prerequisites

| | |
|---|---|
| PowerPC cross-compiler | `gcc-powerpc-linux-gnu`, or devkitPPC. C++ also needs that toolchain's `g++` |
| `pyelf2rel` | ELF → REL conversion (pure Python, on PyPI) |
| [`spm-headers`](https://github.com/SeekyCt/spm-headers) | Symbol lists and struct definitions |
| [`spm-rel-loader`](https://github.com/SeekyCt/spm-rel-loader) | The Gecko loader code |

## The loader

Placing `mod.rel` on the disc is not enough. A **Gecko code** is what actually
executes it, and it ships pre-assembled per region in
`spm-rel-loader/loader/*.txt`.

For Dolphin, Gecko codes go in `User/GameSettings/R8PP01.ini`.

## Building a REL outside `bleck`

`bleck mod build` does all of this for you. Reach for the raw commands only when
you are building a REL in your own toolchain and want to package the result with
`bleck` afterwards.

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

Inspect the result with `bleck`:

```bash
uv run bleck info mod.rel
```

```
mod.rel  264 bytes
  REL v3 (13 sections)
```

!!! warning

    **`-fno-pic -fno-PIE` is mandatory** with a distro compiler. Debian's GCC
    defaults to PIE and devkitPPC does not; without these flags you get
    `R_PPC_REL16_HA` relocations and `pyelf2rel` fails with:

    ```
    UnsupportedRelocationError: Unsupported relocation type 252
    ```

    The error gives no hint about the cause, so it is worth knowing up front.

Only `-mgcn` from the upstream flag set is rejected — it is devkitPPC-specific
and safe to drop.

??? note "ABI differences between cross-compilers"

    devkitPPC targets `powerpc-eabi`; Debian's targets `powerpc-linux-gnu`
    (SysV). `-meabi` asks for EABI conventions, but differences around
    small-data registers and struct passing can produce code that builds
    cleanly and misbehaves at runtime.

    If you hit that, build with devkitPPC and package the resulting REL with
    `bleck` — it is just a file the overlay places.

??? note "Licensing"

    `spm-rel-loader` is **GPLv3**, including the loader code. `spm-headers` is
    MIT except its `mod/` folder. `bleck` is currently unlicensed, so nothing
    upstream has been vendored into it.
