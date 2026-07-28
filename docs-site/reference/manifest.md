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

        `code.patches` <span class="pf-type">list of objects</span>

        :   Replaces one instruction of a script **the game already ships**
            with a call into your own C, so vanilla content can run your code:

            ```json
            "patches": [
              {
                "script": "map:he1_01",
                "at": 0,
                "expect": "DEBUG_PUT_MSG",
                "call": "on_map_init"
              }
            ]
            ```

            - `script` — which script, as `<kind>:<name>`. Two kinds:
              `map:he1_01` for a map's init script, `item:0x41` for an item's
              use script. `door:` is not supported.
            - `at` — word offset into the script where the instruction begins.
            - `expect` — the opcode you expect to find there. **Required.**
              An opcode name (`"DEBUG_PUT_MSG"`), a name with its argument
              count where the opcode is variadic (`"USER_FUNC 4"`), or a raw
              header word (`"0x00010072"`).
            - `call` — a function in your own `code.sources`, with the
              signature `s32 f(EvtEntry *entry, bool firstCall)`. Return `2`
              so the script carries on.

            !!! warning "`expect` is a guard, not a comment"

                Nothing is written unless the word at `at` is what you said
                would be there. A wrong offset then leaves the game untouched
                and reports a status, instead of corrupting a script.

            The replacement is a `USER_FUNC` declaring the **same argument
            count** as the instruction it overwrites, so it is always the same
            size: your function pointer takes the first argument word and the
            original's remaining arguments are carried through untouched,
            reaching your code through the `EvtEntry`. Patches cannot insert or
            delete instructions, and a one-word instruction is refused at build
            time because the function pointer would not fit.

            !!! warning "One item id can change several items"

                The game's item table holds 33 entries but only 22 distinct
                scripts, so several ids share one. `bleck_patch_shared[]`
                reports how many entries point at the script your patch hit.

                An item's use script runs only when a player uses that item, so
                an `item:` patch is checked as far as "resolved the right script
                and wrote into it". Confirm the rest by hand.

            A patch is applied when the module loads and stays applied for the
            rest of the session, including maps you enter later. Your C can
            read what happened:

            ```c
            extern unsigned int bleck_patch_status[];
            /* 1 pending, 2 applied, 3 refused by the guard,
               4 no script, 5 no such item id in the table */

            extern unsigned int bleck_patch_shared[];
            /* 0xFFFFFFFF where nothing counted, e.g. every map patch */
            ```

        `code.hooks` <span class="pf-type">list of objects</span>

        :   Points one of the game's **C functions** at one of yours, so every
            call into it reaches your mod — before, after, or instead of the
            original:

            ```json
            "hooks": [
              {
                "function": "npcDispMain",
                "call": "count_npcs",
                "mode": "replace"
              }
            ]
            ```

            - `function` — the game function to hook. A symbol name, resolved
              against your `code.target`'s symbol list **while the mod
              builds**; a name that is not in the list fails the build, with a
              suggestion. A raw address (`"0x801adef0"`) is accepted for
              something the list does not name.
            - `call` — a function in your own `code.sources`. It has to accept
              the same arguments as the function it hooks, in every mode.
            - `mode` — `"replace"` (the default), `"before"` or `"after"`.

            | `mode` | What runs | Your return value |
            |---|---|---|
            | `"replace"` | yours, and the original **never** | is what the caller gets |
            | `"before"` | yours, then the original | discarded |
            | `"after"` | the original, then yours | discarded |

            !!! danger "`replace` means the original never runs"

                The function's first instruction becomes a branch into your
                code and its body is gone for the rest of the session, so
                **your function is now the whole implementation**. Hooking a
                drawing function stops that thing being drawn; hooking
                something a game sequence waits on stops the game.

                Use `"before"` or `"after"` to *add* behaviour. Under those the
                caller receives the original's return value, so your function
                cannot change what the game sees by returning something.

            !!! warning "Nothing checks your function's signature"

                A symbol list carries addresses, not types, so `bleck` cannot
                verify that `call` accepts what the hooked function is passed.
                Declaring the wrong signature corrupts the call.

                A function taking **more than eight integer arguments** cannot
                be used with `"before"` or `"after"` at all — the rest live in
                the caller's stack frame, which the wrapper does not share.
                This is not checked either.

            You do not write a guard. `bleck` reads the instruction word
            actually at that address out of the base disc's `main.dol` while
            building, and the hook refuses to install unless the running game
            has the same word. A wrong address, or a mod built against a
            different game version, is then a refusal rather than a corrupted
            instruction.

            !!! warning "An address outside the DOL cannot be guarded"

                `bleck` only has the base disc's `main.dol` to read from, so an
                address that is not in it — a REL address, for instance — gets
                no guard. Under `"replace"` the build **warns** and the hook
                installs unchecked. A guard is never invented for one.

                Under `"before"` and `"after"` it is a build **error**. Those
                reach the original by restoring that word for the duration of
                the call, so with nothing to restore the hook would branch into
                itself until the stack ran out.

            Hooks install when the module loads, before your `mod_prolog`, so
            your C can read a final answer:

            ```c
            extern unsigned int bleck_hook_status[];
            /* 1 pending, 2 installed, 3 refused by the guard,
               4 misaligned, 5 out of range */

            extern const unsigned int bleck_hook_count;
            ```

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
