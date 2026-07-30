# The scripting language

Super Paper Mario runs its own bytecode VM, `evt`. Every cutscene, every door,
every enemy behaviour is an `evt` script, and the game is already an interpreter
for them. `bleck` compiles a readable language down to that same bytecode, so a
mod's script is something the game runs natively rather than something bolted
alongside it.

```
script main {
    wait(120)
    evt_pouch_add_coins(10)
}
```

That is a complete mod script. It compiles to `evt` instructions, is linked into
the mod's `mod.rel`, and runs on the game's own scheduler.

## What is on these pages

<div class="grid cards" markdown>

-   :material-code-braces: **[Syntax](syntax.md)**

    Scripts, control flow, operators, and everything the parser accepts.

-   :material-database: **[Storage](storage.md)**

    The eight slot classes, which survive a save, and which will corrupt one.

-   :material-tag: **[Attributes](attributes.md)**

    `#[map(...)]` and `#[combo(...)]` — attaching a script without touching
    `mod.json`.

-   :material-function: **[Built-in functions](builtins.md)**

    All 443 game functions a script can call, by module.

</div>

New to this? [Scripting](../guides/scripting.md) is the tutorial; these pages are
the reference.

## What it is not

⚠️ **This is not a general-purpose language, and it cannot become one.** It
compiles to a fixed instruction set that the game already implements, so
everything here is bounded by what `evt` can express:

- **No user-defined functions.** A `script` is the only callable unit, and the
  VM's only call instruction runs a whole script.
- **No arrays, structs or strings you build.** String literals are pointers to
  constants; there is no string type.
- **No arithmetic on pointers**, and no memory access beyond the slot classes.
- **16 local integers per script.** Not 16 variables *in scope* — 16 in total.

These are the VM's limits rather than the compiler's, so working around them
means writing a [code mod](../guides/code-mods.md) in C and calling it from a
script.

## How a script reaches the game

```
your .evt  ->  evt bytecode  ->  generated C  ->  PowerPC  ->  mod.rel
```

The bytecode is emitted as a C array and compiled into the module, rather than
shipped as a separate data file. That is what lets one `mod.rel` carry several
mods' scripts at once — the loader opens exactly one module, so mods are merged
at compile time.

!!! note "Two terminators, not one"

    Every script ends with `END_EVT` *and* `END_SCRIPT`. Emitting only one
    froze the game. You never write these — the compiler does — but it explains
    why a hand-written `evt` array from elsewhere may not behave.
