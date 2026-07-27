---
title: Scripting
description: Write mod behaviour in a small language that compiles to the game's own script VM
---

Super Paper Mario ships its own scripting VM — the game calls it `evt`, and it
runs cutscenes, NPC behaviour, doors, item pickups and map logic. `bleck`
compiles a small friendly language down to that VM's bytecode.

That means your script runs on an interpreter Nintendo shipped and tested,
scheduled cooperatively alongside the game's own scripts. There is no runtime to
install and nothing extra loaded into memory.

!!! note

    **Scripting handles event logic, not engine internals.** It is excellent at
    "wait, move, speak, branch on a flag, spawn a child script". Changing how an
    existing function *behaves* still needs a native hook — see
    [Code mods](../guides/code-mods.md).

## Your first script

Create a mod and give it a script:

```bash
bleck mod new speedrun
```

```text title="scripts/main.evt"
-- Doubles the game speed a moment after boot.

script main {
    wait(120)

    var speed = 2.0
    evt_sub_set_game_speed(speed)
}
```

Point `mod.json` at it:

```json title="mod.json"
{
  "schema": 1,
  "name": "speedrun",
  "base": "eu0",
  "code": {
    "script": "scripts/main.evt",
    "target": "eu0"
  }
}
```

Check it compiles. This needs no compiler and no symbol list:

```bash
bleck script check mods/speedrun/scripts/main.evt
```

```
main.evt: 1 script(s) [main], 8 bytecode words, 1 game function(s) called
  calls evt_sub_set_game_speed
```

Then build the disc as usual — the script is compiled and packaged
automatically:

```bash
bleck mod build speedrun --launch
```

```
speedrun: compiled main.evt [main] -> 436 byte module (devkitPPC)
chain OK: speedrun
```

## The language

### Scripts

`main` is the script that runs. Others are started with `spawn`.

```text
script main {
    spawn greeter
}

script greeter {
    evt_msg_print(0, "hello", 0, 0)
}
```

### Waiting

`wait` yields the frame rather than blocking it — the game keeps running while
your script is paused. This is the whole reason scripts are pleasant to write
for a 60fps game.

```text
wait(60)        -- 60 frames
wait_ms(500)    -- 500 milliseconds
```

### Variables

Types come from the initialiser and do not mix.

```text
var count = 0        -- integer
var speed = 1.5      -- float
var total = count + 1
```

!!! warning

    **Integers and floats are separate.** `speed + count` is a compile error. The VM
    has different instructions for each and no conversion between them, so mixing
    them would reinterpret the value's bits rather than convert it.

Each script gets **16 local slots**. Declared variables use them from one end
and intermediate results from the other; running out is a clear compile error.

### Control flow

```text
if score >= 100 {
    evt_msg_print(0, "nice", 0, 0)
} else if score >= 50 {
    wait(30)
} else {
    return
}

while count < 10 {
    count = count + 1
}

loop 5 {
    wait(10)
}

loop {
    wait(1)          -- forever, until `break`
}
```

`and`, `or` and `not` work, spelled either way (`&&`, `||`). Comparisons are
`== != < > <= >=`.

### Finding what you can call

The game has **443 script builtins**. `bleck` knows all of them:

```bash
bleck script builtins --search coin
```

```
evt_pouch
  evt_pouch_add_coins(...)        1 argument
  evt_pouch_get_coins(...)        1 argument
```

Drop `--search` to list everything, grouped by subsystem.

### Calling game functions

Any of those builtins can be called by name:

```text
evt_mario_set_pos(0.0, 100.0, 0.0)
evt_msg_print(0, "Hello!", 0, 0)
evt_sub_set_game_speed(2.0)
```

Typos and wrong argument counts are caught by `bleck script check`, before
anything is compiled:

```
main.evt:2:5: 'evt_pouch_add_coin' is not a known game function.
  Did you mean one of: evt_pouch_add_coins, evt_pouch_add_item, evt_pouch_add_xp?
2 |     evt_pouch_add_coin(1)
        ^
```

```
main.evt:3:5: evt_mario_set_pos takes 3 argument(s), but 2 were given
  evt_mario_set_pos(f32 x, f32 y, f32 z)
```

!!! note

    Argument counts are only checked where upstream documents them — about two
    thirds of builtins. The rest are variadic or simply undocumented, and `bleck`
    skips them rather than guessing, since a wrong guess would reject working code.

!!! note

    **Calls are statements, not expressions.** `var x = evt_sub_random(5)` will not
    compile. These builtins return results by writing into a slot you pass them,
    not with a return value.

### Game variables

The game's own variables are reachable directly:

```text
gw[3] = 1        -- global work slot, shared between scripts
var flag = gf[2] -- global flag
```

!!! warning

    **`gsw[]` and `gswf[]` are saved to the memory card** and are what the game's
    own story progression uses. Writing one can corrupt a playthrough. Reading them
    is safe and is how a script checks story state.

## What you need installed

| For | Requirement |
|---|---|
| `bleck script check` and `dump` | Nothing |
| Building a module | A PowerPC compiler + a symbol list |

### The compiler

[devkitPPC](https://devkitpro.org/wiki/Getting_Started) provides
`powerpc-eabi-gcc`. `bleck` finds it automatically in the usual install
locations, or set `BLECK_PPC_GCC`.

### The symbol list

Turning `evt_mario_set_pos` into an address needs `spm.eu0.lst` from
[spm-headers](https://github.com/SeekyCt/spm-headers) (`linker/`). `bleck` does
not ship it. Put it in `work/symbols/`, or set `BLECK_SYMBOLS_DIR`.

!!! note

    **Use `eu0` unless you have a reason not to.** Symbol coverage varies a lot by
    game version — eu0 documents about 1111 symbols, `kr0` only 456. A function that
    exists in one list may simply be absent from another.

## Commands

| Command | What it does |
|---|---|
| `bleck script builtins [--search X]` | List the game functions a script can call |
| `bleck script check <file>` | Parse and compile; validate every call |
| `bleck script dump <file>` | Print the C the script compiles to |
| `bleck script build <file>` | Compile all the way to a `.rel` module |
| `bleck mod build <mod>` | Compile the mod's script and build a disc |

## Running a script when a map loads

A `script main` runs continuously during gameplay. To run something *when the
player arrives somewhere*, attach it to a map in `mod.json`:

```json
"code": {
  "script": "scripts/main.evt",
  "maps": { "mac_01": "on_arrive" }
}
```

```
script on_arrive {
    evt_pouch_add_coins(10)
}
```

Now `on_arrive` runs each time that map is reached. A mod using only map hooks
does **not** need a `script main` — that is just the script that free-runs, and
this one has its own way to start.

Find map names with [`bleck maps`](../reference/cli.md#bleck-maps):

```bash
uv run bleck maps --chapter 5
uv run bleck maps --search mac
```

!!! warning "Nothing survives a map change"

    A map hook stops when the player leaves, and starts again on the next
    arrival. The game rebuilds its script state on every map change, so a script
    cannot hold anything across one. Keep state in `gw[]`, which does survive.

## Limits worth knowing

- **One code mod per build.** The loader opens exactly one `/mod/mod.rel`. A
  chain with two code mods fails with both named rather than silently dropping
  one.
- **16 local slots per script.** Split into several scripts, or use `gw[]`.
- **Floats are fixed-point**, about three decimal places, magnitude under
  ~48000.
- **`%` has no float form** in the VM.
