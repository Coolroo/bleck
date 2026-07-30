# Running a mod on hardware — Riivolution output

**Status: built** (D86). `bleck mod build <mod> --output riivolution` writes a
patch instead of a disc image.

⛔ **No part of this has ever run on a Wii.** Every result on record — the boot,
the isolating negative, the loader travelling in the patched DOL — is Dolphin's
implementation of Riivolution. The XML is written against the documented format
and Dolphin's parser agrees with it, which is not the same thing as an SD card in
a console. Treat hardware as 🔶 until somebody boots one.

An image costs a 4.3 GB write per iteration. A Riivolution patch costs the size
of what changed — for a code-only mod, the REL plus the patched DOL. Measured on
`scripttest`: **5.3 MB, 3.2 s**, against minutes for a `wit` rebuild.

```
work/build/<mod>-riivolution/
  riivolution/<mod>.xml        the patch definition
  <mod>/files/mod/mod.rel      only what differs from the base
  <mod>/sys/main.dol
  <mod>.json                   Dolphin's descriptor; ignored on hardware
```

Copy the contents of that directory to the root of an SD card and the layout is
the one Riivolution expects. `external` paths are absolute from the SD root, so
nothing depends on where the XML sits.

---

## The schema, and the two ways to get it silently wrong

Read against Dolphin's `RiivolutionParser.cpp` / `RiivolutionPatcher.cpp`, not
guessed. Both traps below produce a patch that parses, applies nothing, and
reports no error.

### ⚠️ `default="1"` on the option

`<option default>` is a **1-based choice index**, and `0` means "off":

```cpp
const u32 selected = option.m_selected_choice;
if (selected == 0 || selected > option.m_choices.size())
  continue;
```

A patch is only reachable through `<options>/<section>/<option>/<choice>`;
`<patch>` on its own is inert. An option without `default` defaults to 0.

### ⚠️ `disc="main.dol"` — no leading slash

```cpp
if (!file.m_disc.empty() && file.m_disc[0] == '/')
  // ... look the path up in the FST
else if (dol_node && Common::CaseInsensitiveEquals(file.m_disc, "main.dol"))
  // Special case: If the filename is "main.dol", we want to patch the main executable.
```

The executable has no FST node. `disc="/main.dol"` therefore matches nothing —
and with `create="true"` it would *add* a file called `main.dol` to the disc
root, which the game never reads.

### The rest, as `bleck` uses it

| Element | Attribute | What `bleck` writes |
|---|---|---|
| `wiidisc` | `version` | `1`. Dolphin rejects anything else outright. |
| `id` | `game` | The 3-character title code from `sys/boot.bin`, e.g. `R8P`. Prefix-matched against the disc's 6-character id. |
| `id/region` | `type` | The region letter, e.g. `P`. |
| `option` | `default` | `1` — see above. |
| `file` | `disc` | `/`-rooted FST path, or bare `main.dol`. |
| `file` | `external` | Absolute from the SD root: `/<mod>/<staged path>`. |
| `file` | `resize` | `true` (the default). The patched DOL is larger than stock. |
| `file` | `create` | `true` only for files the base does not have, i.e. `/mod/mod.rel`. |

⚠️ **`external` must be posix.** Dolphin refuses any external path containing a
backslash on Windows, because Riivolution treats `\` as an ordinary filename
character and that cannot be replicated.

---

## The loader travels in the DOL, so no Gecko code is needed

This is the part that makes the whole route work. `code-mods.md` said Riivolution
"only puts the *file* on the disc — the Gecko code is what actually executes it."
That is still true, and `bleck` already solved it for images: `wstrt patch
--add-sect` writes the code handler plus the loader codes into a new TEXT section
of `main.dol` and redirects the game into it (`bleck/backends/gecko.py`).

✅ Verified in Dolphin **with the emulator's own cheat file moved aside**, which
is the only version of this claim worth making — see D86. With
`R8PP01.ini` gone, the Riivolution patch alone runs the mod; delete the one
`<file disc="main.dol">` element and the same patch delivers the module and it
never executes. **No `.gct`, no cheat manager, no `R8PP01.ini`.**

⚠️ **This host has that INI in place and enabled.** A run that shows the mod
working proves nothing about the DOL until the file is moved aside.

`bleck` embeds the loader for every output kind that produces an artifact
(`OutputKind.embeds_loader`), so the Riivolution and image paths carry the same
executable.

---

## The REL filename: `mod.rel`, deliberately

The snapshot notes that `relloader3` looks for `./mod/<region>.rel` (e.g.
`eu0.rel`) with `mod.rel` as a legacy fallback. `bleck` writes `mod.rel`
(`REL_DISC_PATH` in `bleck/mods/manifest/codespec.py`), and that is correct as
things stand:

- ✅ The loader actually in use here is `spm-rel-loader`'s pre-assembled eu0
  codelist. Decoding `work/gecko/loader.eu0.txt` back to bytes shows the literal
  ASCII `./mod/mod.rel`, `ERROR: mod.rel was not found` and
  `ERROR: failed to load mod.rel`. It opens that path and no other.
- ✅ `mod.rel` is also `relloader3`'s documented fallback, so the same patch works
  under either loader.

⛔ **Do not rename it to `eu0.rel` speculatively.** That would break the loader
that is proven to work here in exchange for a marginal preference of one that has
never been run against this toolkit. If `relloader3` is adopted, the region name
becomes worth emitting *alongside* `mod.rel`, not instead of it.

---

## Testing it without an SD card

Dolphin has had Riivolution support since 5.0-13603, and takes a whole run from
the command line via a **game-mod descriptor**:

```
Dolphin.exe -b -e work/build/<mod>-riivolution/<mod>.json
```

`bleck` writes that descriptor. Its `base-file` points at the extracted base's
`sys/main.dol`, which Dolphin opens as a whole disc (`DirectoryBlobReader`), so
**a Riivolution run needs no disc image to exist at all.**
`--base-image path/to/spm.wbfs` names a retail image instead — the
better-trodden route if you have one, given the 🔶 below.

`scripts/ingame.py --riivolution` builds a patch and boots it through the same
unattended memory-reading rig as an image:

```bash
uv run python scripts/ingame.py speedrun --riivolution --watch-gw 30
```

The descriptor also restates the choice explicitly, alongside the XML's
`default="1"`:

```json
"options": [{ "section-name": "bleck", "option-id": "scripttest", "choice": 1 }]
```

---

### 🔶 An inactive patch does not boot

A descriptor whose only option is `default="0"` — no patches active — did not get
past the logo. `Boot.cpp`'s `AddRiivolutionPatches` returns early on an empty
list, leaving whatever `GenerateFromFile(base_file)` made of a `.dol` path.
Mechanism untested; `--base-image` sidesteps it.

## What Riivolution cannot do

`plan()` reports these rather than dropping them, and `bleck mod build` prints
them as warnings:

- **Changes outside `files/` and the executable.** `sys/boot.bin`, `sys/fst.bin`,
  `sys/bi2.bin`, the ticket and TMD have no `<file>` patch that reaches them.
  Nothing `bleck` does today touches them, but a future feature might.
- **Deleting a base file.** A mod's `"remove"` list cannot be expressed; the disc
  file stays. Build an image for that.

---

## Adding another delivery mechanism

Output kinds are a table, not a branch: `bleck/mods/build/outputs.py` holds one
`OutputKind` per way a build can leave the toolkit (`iso`, `wbfs`, `rvz`,
`riivolution`, `none`). Each carries its own writer, its default destination,
whether it produces an artifact, and whether the loader is embedded first.

Adding a route — a `.gct` beside an image, a NAND-installable channel, a
save-exploit payload — means adding a value there and nothing else. `bleck mod
build --output` builds its own choice list and help text from that table, so the
two cannot drift.
