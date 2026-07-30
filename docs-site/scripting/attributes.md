# Attributes

An attribute declares, above a script, something `mod.json` would otherwise have
to repeat as a string.

```
#[map("he1_04")]
script on_arrive {
    evt_pouch_add_coins(10)
}
```

That replaces a `code.maps` entry. The manifest needs nothing:

```json
"code": {
  "script": "scripts/main.evt",
  "sources": ["src"]
}
```

## The attributes

| Attribute | Replaces | What it does |
|---|---|---|
| `#[map("name")]` | `code.maps` | runs this script each time that map loads |
| `#[combo("name")]` | `code.combos` | runs it on a button combination from `bleck.yml` |

Both take one quoted string, must sit on their own line, and must be directly
above a `script` declaration. Several may stack:

```
#[map("he1_04")]
#[combo("dev")]
script both { ... }
```

An unrecognised attribute is an error naming the file and line — it is never
ignored.

## Hooks are tagged in C, not here

A hook points a **game C function** at one of yours, so it belongs beside that
function rather than in a script:

```c
#include <bleck.h>

BLECK_HOOK(mapDataPtr, before)
void watchMapData(void *work) { ... }
```

Full detail in [Code mods](../guides/code-mods.md#declaring-the-hook-in-the-source-instead).

## Declare each thing once

!!! warning "A tag and a `mod.json` entry may not claim the same thing"

    Declaring `he1_04` in both a `#[map(...)]` attribute and `code.maps` is an
    error, and `bleck` names both places:

    ```
    m: map hook conflict on 'map:he1_04'
      scripts/main.evt:4       declares it as a tag
      code.maps[0]             declares it in mod.json
    Declare it once. Tags and mod.json do not override one another.
    ```

Neither side wins. Silent precedence would mean a declaration that parses, is
ignored, and still reports success — which is a failure mode this project has
hit enough times to refuse on principle.

Only the **claimed thing** is exclusive. One map may be claimed once; a single
script may still be attached to two different maps.

## Why not put everything in the manifest

`mod.json` can only name a script or a function as a *string*. Rename the thing
and the manifest silently points at nothing, or the build fails somewhere
unrelated. An attribute sits on the declaration it describes, so the two cannot
drift apart.

`example-mods/tag-demo` is the worked example: it declares no hooks and no maps
in its manifest, and builds with both.
