---
title: Findings — measured facts about Super Paper Mario
description: Things about SPM's internals that we had to measure because no wiki, forum or repository records them — with the evidence, and with what is still unproven
---

# Findings

Facts about **Super Paper Mario**'s internals that we had to establish by
measurement, because they are not recorded on any wiki, forum or repository we
could find. Several of them exist because a published header or a natural
assumption is **wrong**.

This section is not about `bleck`, the toolkit this site otherwise documents.
You do not need it, and none of these pages assume you have it. If you are
reverse-engineering this game, writing a mod loader, decoding a format or
maintaining `spm-headers`, take what is useful.

!!! info "Everything is PAL rev 0"

    Addresses are for **`R8PP01`, PAL revision 0** ("eu0") — the build every
    upstream research project documents — and **do not transfer** to other
    revisions. Structure layouts, formats and behaviours generally do; the
    numbers do not.

    Every runtime result is **Dolphin's** behaviour. Nothing here has been run
    on real Wii hardware.

## How to read these pages

Each page states the fact, then the evidence — addresses, byte values, counts,
what was measured and how — then what is *not* established. Confidence is marked
inline and always means the same thing:

| | |
|---|---|
| ✅ | observed directly |
| 🔶 | inferred or hypothesised; **not** measured |
| ⛔ | ruled out, or superseded and wrong |
| ⚠️ | a trap: true, and easy to misread |

Sources are cited as `D<number>` — entries in this project's decision log, which
is a public, append-only record in the repository:
[`docs/decision-log.md`](https://github.com/Coolroo/bleck/blob/main/docs/decision-log.md).
You should never need to open it; the evidence is on the page.

⚠️ Some of what is published here overturned an earlier conclusion of our own,
and a few of those earlier conclusions were confidently written and internally
consistent. Where that happened it is said out loud, because how a wrong thing
survived is usually more useful than the right answer alone.

## [How these were measured](method.md)

A module runs inside the game and writes to a fixed unused address; a script
outside Dolphin reads it while the game runs. That page also records the probe
rules learned by losing runs — chiefly that **a probe must report the
precondition it depends on**, not only the value it went looking for, and that a
control proves the instrument *works*, not that it is *aimed*.

## Corrections to published material

| page | what is wrong |
|---|---|
| [`evt_door_set_door_descs` takes argc 3](evt-door-argc.md) | `spm-headers` declares 1 argument; the game uses 2, matching the comment directly above the macro. Contradicts its own sibling declarations |
| [Two wrong names in the PAL symbol list](symbol-list-errors.md) | `strlen` in `spm.eu0.lst` points at `TRK_strlen`; `evt_fairy_flag_onoff` points at `evt_fairy_flag_onoff_all`. Also: 148 of 443 declared evt builtins have no linkable address |
| [The setup file format](setup-file-format.md) | The widely-linked Google Doc's "consistently 11,204 bytes" is true of 184 of 227 files. The stride is a function of the version field |
| [Which setup file the game reads](setup-which-copy.md) | The standalone `files/setup/<map>.dat`, not the copy embedded in the map archive — **we published the opposite first** |

## The evt VM

| page | claim |
|---|---|
| [An evt script that ends needs `END_EVT`](evt-script-end.md) | `END_SCRIPT` alone leaves the entry alive and the game hangs a few frames later, with every value the script wrote still correct. `EVT_END()` in the upstream macros emits only `END_SCRIPT` |
| [How an evt instruction is encoded](evt-instruction-format.md) | Header word `(argc << 16) \| opcode` plus `argc` words; how `USER_FUNC` receives its arguments; operand biases; same-size in-place replacement, and why no cache flush is needed |
| [`evt_door_set_door_descs` takes argc 3](evt-door-argc.md) | The header is wrong, and a bytecode search constrained by it finds nothing |

## Game data

| page | claim |
|---|---|
| [Door descriptors](door-descriptors.md) | Doors are registered from the map's own init script with the array address in the bytecode; the three script pointers; a door interact script opens with `MULF`; one use of a door runs its interact script ~62 times, and the door still works with that first instruction destroyed |
| [`npcEnemyTemplates`](npc-enemy-templates.md) | Enemy behaviour scripts are in a static table, stride `0x68`, entry *n* = template *n* — and **280 templates share one Goomba's death script**, confirmed in game by a Goomba-targeted patch firing on a Squiglet |
| [`itemEventDataTable`](item-event-data-table.md) | The 33 items that have a use script, by id — 11 of them cooked items and one a key — and only 19 of the 33 scripts open with a `USER_FUNC` |
| [`itemDataTable`](item-data-table.md) | 538 entries at stride `0x2C`, length proven two ways; the internal names are **romaji**, and the English name is a second lookup that is not derivable from them |
| [The message file format](msg-file-format.md) | `files/msg/<lang>/*.txt` is a flat run of NUL-terminated `key\0value\0` pairs from byte 0, with no header. JP is Shift-JIS |
| [The setup file format](setup-file-format.md) | Always 100 entries; the stride varies with the version; and **clearing a slot in the middle silently discards every slot after it** |
| [Which setup file the game reads](setup-which-copy.md) | The standalone copy. Editing only the embedded one is a no-op |
| [Placed items and the 512 ceiling](setup-items.md) | The loader memcpys the file's own count into a fixed 8192-byte buffer, unclamped; a map that ships no item section **hangs** if given one |

## Code, tooling and formats

| page | claim |
|---|---|
| [Patching PowerPC code at runtime](ppc-code-patching.md) | The `dcbst`/`sync`/`icbi`/`isync` flush is load-bearing, measured against a no-flush control that left the *new* word visible in memory while the CPU kept running the old body |
| [Tracing a function without a trampoline](function-tracing.md) | A self-healing detour records arguments and return values while the original still runs, and works on a function starting with a branch — which a trampoline cannot relocate. Plus the full list of what a trace cannot see |
| [Four functions, measured](undocumented-functions.md) | `GetBasicPlayer` returns `arg0 + 0xD8`; `func_800cd554` is an alternate entry to `effSmallStarEntry`; **do not stub `effMain`**; every `mapDataPtr` caller passes the same buffer |
| [Two wrong names in the PAL symbol list](symbol-list-errors.md) | Found by comparing two upstream sources that had only ever been used separately |
| [LZ77 does not have to be bit-exact](lz77-not-bit-exact.md) | A stream 0.25% larger with different token boundaries boots and renders. Nintendo's own streams contain **overlapping** back-references |

## Testing the game

| page | claim |
|---|---|
| [What an unattended boot runs](attract-demo.md) | No title screen at all; two maps; no NPCs; no doors; no player session — and three "the game does not do X" results that were really "these two maps do not" |
| [The pouch and the save slots](player-session.md) | `pouchGetPtr()` is a **stable** address whose contents mean different things at different times; `pouchAddItem` refuses in the demo and works in a real session; an empty save slot is distinguishable from a written one |

## What is not here

We do not redistribute game data, and we do not republish upstream symbol lists
or headers. Individual addresses appear as evidence for specific findings;
whole tables do not. Take symbol lists from
[`spm-headers`](https://github.com/SeekyCt/spm-headers) and
[`spm-decomp`](https://github.com/SeekyCt/spm-decomp), whose work they are.
