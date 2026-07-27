---
title: mod.json
description: The mod manifest format
---

Every mod has a `mod.json` at its root.

```json
{
  "schema": 1,
  "name": "hard-mode-plus",
  "version": "0.1.0",
  "description": "Rebalanced enemy damage",
  "author": "coolroo",
  "base": "eu0",
  "created": "2026-07-26",
  "dependencies": [
    { "name": "hard-mode", "version": ">=2.0.0" }
  ],
  "exclusive": ["files/rel/rel.bin"],
  "remove": ["files/some/unwanted.bin"]
}
```

## Fields

`name` <span class="pf-type">string</span>{ .pf-required }

:   The mod's identifier. Dependencies resolve against it.


`version` <span class="pf-type">string</span> <span class="pf-default">default: `0.0.0`</span>

:   Semantic version, `MAJOR.MINOR.PATCH`.


`base` <span class="pf-type">string</span>

:   Which base build this targets, e.g. `eu0`. Building against a different base
    is an error.

    This matters: `eu0` contains files `us0` does not, so a mod referencing them
    cannot apply to a US disc at all.


`dependencies` <span class="pf-type">array</span>

:   Mods that must apply before this one. Each entry is `{ "name": "..." }` with
    an optional `"version"` constraint using `>=`, `<=` or `==`.

    A bare string is also accepted as shorthand for an unconstrained dependency.


`exclusive` <span class="pf-type">array</span>

:   Paths this mod claims outright. Any other mod touching one is an error, with
    no merge attempted.

    Intended for files where concurrent edits cannot be sound — compiled code, or
    formats with internal offsets.


`remove` <span class="pf-type">array</span>

:   Base files to delete. An overlay can express "replace" and "add" but not
    "absent", so deletions live here.


`schema` <span class="pf-type">integer</span> <span class="pf-default">default: `1`</span>

:   Manifest format version. An unknown value is rejected rather than guessed at.


`code` <span class="pf-type">object</span>

:   Present only for mods that ship behaviour. See [Scripting](../guides/scripting.md).

    ??? note "fields"

        `code.script` <span class="pf-type">string</span>

        :   Path to the script source, relative to the mod directory.

        `code.sources` <span class="pf-type">array</span>

        :   Native C sources compiled into the same module, relative to the mod
            directory. Each entry may be a file or a directory; a directory
            contributes every `.c` beneath it. See
            [Code mods](../guides/code-mods.md).

            At least one of `script` or `sources` is required.

        `code.target` <span class="pf-type">string</span> <span class="pf-default">default: `eu0`</span>

        :   Game version whose symbol list resolves the functions the script
            calls. Addresses differ per version, so building against the wrong
            list produces a module that jumps into unrelated code.

        `code.module_id` <span class="pf-type">integer</span> <span class="pf-default">default: `2`</span>

        :   REL module id. The game's own REL is 1, so mods start at 2.

```json
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

!!! note

    The compiled module is written to `overlay/files/mod/mod.rel` and then carried
    by the ordinary overlay machinery — a code mod is still just a mod. Only one
    code mod can be in a build, because the loader opens exactly that one path.

## Layout

```
mods/my-mod/
  mod.json
  overlay/                    mirrors the extracted disc root
    files/...                 the data partition
    sys/...                   also addressable
```

!!! note

    The overlay mirrors the **extract root**, not the data partition, so `sys/`
    files are reachable. It is called `overlay/` rather than `files/` because the
    disc's own data partition is `files/` — `overlay/files/...` reads correctly
    where `files/files/...` would not.

## Version constraints

| Constraint | Matches |
|---|---|
| *(omitted)* | Any version |
| `>=1.2.0` | 1.2.0 and above |
| `<=2.0.0` | 2.0.0 and below |
| `==1.0.0` | Exactly 1.0.0 |
