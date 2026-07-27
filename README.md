# bleck

A modding toolkit for **Super Paper Mario** (Wii, 2007).

`bleck` extracts a disc, applies layered mods, compiles scripts and C into game
code, and rebuilds a bootable image — as one command:

```bash
uv run bleck mod build my-mod work/out/my-mod.wbfs --launch
```

It ships a small scripting language that compiles to **the game's own bytecode
VM**, so there is no interpreter to port and no runtime to pay for. A script can
run continuously, or be attached to a map so it fires on arrival:

```json
"code": { "script": "scripts/main.evt", "maps": { "mac_01": "on_arrive" } }
```

Docs live in [`docs-site/`](docs-site/) (users) and [`docs/`](docs/)
(maintainers — the design record and every decision, with its evidence).

---

## Credit where it is due

**`bleck` exists because other people did the hard reverse-engineering first.**
Almost everything this toolkit knows about Super Paper Mario — what the opcodes
mean, where the functions live, how a REL is loaded — was worked out by the
projects below and published. None of it is our discovery.

### [`SeekyCt/spm-headers`](https://github.com/SeekyCt/spm-headers) — MIT

The single most load-bearing dependency. Its `include/`, `decomp/` and `linker/`
directories are MIT-licensed by its README.

| What we use | How |
|---|---|
| `linker/spm.<version>.lst` | Turns every function name a mod writes into an address. **Not vendored** — supply your own via `BLECK_SYMBOLS_DIR` |
| `include/**` struct layouts | `MapData`, `SeqDef`, `SeqWork`, `fontmgr` signatures — what generated C is written against |
| `EVT_DECLARE_USER_FUNC` declarations | The source of [`bleck/script/catalog.json`](bleck/script/catalog.json): 443 builtins with names and argument counts. **This is vendored**, with attribution inside the file, and regenerable with `bleck script index <path-to-spm-headers/include>` |

⚠️ Its `mod/` directory is **GPLv3**, not MIT — the README is explicit that it is
derived from other GPL code. `bleck` takes nothing from there.

### [`SeekyCt/spm-rel-loader`](https://github.com/SeekyCt/spm-rel-loader) — GPLv3

The reason custom code can run at all. It established the Gecko loader, the REL
entry-point convention (`_prolog`/`_epilog`/`_unresolved`) and the
`seq_data`-hooking technique that every mod in this scene uses, `bleck` included.

Its loader codes are what a built disc carries at `0x80001800`. They are **not
committed here** — supply them via `BLECK_GECKO_DIR`. Its title-screen example
is also the only known-working demonstration of the game's text-drawing API, and
our on-screen mod banner follows its call sequence.

⚠️ It re-bundles the MIT headers under its own repo-wide GPLv3. Take headers
from `spm-headers` directly, never from here.

### [`SeekyCt/spm-decomp`](https://github.com/SeekyCt/spm-decomp) — no licence stated

A work-in-progress 1:1 decompilation, deliberately partial. We read
`src/evtmgr_cmd.c` as **documentation** to settle how the `evt` VM decodes its
operands — which is why `bleck` encodes `SET`/`SETI`/`SETF` correctly instead of
by guesswork.

⚠️ **It carries no licence file or statement**, so nothing from it is vendored
or copied, and nothing will be without one. Any future use reads a clone you
supply, the same way symbol lists already work.

### [`SeekyCt/pyelf2rel`](https://github.com/SeekyCt/pyelf2rel)

Converts our compiled ELF into a REL. A runtime dependency, used as published.

### [`skawo/Super-Paper-Mario-Level-Editor-Randomizer`](https://github.com/skawo/Super-Paper-Mario-Level-Editor-Randomizer)

The established tool for setup files and enemy data. Its existence is why
`bleck` checked what was already solved before building anything in that space —
and skawo's correction that setup entries are *not* a fixed 112 bytes is what
sent us to measure all 227 files rather than trust a widely-repeated number.

### Also consulted

- [`SeekyCt/spm-docs`](https://github.com/SeekyCt/spm-docs) — RE notes; its
  `SETUPOBJ_FORMAT_VERSION` constant was independently confirmed on disc
- [`SeekyCt/chainrel`](https://github.com/SeekyCt/chainrel) and
  [`evt-disassembler`](https://github.com/SeekyCt/evt-disassembler) — examined,
  not used
- [TCRF](https://tcrf.net/) — notes on the setup-file format

### Deliberately not used

`Flipside-Mod-Manager` carries **no licence at all** while its loader is plainly
derivative of GPLv3 `spm-rel-loader`. `bleck` copies nothing from it. Where we
needed the same facts, they came from upstream or from measuring the disc —
addresses are facts, and facts are not copyrightable.

### External tools

Invoked, never bundled: [Wiimms ISO Tool](https://wit.wiimm.de/) (`wit`),
[Wiimms SZS Toolset](https://szs.wiimm.de/) (`wstrt`),
[Dolphin](https://dolphin-emu.org/), [devkitPPC](https://devkitpro.org/), and
[`dolphin-memory-engine`](https://github.com/aldelaro5/Dolphin-memory-engine),
which makes unattended in-game testing possible.

---

## What is not included

**No game data.** No disc image, no ROM, no extracted assets, no symbol list, no
loader codes. Bring your own legally-obtained copy of the game. `work/` is
gitignored precisely so none of it can be committed by accident.

The one exception is [`bleck/backends/mapcatalog.json`](bleck/backends/mapcatalog.json):
468 map names and their ids, read out of a running game. These are identifiers
rather than content — the same names already visible as filenames on any disc.

---

## Licence

⚠️ **`bleck` itself is currently unlicensed**, which means all rights reserved
by default. This is an open question, not a decision — see
[`docs/decision-log.md`](docs/decision-log.md).

Until it is settled, treat this repository as source to read rather than to
redistribute. Everything above about *upstream* licences applies regardless, and
is the part that must not be got wrong.
