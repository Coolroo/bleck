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

        `code.banner` <span class="pf-type">object or `false`</span> <span class="pf-default">default: on</span>

        :   The `mod_loaded: <name>` label drawn in the bottom right of the
            title screen. **On by default — you do not need to declare it.**

            Set it to `false` to suppress the label, or pass an object to
            change it:

            - `text` — replaces the whole label. Defaults to
              `mod_loaded: <mod name>`.
            - `sequences` — which parts of the game draw it. One or more of
              `logo`, `title`, `game`, `mapchange`, `gameover`, `load`.
              Defaults to `["title"]`.

        `code.maps` <span class="pf-type">object</span>

        :   Scripts to run on arrival at a map, as map name → script name:

            ```json
            "maps": { "aa4_01": "on_arrive", "mac_01": "greet" }
            ```

            The script starts each time that map is reached, and stops when the
            map is left — evt state is rebuilt on every map change, so nothing
            survives one.

            You do not have to know map names by heart — `bleck` lists them,
            with the chapter each belongs to:

            ```bash
            uv run bleck maps --areas        # every area, in playthrough order
            uv run bleck maps --chapter 5    # just chapter 5
            uv run bleck maps --search mac   # Flipside / Flopside
            ```

            ```
              186  sp1_01     Ch 5-1  Land of the Cragnons
              187  sp1_02     Ch 5-1  Land of the Cragnons
            ```

            The leading number is the game's own map id.

            A mod using only map hooks does **not** need a `script main`;
            `main` is what runs continuously during gameplay, and a map hook has
            its own way to start.

        `code.boot` <span class="pf-type">string</span>

        :   A map to start the game at, instead of the attract demo:

            ```json
            "code": { "boot": "he1_01" }
            ```

            Without a controller the game boots into `aa4_01`, then `ls4_12`,
            and nowhere else. `boot` sends the disc straight to the map you
            name, so you can look at a mod without playing to it.

            `bleck` generates the script that does this, so a mod needs no
            `code.script` — and no `code` block at all if `boot` is the only
            thing in it. `bleck mod build --map <name|id>` sets it for one
            build without touching the manifest.

            !!! warning "The player is uninitialised"

                No save file and no profile means **Mario is invisible** and
                anything reading player state is meaningless. This is for
                looking at a map, not playing it.

        `code.combos` <span class="pf-type">object</span>

        :   Scripts to run when a button combination is pressed, as
            combination name → script name:

            ```json
            "combos": { "start_map": "warp_home" }
            ```

            The **name** is defined once in `bleck.yml` at the top of your
            project, so a mod never contains a button mask:

            ```yaml
            combos:
              start_map: [1, 2]
            ```

            Changing which buttons `start_map` means is one edit in one file,
            however many mods use it. Valid button names are `a`, `b`, `1`,
            `2`, `plus`, `minus`, `home`, `up`, `down`, `left`, `right`.

            Two buttons minimum, so a combination cannot fire while you are
            walking around. For a deliberate single-button trigger, write
            `{buttons: [home], allow_single: true}`.

            The combination fires **once** when it becomes held, not while it
            is held, and re-arms when you let go. A mod may declare up to 32.

            !!! note "Nunchuk buttons are not supported"

                `c` and `z` are not in the field `bleck` reads. Asking for one
                gets an error saying so rather than "unknown button".

`setup` <span class="pf-type">object</span>

:   Changes to a map's enemy placement, as map name → a list of slot edits.
    `bleck` derives the file at build time, so the change stays reviewable in
    the manifest rather than hidden in a binary.

    ```json
    "setup": {
      "he1_01": [
        { "slot": 0, "template": 148 },
        { "slot": 2, "position": [-75, 0, -75] },
        { "slot": 1, "clear": true }
      ]
    }
    ```

    Each edit needs a `slot` (0–99) and at least one of `template`, `position`
    or `clear`. See what a map currently places with
    [`bleck setup show`](cli.md#bleck-setup).

    !!! note

        `bleck` writes **both** copies of the setup file — the standalone
        `files/setup/<map>.dat` the game reads, and the byte-identical one
        inside the map archive, so nothing stale is left on the disc.

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
