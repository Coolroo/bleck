# Mods — Design

✅ **Implemented.** See D22 in [`decision-log.md`](./decision-log.md).

How `bleck` represents a mod, and how a mod becomes a bootable disc.

---

## The problem this solves

The obvious approach — extract the disc, edit files in place, rebuild — is a
trap:

- **No baseline.** Once you edit `extracted/eu0/`, you no longer have a pristine
  copy to diff against. "What did I actually change?" becomes unanswerable, and
  our main verification tool (byte-exact comparison) stops working.
- **Nothing is shareable.** A mod becomes "my 400 MB directory", not a set of
  changes.
- **Mistakes are unrecoverable** without re-extracting from the ISO.

So: **the extracted base is immutable.** `bleck` must refuse to write into it.
A mod is a small overlay of *only what changed*, kept separately and applied at
build time.

---

## Concepts

**Base** — a pristine extracted disc (`extracted/eu0`). Read-only, never
modified, not committed to git.

**Mod** — a named directory holding a manifest and an overlay tree containing
only the files that differ from the base. Small enough to commit and share.

**Build** — base + mod → ISO. Non-destructive; both inputs are untouched.

```
base (read-only)  ─┐
                   ├─►  merge  ─►  staging  ─►  ISO
mod overlay       ─┘
```

---

## Layout

```
mods/
  hard-mode/
    mod.json                            manifest
    overlay/                            mirrors the *extract* root
      files/lyt/title.bin.uk            whole-file replacement
      files/map/
        aa1_01.bin/                     a DIRECTORY where the base has a FILE
          arc/timg/mario.tpl            → merged *into* the archive
      sys/main.dol                      the DOL is reachable too
```

The overlay mirrors the extract root, not the data partition, so `sys/` is
addressable. It is named `overlay/` rather than `files/` because the disc's own
data partition is `files/` — `overlay/files/...` reads correctly where
`files/files/...` would not. Commands accept a bare `lyt/title.bin.uk` and add
the `files/` prefix when that resolves.

### `mod.json`

```json
{
  "schema": 1,
  "name": "hard-mode",
  "version": "0.1.0",
  "description": "Rebalanced enemy damage",
  "author": "coolroo",
  "base": "eu0",
  "created": "2026-07-26"
}
```

`base` is load-bearing: a mod built against `eu0` must not be silently applied to
`us0`, where addresses and even the file list differ (`eu0` has `map/go1_03.bin`
and `rel/relD.bin`, which `us0` lacks). Building against a mismatched base is an
error unless explicitly forced.

---

## Overlay resolution

Walking the mod's `files/` tree, for each entry:

| Mod entry | Base entry | Result |
|---|---|---|
| file | file | **replace** the base file |
| file | *(absent)* | **add** a new file |
| **directory** | **file** | **merge into the archive** (see below) |
| directory | directory | recurse |

Everything in the base with no mod counterpart passes through untouched.

### Archive-aware merging — the important part

SPM's assets live inside LZ77+U8 archives. Without help, changing one texture
means shipping a whole 240 KB repacked archive as a binary blob — opaque in
review, and it silently freezes every *other* file in that archive at whatever
version you extracted.

So when the mod has a **directory** where the base has a **file**, and that file
is a recognised archive, `bleck` unpacks the base archive, replaces only the
named members, and repacks:

```
mods/my-mod/files/lyt/title.bin.uk/arc/timg/mario.tpl
```

means "in `lyt/title.bin.uk`, replace `arc/timg/mario.tpl`; leave the other 30
members alone." The mod stores 18 KB, not 240 KB, and the diff is legible.

Repacking preserves original node order (D17), so unchanged members stay
byte-identical and a rebuilt archive differs only where intended.

To replace an archive wholesale instead, put a *file* at that path.

---

## Dependencies and layering

A mod may depend on other mods. Layers apply in order, each overriding what came
before:

```
base game  ←  dependencies (transitively)  ←  this mod
```

Later wins. A mod always applies *after* everything it depends on, so it can
knowingly override its dependencies' files — that is not a conflict, it is the
whole point of depending on something.

```json
{
  "name": "hard-mode-plus",
  "base": "eu0",
  "dependencies": [
    { "name": "hard-mode", "version": ">=2.0" },
    { "name": "shared-textures" }
  ]
}
```

### Resolution — producing one concrete install order

Dependencies form a DAG, and the same mod can be reached by several paths. The
resolver flattens it into a **single ordered list where each mod appears exactly
once**:

> **Depth-first post-order traversal in declaration order, keeping the first
> occurrence of each mod.**

Post-order is what guarantees the invariant: a mod is emitted only after
everything it depends on. Declaration order makes it deterministic — the same
graph always linearises the same way, so a build is reproducible.

**Worked diamond.** `M` depends on `[A, B]`; both `A` and `B` depend on `C`:

```
        M
       / \
      A   B
       \ /
        C
```

Traversal: descend `A` → descend `C` → emit `C` → emit `A` → descend `B` →
`C` already seen, skip → emit `B` → emit `M`.

Result: **`C, A, B, M`** — `C` once, before both dependents.

**Cycles are an error**, reported with the full path (`A → B → C → A`) rather
than a bare "cycle detected".

**Missing or version-mismatched dependencies are errors**, naming who required
what.

The resolved chain is data worth showing, not just an implementation detail:

```
$ bleck mod chain hard-mode-plus
1. shared-textures  0.3.0   (required by hard-mode-plus)
2. hard-mode        2.1.0   (required by hard-mode-plus)
3. hard-mode-plus   0.1.0   (target)
```

---

## Conflict detection

Two mods in a chain, **neither depending on the other**, both touching the same
thing. If one depends on the other, the later one wins by design and nothing is
reported.

Conflicts are checked at the finest granularity available, so the common cases
resolve cleanly.

### Tier 1 — archive members

Most "same file" collisions are not real. Two mods editing
`lyt/title.bin.uk` are only in conflict if they edit the **same member**:

```
mod-a:  lyt/title.bin.uk/arc/timg/mario.tpl
mod-b:  lyt/title.bin.uk/arc/timg/koopa.tpl     → no conflict, merges cleanly
```

Archive-aware overlays (above) make this the normal case rather than the
exception.

### Tier 2 — three-way content merge

When two independent mods change the *same* file, `bleck` does a git-style
three-way merge using **the base game's version as the common ancestor** — which
we always have, because the base is immutable.

**Text files** (`.txt`, `.json`, `.xml`) merge line by line. Non-overlapping
hunks combine; overlapping hunks conflict and are reported with the offending
region from each side.

**Binary files** — the same algorithm at byte granularity: compute each mod's
changed byte ranges against the base, and merge if those ranges do not overlap.

⚠️ **Non-overlapping binary edits are not automatically safe, and `bleck` will
say so.** Two mods editing different fields of a struct merge fine. Two mods each
appending an entry to the same table produce a file that is byte-wise merged and
semantically corrupt. Byte-range merging cannot tell these apart.

So binary auto-merge is **off by default**: independent mods editing the same
binary file is reported as a conflict, with the byte-range analysis shown so the
user can judge. `--merge-binary` opts in per build, and the result is flagged in
the output. Better a false conflict the user overrides than a corrupt disc that
boots and misbehaves.

### Tier 3 — hard overrides

A mod may claim a file exclusively. Any other mod touching it is an error, no
merge attempted:

```json
"exclusive": [
  "rel/rel.bin",
  "map/aa1_01.bin"
]
```

Intended for files where any concurrent edit is unsound — compiled code, or
formats with internal offsets where two independent edits cannot coexist however
disjoint they look.

Claiming an archive path exclusively claims **every member**, which is the point:
`rel/rel.bin` is one compiled artifact and cannot be meaningfully co-edited.

### Reporting

Conflicts are collected and reported together, not one per run:

```
$ bleck mod build hard-mode-plus
error: 2 conflicts

  map/aa1_01.bin/dvd/setup/aa1_01.dat
    hard-mode        bytes 0x120-0x14c
    shared-textures  bytes 0x134-0x160        ← overlapping

  rel/rel.bin
    claimed exclusively by hard-mode
    also modified by shared-textures
```

---

## Commands

```
bleck mod new <name>                  create and register a mod
bleck mod list                        registered mods, and what each overrides
bleck mod vendor <name> <disc-path>   copy a file from the base into the mod
bleck mod status <name>               what this mod overrides, vs base
bleck mod chain <name>                resolved install order, in order
bleck mod check <name>                resolve + detect conflicts; writes nothing
bleck mod build <name> [out.iso]      base + chain + mod -> ISO
```

`check` is `build` without the 4.7 GB write — resolution and conflict detection
only. On this hardware that distinction matters; it should be what you run while
iterating.

`vendor` is how a mod gets started, and it is the piece that makes this pleasant.
Rather than hunting through the base and copying by hand:

```
$ bleck mod vendor my-mod lyt/title.bin.uk/arc/timg/mario.tpl
vendored -> mods/my-mod/files/lyt/title.bin.uk/arc/timg/mario.tpl  (18,880 bytes)
```

It resolves the path *through* archive boundaries, unpacks as needed, and drops
the file where the overlay expects it. You then edit it in place. The base is
never touched.

---

## Configuration

All paths are environment-overridable, declared in `bleck/common/env.py` per the
project rule:

| Variable | Default | Meaning |
|---|---|---|
| `BLECK_MODS_DIR` | `mods` | Where mods live |
| `BLECK_BASE_DIR` | `extracted/eu0` | The pristine extracted base |
| `BLECK_BUILD_DIR` | `build` | Where staging and output ISOs go |
| `BLECK_EXTRACT_ROOT` | `extracted` | Where `bleck extract` writes *(exists)* |

Defaults point at the repo layout, so a dev checkout works with no configuration.

---

## Build pipeline

1. **Validate** — manifest parses; `base` matches the configured base; every
   overlay path resolves.
2. **Stage** — materialise the base into `build/<name>/`. Copying 400 MB per
   build is wasteful, so prefer **hardlinks** for untouched files, falling back
   to copies across filesystems. Only merged archives are written fresh.
3. **Merge** — apply the overlay per the rules above.
4. **Emit** — `wit COPY --align-files` (mandatory; omitting it fails subtly).

Staging is disposable and gitignored. The base is opened read-only throughout.

---

## Known hazards

⚠️ **Setup files exist in two byte-identical copies** (D13): standalone in
`setup/` *and* embedded inside some map archives. We do not yet know which the
game reads. A mod that edits one copy may appear to do nothing.

Until that is settled, `bleck mod build` should **warn** when an overlay touches
a path that has a known duplicate, and name the other copy. Silently editing one
of two copies is exactly the bug that wastes an afternoon.

⚠️ **Compression is not bit-exact** (D16). A rebuilt archive is ~0.25% larger
than Nintendo's and differs in token stream. Believed fine — untested against a
running game, which is what the current end-to-end work is for. `--store` gives
an instant all-literals encode for fast iteration at ~1.125× size.

⚠️ **Mods are base-specific.** `eu0` ⊃ `us0`, so a mod referencing
`map/go1_03.bin` cannot apply to a US disc at all.

---

## Deliberately out of scope for now

- **Distribution format.** A zipped `mods/<name>/` is adequate; a dedicated
  package format can wait for a reason.
- **A registry or remote resolution.** Dependencies resolve against
  `BLECK_MODS_DIR` only. Fetching mods from anywhere is a separate concern.
- **Semver ranges beyond `>=`, `<=`, `==`.** Full range grammar can wait until
  something needs it.
- **Patching the game's REL.** Code mods go through `/mod/mod.rel` and the Gecko
  loader, a separate pipeline from asset overlays. Likely a sibling `bleck mod
  rel` verb once that workflow is exercised.

---

## Open questions

1. Should `mods/` be committed? Overlays are small and reviewable, which argues
   yes — but a mod containing extracted game assets is redistribution of
   copyrighted data. Suggest committing manifests while gitignoring `files/`,
   with an opt-in for original content.
2. Should `bleck mod build` emit an ISO by default, or a Riivolution-ready
   directory? Riivolution avoids a 4.7 GB write per iteration, which matters a
   lot on this hardware.
3. Does `vendor` need a reverse (`unvendor`) to drop a file back to base
   behaviour, or is deleting the file from the overlay obvious enough?
4. Should binary three-way merge be opt-in (`--merge-binary`, as proposed) or
   opt-out? Proposed opt-in because a byte-wise-clean merge can still be
   semantically corrupt, and a corrupt disc that boots is worse than a conflict
   the user resolves deliberately.
5. Should a mod be able to *delete* a base file, and if so how is that spelled?
   A `"remove": [...]` list in the manifest is the obvious answer, since an
   overlay tree can express "replace" and "add" but not "absent".
