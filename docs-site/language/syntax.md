# Syntax

Everything the parser accepts. For a walk-through, start with
[Scripting](../guides/scripting.md).

## Scripts

A file is one or more `script` blocks and nothing else — there is no top-level
code.

```
script main {
    wait(60)
}

script helper {
    evt_pouch_add_coins(1)
}
```

`main` is the one that free-runs during gameplay. Others start only when
something reaches them: [`spawn`](#spawn), an [attribute](attributes.md), or a
`mod.json` entry.

Two scripts may not share a name, and the compiler says where the first one was.

## Comments

```
-- SPM community style
// also accepted
/* block comments,
   over several lines */
```

## Waiting

```
wait(60)        -- 60 frames
wait_ms(1000)   -- 1000 milliseconds
```

Both take any expression, not just a literal. `wait(0)` yields for one frame.

!!! warning "A script with no wait in its loop hangs the game"

    `evt` is cooperative: nothing preempts a script. A `loop` without a `wait`
    never returns control, and the frame never ends.

## Variables

```
var count = 0
count = count + 1
```

`var` declares a local, backed by one of the 16 `lw` slots. Sixteen is the total
per script, not per scope — see [Storage](storage.md).

Slots can also be addressed directly:

```
gw[3] = 1
lw[0] = gw[3] + 2
```

## Control flow

```
if count > 3 {
    evt_pouch_add_coins(10)
} else if count > 1 {
    evt_pouch_add_coins(5)
} else {
    wait(30)
}
```

```
while count < 10 {
    count = count + 1
    wait(1)
}

loop {
    wait(60)
    break
}
```

`break` and `continue` work in both. `loop` is an unconditional loop — the usual
shape for a `main` that runs for the whole map.

## Switching

```
switch state {
    case 0 {
        wait(30)
    }
    case > 5 {
        evt_pouch_add_coins(1)
    }
    case else {
        break
    }
}
```

A bare `case v` means `== v`. A `case` may also lead with `<`, `>`, `<=`, `>=` or
`!=`.

## Operators

Highest binding last:

| Precedence | Operators |
|---|---|
| 6 | `*` `/` `%` |
| 5 | `+` `-` |
| 4 | `<` `>` `<=` `>=` |
| 3 | `==` `!=` |
| 2 | `and` (`&&`) |
| 1 | `or` (`\|\|`) |

All are **left-associative**. Unary `-` and `not` bind tighter than any of them.

## Calling game functions

```
evt_pouch_add_coins(10)
evt_seq_mapchange("mac_01", 0)
```

Argument counts are checked while the mod builds; a wrong count fails with the
expected number. Types are not checked — see
[Built-in functions](builtins.md).

```bash
uv run bleck script builtins --search coin
```

## `spawn`

```
spawn watcher
```

Starts another script in this file as a child, and continues immediately without
waiting for it.

## `script` as a value

```
evt_door_set_event(door, 0, script on_open)
```

`script <name>` is the **address** of a compiled script, not a call. Some game
functions take one and store it for later — attaching a script to a loading zone,
for instance. Without this there was no way to name a script as a value, and
those functions were unreachable.

## Literals

```
42          -- integer
0x8005000   -- hex integer
1.5         -- float, fixed-point (see Storage)
"mac_01"    -- string, a pointer to a constant
true false  -- booleans
```

⚠️ **`1.foo` is an integer followed by a field access**, not a malformed float. A
dot only continues a number when a digit follows it.

## Attributes

```
#[map("he1_04")]
script on_arrive { ... }
```

See [Attributes](attributes.md).
