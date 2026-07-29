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

            - `script` — which script, as `<kind>:<name>`. Three kinds:

                | Selector | Reaches |
                |---|---|
                | `map:he1_01` | that map's init script |
                | `item:0x41` | that item's use script |
                | `item:fire_burst` | the same, by name |
                | `door:he1_01:0` | that door's interact script |
                | `door:he1_01:0:init` | that door's init script |
                | `door:he1_01:0:move` | that door's move script |

                A door selector is
                `door:<map>:<index>[:interact|init|move]`. The last part
                picks one of the door's three scripts and defaults to
                `interact` — the script that runs when the player uses the
                door. `bleck` finds the door by loading the map's data,
                walking its init script for the call that registers the
                map's doors, and indexing the array it registers.

                The index is a **position in that list, in registration
                order**, not an id — the game gives no way to look a door up
                by name. The list lives in the game's data, so the index
                cannot be checked while building: one past the end resolves
                to nothing and reports status `4` at run time rather than
                writing anywhere.

                An **item** may be a number (`item:65`, `item:0x41`) or a
                name: its English name (`fire_burst`), its internal name
                (`HONOO_SAKURETU`), or its `ITEM_ID_*` constant with the
                `ITEM_ID_` and group prefixes optional. Case, `-`, `_` and
                spaces are all equivalent. Names resolve while the manifest
                is read, and the manifest keeps the one you wrote. A name
                that means two items — `mario` is a character item *and* a
                card — is refused with the candidates listed.

                Ids and `ITEM_ID_*` constants are built into `bleck`;
                English names come from a data file shipped beside it. If
                that file is missing, only the English spelling stops
                resolving, and it says so.

                [`bleck items`](cli.md#bleck-items) lists all 538 with
                every spelling each one accepts, so you need not guess:

                ```bash
                bleck items --search fire
                bleck items --group CARD
                ```
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

                Doors have no sensible default to offer here: `he1_01`'s first
                door opens its interact script with `MULF`, a float multiply,
                rather than the `USER_FUNC` you might expect. Read the word
                that is actually there and put it in `expect`.

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

            !!! note "Item and door patches are checked less far than map ones"

                An item's use script runs only when a player uses that item, and
                a door's interact script only when a player uses that door. Both
                kinds of patch are checked as far as "resolved the right script
                and wrote into it" — your function has not been observed
                running. Read `bleck_patch_status[]`, then confirm the rest by
                hand.

            A patch is applied when the module loads and stays applied for the
            rest of the session, including maps you enter later. Your C can
            read what happened:

            ```c
            extern unsigned int bleck_patch_status[];
            /* 1 pending, 2 applied, 3 refused by the guard,
               4 no script -- including a door index the map does not have,
               5 no such item id in the table */

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

    Each edit needs a `slot` (0–99) and at least one of `template`, `position`,
    `copy_from` or `clear`. See what a map currently places with
    [`bleck setup show`](cli.md#bleck-setup).

    `copy_from` names a slot whose **whole entry** is copied in before
    `template` and `position` are applied:

    ```json
    { "slot": 3, "copy_from": 0, "template": 2, "position": [-300, 0, 0] }
    ```

    An edit otherwise builds on whatever the slot already holds, and an unused
    slot holds zeros — where every enemy the game ships carries three values
    nobody has identified, which do reach the live NPC. Copying an existing
    enemy carries them across without your having to know what they are. Copying
    an **empty** slot is refused, because it would carry nothing and quietly
    look like it had.

    A map may instead be written as an object, which is how it declares
    **placed coins** as well as enemies:

    ```json
    "setup": {
      "he1_03": {
        "enemies": [ { "slot": 0, "template": 148 } ],
        "coins": [
          { "position": [-300, 50, 0] },
          { "index": 1, "clear": true }
        ]
      }
    }
    ```

    The bare list is not deprecated — it means `enemies`, and stays exactly as
    valid.

    A coin edit takes an optional `index`, a `position`, `flags` and `clear`.
    **Leaving `index` out adds a coin**; giving it moves one the map already
    places. That is the opposite of an enemy edit, and deliberately so: enemies
    live in 100 fixed slots, while coins are a counted list with no empty
    entries. For the same reason `clear` needs an `index` — there is no empty
    coin to clear.

    !!! note "Coins, not items"

        A setup file's item section can hold nothing but coins. The game's
        `setupItemTemplates` has exactly one entry, and the spawner takes a
        different code path for it than for every other item — so there is no
        `type` to set. All 299 the game ships are coins with `flags` `0x11`;
        `0x10` and `0x1` are what make one spawn at all.

    !!! danger "Some maps have no room for another coin"

        A coin is persistent, so each needs a save flag, and 32 maps reserve a
        fixed number of them — spent by coins in blocks as well as floating
        ones. Adding a coin to one of those that has already spent its
        allowance **hangs the game**, and `bleck` refuses it at build time
        rather than producing a disc that freezes.

        Every other map — 204 of the 227 with a setup file — takes coins fine.
        `bleck` warns there instead: those coins have no save flag, so they may
        reappear each time the map loads.

        The reason is that a coin is persistent, so each one needs a save flag,
        and every map has a fixed budget of them — spent by coins in blocks as
        well as floating ones. A map that places no floating coins has typically
        already spent it, and the game asserts *"the coin flags have
        overflowed"*. [`bleck setup show <map>`](cli.md#bleck-setup) says whether a
        map is one of the 14.

        Adding coins to one of the 14 maps that *do* place them works —
        `he1_03` was taken from 5 to 7 and reached gameplay. At most 512 per
        map: the game copies the file's own count into a fixed buffer without
        clamping it, and the busiest map it ships places 48.

    !!! note

        `bleck` writes **both** copies of the setup file — the standalone
        `files/setup/<map>.dat` the game reads, and the byte-identical one
        inside the map archive, so nothing stale is left on the disc.

`tables` <span class="pf-type">object</span>

:   The same placements as `setup`, in CSV files instead. Past a handful of
    rows, JSON stops being readable and starts being punctuation.

    ```json
    "tables": {
      "enemies": "tables/enemies.csv",
      "coins": "tables/coins.csv"
    }
    ```

    ```csv
    # mods/my-mod/tables/enemies.csv
    map,slot,template,x,y,z,copy_from
    he1_01,3,Squiglet,-300,0,0,0
    he1_01,4,55,-450,0,0,
    ```

    **The key says what the table's rows describe, not what to call the file.**
    It is a closed set — `enemies` and `coins` — so a label like `"lineland"` is
    refused rather than read as enemy placements on the strength of being
    present. `doors` is designed and not built; declaring one says so, instead
    of accepting a table nothing will ever read.

    `bleck mod new` scaffolds both files, empty, and references them from the
    manifest it writes.

    The value is a path relative to the mod, or an object with a `path` and a
    `map`, or a **list** of either:

    ```json
    "tables": {
      "enemies": [
        { "path": "tables/he1_01.csv", "map": "he1_01" },
        { "path": "tables/he2_01.csv", "map": "he2_01" }
      ]
    }
    ```

    **A table with a `map` lets every row drop the column** — one file per
    level, and nothing repeating the filename. A bound table may *not* also
    have a `map` column; two places to say the same thing is two places for them
    to disagree.

    An **enemy** table's columns:

    | Column | |
    |---|---|
    | `map` | Required unless the table is bound to a map |
    | `slot` | Required. 0–99 |
    | `template` | A template number, or an enemy's name |
    | `x`, `y`, `z` | All three or none. Two is an error, not a silent zero |
    | `copy_from` | A slot to copy first, as above |
    | `clear` | `true` to empty the slot |

    A **coin** table's, which are deliberately not the same:

    ```csv
    # mods/my-mod/tables/coins.csv
    map,index,x,y,z
    he1_03,,-300,50,0
    he1_03,1,999,0,0
    ```

    | Column | |
    |---|---|
    | `map` | Required unless the table is bound to a map |
    | `index` | **Optional. Leave it empty to add a coin**, or name one the map already places |
    | `x`, `y`, `z` | All three or none. Required when adding |
        | `flags` | `0x11` spawns; base-prefixed, so `0x11` and `17` both work |
    | `clear` | `true` to remove the coin. Needs an `index` |

    Enemies have 100 fixed slots and coins are a counted list, so `slot` and
    `index` are different words for genuinely different things. Indexed edits
    resolve against the list **as the game ships it**, so the order rows appear
    in cannot change what a table means.

    A header row is required and column **order is free**. An unknown column is
    an error that names it and lists the ones that exist. Every message names
    the file and the line — `tables/enemies.csv:4: ...` — because a table is
    only worth having once there are more rows than you want to count.

    `template` takes a name as well as a number, resolved through the NPC
    catalog `bleck` ships: `Squiglet`, `squiglet`, `SQUIGLET` and the model name
    `e_octa2` are all the same enemy. **A name that fits several templates is
    refused, not guessed** — `Goomba` alone covers 35 of them, so those cases
    want the number. [`bleck setup show <map>`](cli.md#bleck-setup) lists the
    templates a map actually uses.

    !!! warning "`#` comments are an extension, and the format's one weak spot"

        CSV has no comment syntax. `bleck` skips lines whose first character is
        `#`, and blank lines, so a table can say *why* a row exists. The cost is
        that these files are no longer strictly CSV: a quoted field cannot
        contain a newline, and a tool that writes exact CSV will not produce the
        comments (it will still read fine).

    !!! note "One slot, one place"

        Declaring the same `(map, slot)` both inline in `setup` and in a table
        is an error naming both. Across *different* mods it is an ordinary
        conflict, and the install order settles it as usual.

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
