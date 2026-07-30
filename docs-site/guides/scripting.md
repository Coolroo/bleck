---
title: Scripting
description: Write mod behaviour in a small language that compiles to the game's own script VM
---

Super Paper Mario ships its own scripting VM — the game calls it `evt`, and it
runs cutscenes, NPC behaviour, doors, item pickups and map logic. `bleck`
compiles a small friendly language down to that VM's bytecode.

Your script runs on the game's own interpreter, scheduled cooperatively
alongside the game's scripts. There is no runtime to install and nothing extra
loaded into memory.

!!! note

    **Scripting handles event logic, not engine internals.** It is excellent at
    "wait, move, speak, branch on a flag, spawn a child script". Changing how an
    existing function *behaves* still needs a native hook — see
    [Code mods](../guides/code-mods.md).

## Naming a script without running it

Some of the game's builtins take a script and keep it for later rather than
running it. `script <name>` is how you pass one:

```
script main {
    evt_door_set_event("doa2_l", 0, script on_enter)
}

script on_enter {
    evt_msg_print(0, "you came through the star door", 0, 0)
}
```

!!! warning "`script name` is not `spawn name`"

    `spawn on_enter` starts it **now**. `script on_enter` only names it, so
    whatever you hand it to can start it later — here, when the player uses
    that loading zone.

This is what makes loading zones scriptable at all: unlike a door, a zone has
no script of its own, and `evt_door_set_event` is how the game itself attaches
one — it does so on 13 maps. See [`bleck doors`](../reference/cli.md#bleck-doors)
for which zones a map has.

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
bleck script check example-mods/speedrun/scripts/main.evt
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

!!! tip "Reference pages"

    This is the tour. The full reference lives under
    [Scripting](../scripting/index.md) —
    [syntax](../scripting/syntax.md), [storage classes](../scripting/storage.md),
    [attributes](../scripting/attributes.md) and all
    [443 built-in functions](../scripting/builtins.md).


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
your script is paused.

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

### Switching on a value

```text
switch enemy_type {
    case 1 {
        evt_msg_print(0, "goomba", 0, 0)
    }
    case 2, 3 {          -- a comma list matches any of them
        evt_msg_print(0, "koopa", 0, 0)
    }
    case > 10 {          -- any comparison works
        evt_msg_print(0, "boss", 0, 0)
    }
    else {               -- optional, at most one, and last
        return
    }
}
```

Cases do not fall through, so no `break` is needed — and `break` inside a case
is rejected rather than quietly breaking an enclosing loop. The value you switch
on can be any expression; the values in each `case` must be a number, a variable
or a slot, so work out anything more involved beforehand. Integers only.

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

    Argument counts are only checked for builtins whose signature is documented
    upstream. The rest are variadic or undocumented, and `bleck` accepts any
    argument count for them rather than guessing.

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

### Attaching it in the script instead

The same attachment can be written above the script, so the map name sits with
the code it runs:

```
#[map("mac_01")]
script on_arrive {
    evt_pouch_add_coins(10)
}
```

Then `mod.json` needs no `maps` block at all. `#[combo("dev")]` works the same
way for a button combination from `bleck.yml`.

!!! warning "Declare it once"

    A `#[map(...)]` attribute and a `maps` entry for the same map is an error,
    naming both places. Neither overrides the other.

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

- **One `mod.rel` per disc.** The loader opens exactly one. `bleck` compiles
  every code mod in a chain into that single module — see
  [Several code mods on one disc](../guides/code-mods.md#several-code-mods-on-one-disc).
- **16 local slots per script.** Split into several scripts, or use `gw[]`.
- **Floats are fixed-point**, about three decimal places, magnitude under
  ~48000.
- **`%` has no float form** in the VM.
