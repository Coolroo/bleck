# bleck

A modding toolkit for **Super Paper Mario** (Wii, 2007).

Extract a disc, layer mods onto it, compile scripts and C into game code, and
rebuild a bootable image:

```bash
uv run bleck mod build my-mod work/out/my-mod.wbfs --launch
```

Mods can ship assets, or behaviour. The scripting language compiles to the
game's own bytecode VM, so there is no interpreter to ship:

```json
"code": { "script": "scripts/main.evt", "maps": { "mac_01": "on_arrive" } }
```

- **Using it:** [`docs-site/`](docs-site/)
- **How it works, and why:** [`docs/`](docs/)

## Credits

`bleck` stands on other people's reverse-engineering. The hard parts — what the
opcodes mean, where the functions live, how to get code running at all — were
worked out and published by these projects, not by us.

| Project | What we get from it |
|---|---|
| [`SeekyCt/spm-headers`](https://github.com/SeekyCt/spm-headers) | Symbol lists, struct layouts, and the 443 script builtins |
| [`SeekyCt/spm-rel-loader`](https://github.com/SeekyCt/spm-rel-loader) | The Gecko loader, and the hooking technique every SPM mod uses |
| [`SeekyCt/spm-decomp`](https://github.com/SeekyCt/spm-decomp) | Decompiled source that settled how the script VM works |
| [`SeekyCt/pyelf2rel`](https://github.com/SeekyCt/pyelf2rel) | ELF → REL conversion |
| [`SeekyCt/spm-docs`](https://github.com/SeekyCt/spm-docs) | Reverse-engineering notes |
| [`skawo`'s level editor](https://github.com/skawo/Super-Paper-Mario-Level-Editor-Randomizer) | The prior art on setup files and enemy data |

External tools, invoked but never bundled: [Wiimms ISO
Tool](https://wit.wiimm.de/), [Wiimms SZS Toolset](https://szs.wiimm.de/),
[Dolphin](https://dolphin-emu.org/), [devkitPPC](https://devkitpro.org/), and
[`dolphin-memory-engine`](https://github.com/aldelaro5/Dolphin-memory-engine).

Upstream licences are respected and recorded per-project in
[`docs/decision-log.md`](docs/decision-log.md) (D54).

## No game data here

No disc image, no assets, no symbol lists, no loader codes. Bring your own
legally-obtained copy — `work/` is gitignored so none of it lands here by
accident.

## Licence

`bleck` itself is not yet licensed. Until it is, treat this as source to read
rather than redistribute.
