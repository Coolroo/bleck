# Where this is going

**Living.** The end state `bleck` is being built toward, and the decisions that
follow from it. Not a promise of dates — a statement of what the architecture
has to survive.

---

## The goal

**A full editor for Super Paper Mario mods**, including a visual map editor in
the spirit of Hammer: open a map, see it, move things, build, play.

The CLI is not the product. It is the first front-end onto a library, and the
one that happens to be usable while the library is still being built.

---

## What that forces, starting now

These are the decisions the goal actually constrains. Everything else is detail.

### 1. Edits are data, not baked bytes

⚠️ **The load-bearing one.**

A mod could ship a modified `setup/he1_01.dat` as a binary blob. It would work
today, and it would be a dead end: a blob cannot be undone, reviewed, re-applied
to a corrected base, or *opened in an editor*.

So a mod declares **intent** — "slot 3 is a Goomba at (100, 0, 0)" — and `bleck`
produces the bytes at build time. That gives, for free:

| Property | Because |
|---|---|
| Legible diffs | The change is a line of JSON, not 11 KB of binary |
| Undo / redo | The document is an ordered list of edits |
| Re-application | Fixing a decode bug re-derives every mod correctly |
| A GUI | The editor mutates the same document the CLI writes |

This is the same shape `code` already has: declare a script, `bleck` generates
the module. Placement should not be different in kind.

### 2. The core is a library; front-ends are peers

`bleck/` is the library, `bleck/cli/` is one consumer. A GUI must not need to
shell out to the CLI or re-implement anything.

Practically: no business logic in command modules, no `print` in the library, no
`sys.exit`. Commands parse arguments, call the library, and format the result.

### 3. Everything the editor shows needs a queryable model

An editor is mostly *presentation of a model*. The model has to exist first, in
named types, independent of how it is displayed.

Already built: maps and their chapters (`backends/maps.py`), NPC templates and
tribes (`npccatalog.json`), script builtins (`script/catalog.json`), placements
(`formats/setup.py`).

⚠️ These catalogs are the editor's **palettes** — the drop-downs of "what can I
place here". That is why they carry names and not just ids.

### 4. Round-trip fidelity is not optional

Every format `bleck` touches must read → write byte-identically when nothing was
asked to change. An editor that silently rewrites the 70 undocumented bytes of a
setup entry is an editor that corrupts maps it does not understand.

Held today by LZ77, U8 (383/383 archives) and setup files (227/227).

### 5. The base stays immutable

Already true, and it is what makes an editor safe: the pristine disc is never
written to, so "revert" is always available and "what did I change?" is always
answerable.

---

## What is already the right shape

Worth stating so it does not get re-litigated:

- **A mod is a document.** `mod.json` plus an overlay is exactly a save file.
- **Non-destructive layering.** Dependencies, conflict detection and overlays
  already model "several people's changes composed".
- **Archive-aware merging.** Editing one texture in an archive already means
  shipping one texture, not the archive.
- **Unattended boot with map navigation** (D52). This is the seed of **preview**:
  `bleck` can already build a disc and drive the game to an arbitrary map with no
  controller input. "Play this map" is a button away from working.

---

## What has to change, eventually

| Now | Needed for an editor |
|---|---|
| Placement edits go through the CLI only | A document model with undo, shared by both front-ends |
| `map.dat` is opaque | Geometry must be readable to draw a map at all |
| Textures are files | An asset browser needs thumbnails and references |
| Build takes ~2 minutes | Incremental builds, or preview without a full disc |
| One code mod per disc | An editor cannot tell users "only one mod" |

⛔ **`map.dat` is the real wall.** It is 300–600 KB per map and undecoded, and
nothing draws a map without it. That is the single largest piece of work between
here and a visual editor, and it is deliberately deferred until the data-side
tooling is worth building a view onto.

---

## Non-goals

- **Not a decompilation.** `spm-decomp` is that. `bleck` builds mods, and treats
  the decomp as a documentation source (D54).
- **Not a general Wii toolkit.** Being SPM-specific is what lets the model be
  concrete — "enemy", "map", "chapter" rather than "binary blob".
- **Not a replacement for existing tools.** skawo's editor already does setup
  files well. Overlap is fine; pretending it does not exist is not.

---

## Order of work

Roughly, and each stage is useful on its own — nothing here is a
build-it-all-then-ship:

1. **Data-side tooling** *(here now)* — read and write every format a mod
   touches, declaratively, with names.
2. **A document model** — edits as an ordered, undoable list; the manifest as
   its serialisation.
3. **Preview** — build and boot to the map being edited. Most of this exists.
4. **A view** — needs `map.dat`, and is gated on it.

See [`roadmap.md`](./roadmap.md) for what is actually next.

---

## Priority as of 2026-07-27

**Everything is measured against "does this get us to the base app".**

Licensing, distribution and polish are explicitly deferred: nothing is shared
until there is an application worth sharing. That is a decision, not an
oversight — see `handoff.md`.

What that promotes:

- **A programmatic API** for reading and editing a mod, not just a CLI. A GUI
  cannot shell out to `bleck mod build` for every keystroke.
- **Editing surfaces**, in the order they are already understood: enemy
  placement (format fully decoded), then whatever the map archive holds.
- **Round-tripping**, because an editor that cannot re-open what it wrote is a
  converter.

What it demotes:

- Licensing, packaging, release engineering
- Breadth of game-version support — `eu0` remains the only anchor
- Anything whose value is "someone else could use this"
