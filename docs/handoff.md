# Handoff — start here on a new machine

Last updated 2026-07-31, at **D238**. This is the orientation doc: what exists,
what it can do, what has been *seen to work* versus what only tests believe, and
where the open threads are. Everything else is a link.

| | |
|---|---|
| [`decision-log.md`](./decision-log.md) | **why** every choice was made. Chronological, append-only, D1–D238 |
| [`roadmap.md`](./roadmap.md) | what to build next and what blocks it |
| [`model-format.md`](./model-format.md) | **the character model format**, decoded — structure, and what is still unread |
| [`disc-layout.md`](./disc-layout.md) | observed facts about the disc |
| [`function-behaviour.md`](./function-behaviour.md) | what game functions do, measured by tracing them |
| [`scripting.md`](./scripting.md) | the scripting language and its limits |
| [`hook-points.md`](./hook-points.md) | **when custom code can safely run.** Read before writing a hook |
| [`code-mods.md`](./code-mods.md) | compiled PowerPC code mods |
| [`plan-dimentio.md`](./plan-dimentio.md) | the asset viewer |
| [`../docs-site/`](../docs-site/) | user-facing docs, published to GitHub Pages |

`bleck` is **MIT** (D132), and the rule at the top of the project instructions
about keeping derived code MIT-compatible is load-bearing — `spm-rel-loader` and
`spm-headers/mod/` are GPLv3.

---

## What this can do today

Two programs. `bleck` is a Python CLI that reads and rebuilds the user's own
disc; `dimentio/` is a Rust/eframe window that displays what `bleck` exported.

### Four kinds of asset come off the disc

```powershell
uv run bleck texture export --out work/export   # 21,780 images, PNG
uv run bleck model   export --out work/export   # 864 .glb + models.json
uv run bleck effect  export --out work/export   # 139 effects + effects.json
uv run bleck sound   export --out work/export   # 135 streams, WAV
uv run cargo run --manifest-path dimentio/Cargo.toml -- work/export
```

⚠️ **`bleck model export` still defaults to `--out work/models`** while the
other three default to `work/export` (D233). Pass `--out work/export`
explicitly, every time — pointing all four at one root is the intended use, and
this default predates the layout change.

Exports mirror the disc, one subtree per kind, with the four manifests at the
root (D233). Dimentio reads the manifests, never the directory listing:

```
work/export/
  textures.json  models.json  sounds.json  effects.json
  textures/files/eff/effdata.tpl/0.png
  textures/files/map/aa1_01.bin/dvd/bg/aa1_01_00.tpl/0.png
  models/files/a/p_wii_mario.glb
  sounds/files/sound/sys_title1_44k_lp.wav
```

⚠️ **A TPL becomes a directory; a model or stream does not.** One TPL holds
several images, so the file becomes a folder and the leaf is the image index.
Path components are percent-escaped, `%` first, which is what makes the mapping
injective and stops two assets landing on one file.

### Dimentio has four tabs

| tab | state |
|---|---|
| **Textures** | ✅ browsable, searchable, filterable by GameCube format |
| **Models** | ✅ geometry, UVs, per-shape primitives, textures where the binding is known; animation plays with a clip picker, scrub bar and per-shape hiding (D222, D235, D237) |
| **Effects** | 🔶 structure, part durations, transform rows, a scrubber and a viewport. ⛔ **no part→image link** (D210, D218, D219, D225) |
| **Sounds** | 🔶 135 tracks, waveform, seek, volume, real playback through `rodio` (D227). ⛔ **nobody has heard it** |

Every asset name is copyable from any tab (D231). The model viewport is a
**software rasteriser**, deliberately: this machine cannot capture its own
interactive desktop, so a GPU viewport could not be validated at all, whereas a
`Vec<u8>` is something `cargo test` can assert on (D213).

### Character models are fully readable

This is the session's headline. The format in `files/a/` went from "not decoded"
to a reference you can open: [`model-format.md`](./model-format.md).

- ✅ Positions and normals are **F32 XYZ at stride 12, indexed by `u16`** — read
  off the game's own draw code, not pattern-matched (D207).
- ✅ **Per-shape rebasing** took median coverage from 13.7% to **100%**, models
  at 95%+ from 132 to 801, animated models from 12 to 202 (D224). Anything in
  `docs/` or a docstring that still says "13.6%" or "fragment" predates it.
- ✅ UVs are indexed **per corner** via slot 7 (D234); faces are triangulated by
  **ear clipping**, because a fan is wrong for 14% of the disc's quads (D223).
- ⛔ Animation is **per-vertex morphing, not skeletal** (D217). Two sessions
  went into hunting a track→joint mapping that does not exist.
- ✅ One glTF **primitive per shape** (D237), morph targets **sparse where
  sparse is smaller** (D238) — all 3,079 clips now export, none dropped.

### A mod can change the game

Unchanged this session, and still the core of the toolkit.

| | Declared as | Proven by |
|---|---|---|
| Run its own script or C, on a loop, on arrival at a map, or on a button combo | `code.script`, `code.maps`, `code.combos` | D43, D46, D51, D77 |
| Make a **vanilla** script call into it | `code.patches` | D89, D90, D92 |
| Replace a **game C function** by name, or run **before**/**after** it | `code.hooks` | D94, D95, D97 |
| **Trace** a game function without breaking it | a pattern, not a manifest key | D96 |
| Change what a map **places** — enemies, coins | `setup`, `tables` | D122–D131 |
| Spawn an **effect**, including the Chaos Heart | `effdrv` entry `0x80094E44` | D171–D173 |
| Edit a texture **declaratively**, no baked bytes | `tables/textures.csv` | D187, D193 |

⛔ **Nothing has ever run on a real Wii.** Riivolution output exists (D86) and
Dolphin runs it; hardware is untested, and so is Dolphin's cache model against a
real 750 (D94, D96).

---

## ⚠️ Verified by a person, versus verified only by tests

**Read this before repeating a claim.** The suite is large and mutation-tested,
and it still cannot see a window, hear a speaker, or open a `.glb`.

### ✅ A human confirmed these

| | |
|---|---|
| **A `bleck`-built disc boots and renders modified textures** | D25 (Linux), D36 (Windows), with a two-mod dependency chain |
| **`e_3D_manera_ruby` "renders correctly and looks like a ruby"** | D215, opened outside this repo |
| **`MOBJ_broken_heart` rendered its texture in Blender** | D215 addendum — mesh, UVs, embedded PNG and material |
| **The audio rate, against a supplied reference recording** | D232 — 371 MP3 frames give 8.90 s, so 193,816 samples are 21,777 Hz, exactly half the stated 44100. Confirmed by ear afterwards (D228 addendum) |
| **Model defects, reported from the window and each one real** | `e_genjin_b` bow-ties (D223), `e_2D_manera6` "small mimis on a big mimi" (D229), `e_bara_tib_p` bare (D234), "models rendering without materials" (D222), "Mesh file is missing" (D221), the flat export directory (D233) |
| **A third-party rip of Brobot as ground truth** | D236 — max Y matches to the hundredth, 100.83 both ways |
| **A button combination runs a script** | D77, played by hand |
| **Every disc names itself on screen** | D49 — `mod_loaded: <name>` on the title screen |

### ⛔ Nobody has confirmed these

| | |
|---|---|
| **Audio playback** | No test opens a device (D227). Whether sound comes out, at the right pitch, from the right offset, needs a person with ears |
| **The sparse-morph `.glb` path in a real viewer** | All 864 files are **structurally** validated against the specification (D238) and nobody has opened a sparse one in Blender. `--dense-morphs` exists for a reader that chokes |
| **Most of Dimentio's window** | Drag direction, panel proportions, the effects two-column split, the tooltip, the combo box, whether 219 un-virtualised thumbnails scroll comfortably (D213, D219, D225). The clipboard *write* cannot be verified in-process at all (D231) |
| **A patched *item* hook being entered** | Applying it works; using an item needs menu input, which cannot be injected (D48, D92) |
| **Anything on real hardware** | D86, D94, D96 |
| **The docs site in a browser** | `mkdocs build --strict` passing is not the same as looking right |
| **The banner on screen** since it gained the version line | D181 — the strings are confirmed in the module; the title screen is unreachable unattended |

⚠️ **"Works by eye, invisible to the rig" is a finding about the rig**, and so is
the reverse. Four rounds of asking "does it sound right" produced four
contradictory answers; **one reference file settled it in a single measurement**
(D232). Ask for an artifact, not an opinion.

---

## ⚠️ Standing traps

Four are new this session and all four have already misled someone.

1. ⚠️ **`work/reference/` is a third-party ground-truth instrument.** It holds
   supplied rips and recordings — Brobot as OBJ/DAE (D236), the pure-heart
   jingle as MP3 (D232). Tests use it and **skip when it is absent**, so a fresh
   clone passes without it. ⛔ It is third-party asset data: `work/` is
   git-ignored and stays that way.
2. ⚠️ **`--guess-textures` produces deliberately wrong art.** It paints image 0
   on every shape of a multi-shape model. Three candidate bindings are refuted
   (D229, D229 addendum) and the real one is unknown. It is opt-in, off by
   default, marked `texture_guessed` per model in the manifest, printed in
   capitals by the export, and shown in amber in the window. **Never cite a
   guessed export as evidence about the format.**
3. 🔶 **The 60 Hz clip rate is an inference, not a measurement.** Model key
   times are whole numbers and `effdata` already converts effect frames at 60
   (D219), so `FRAME_RATE = 60.0` applies the same inference to a second table
   (D235). The manifest carries both `frames` and `seconds`, so the raw number
   is never lost.
4. ⚠️ **`bleck model export` defaults to `--out work/models`**, the other three
   to `work/export` (D233). Harmless when one root meant one pile; now it splits
   the export in half and Dimentio finds no models.

And the older ones that keep biting:

- ⚠️ **Editing code by string replace or regex fails silently.** Use the `Edit`
  tool, which errors instead. This has corrupted `codespec.py` twice.
- ⚠️ **Capture output to a file; never filter raw stdout.** `tail` has hidden
  the one line naming a failure more than once.
- ⚠️ **This host runs the REL loader as a Dolphin cheat** (D86):
  `%APPDATA%\Dolphin Emulator\GameSettings\R8PP01.ini`, under `[Gecko_Enabled]`,
  with `EnableCheats = True`. A mod can therefore run **even when the DOL carries
  no loader**. Move that file aside before concluding an embedded loader worked.
- ⚠️ **An idle Dolphin window breaks `ingame.py`** — the memory reader may attach
  to it. `example-mods/nop` exists so a stock-behaviour disc can boot here.
- Generated C must be **pure ASCII**; console output too — Windows is cp1252 and
  an emoji raises `UnicodeEncodeError`.
- ⚠️ **`spm-headers` is not ground truth.** `evt_door.h`'s macro declares the
  wrong argc and its own comment was right; it cost two decision entries (D102).
- ⚠️ **Linux now needs `libasound2-dev`** to build `dimentio` (D227). CI does
  not build that crate, so nothing there breaks — a fresh Linux clone will.

---

## ⚠️ Every mod this repo names lives in `example-mods/`, not `mods/`

`bleck` reads `mods/` by default (`BLECK_MODS_DIR`), and that directory is
**git-ignored entirely** except its `README.md` (D175). It is scratch space for
*your* mods; write probes there freely and nothing needs cleaning up. The 31
worked examples this documentation cites are in `example-mods/`, so pass
`--mods-dir`, which every command accepts:

```powershell
uv run bleck mod check mr-l --mods-dir example-mods
uv run python scripts/ingame.py coin-tick --words 12   # the rig reads BLECK_MODS_DIR
```

Without it a bare `bleck mod check mr-l` reports **"no mod named 'mr-l'"**, which
reads as a broken repo rather than a wrong path (D147).

When a mod earns its keep — it demonstrates a concept, or produced a finding in
the decision log — **copy** it (do not move it) and drop the build output:

```powershell
Copy-Item -Recurse mods\my-mod example-mods\my-mod
Remove-Item -Recurse -Force example-mods\my-mod\overlay
uv run bleck mod check my-mod --mods-dir example-mods
```

⛔ 32 older probes were deleted in D148 once their findings were recorded. A
decision-log entry naming one is history, not a directory you can `cd` into.

---

## Setup

### Environment variables — copy `.env.example` to `.env`

`bleck` loads the nearest `.env` automatically from anywhere inside the checkout,
so there is nothing to source and nothing to export per shell. Only `BLECK_*`
names are read, and the real environment still wins — a one-off override works.
`.env` is gitignored; `.env.example` documents every setting.

```ini
# .env
BLECK_WIT=C:\Users\Wyatt\tools\wit\bin\wit.exe
BLECK_DOLPHIN=C:\Users\Wyatt\tools\dolphin\Dolphin.exe
BLECK_WSTRT=C:\Users\Wyatt\tools\szs\szs-v2.42a-r8989-cygwin64\bin\wstrt.exe
```

Backslashes are taken literally, so Windows paths need no escaping.

⚠️ **This exists because `$env:` does not persist between shells.** Two sessions
were lost to that, and both `wit` and Dolphin had to be found by searching the
filesystem afterwards. `setx` also works and survives reboots, but it is
per-machine rather than per-checkout and will not tell the next person which
variables matter — `.env.example` will.

⛔ **`os.environ` and `os.getenv` are rejected outside `bleck/common/env.py`**
(pylint `C9002`). Declare an `EnvVar`, add it to `DECLARED`, read it with
`env.text` / `env.flag` / `env.path`.

### Symbol lists — required for code mods, not shipped

Compiling a script or resolving a hook needs `spm.eu0.lst` from
[spm-headers](https://github.com/SeekyCt/spm-headers) (`linker/`). ✅ It lives at
`work/symbols/spm.eu0.lst`, which is where `BLECK_SYMBOLS_DIR` defaults, so no
variable is needed.

Anchor to **eu0**: `spm.eu0.lst` carries 1,111 entries, `kr0` only 456.

⚠️ **There is a much better source and it cannot be vendored.** `spm-decomp`'s
`config/EU0/symbols.txt` carries ~9,566 human-named symbols with sizes and types
— 11× the lst — and states **no licence at all** (D39, D54). Read a user-supplied
clone; ship nothing derived from it.

### Dolphin

✅ **`bleck` embeds the loader into the disc** (D44), verified with `R8PP01.ini`
moved aside entirely, so the two old traps no longer apply. It needs `wstrt`
(Wiimms SZS Toolset, a separate download from `wit`) and a codelist at
`work/gecko/loader.eu0.txt`; without them the build warns and continues.

The old path, for reference — both fail *invisibly* if misconfigured:

1. `User/GameSettings/R8PP01.ini` must list the Gecko loader under **both**
   `[Gecko]` **and** `[Gecko_Enabled]`. Listed once, it never runs.
2. `Config/Dolphin.ini` must have `EnableCheats = True` under `[Core]`. A fresh
   install has no `[Core]` section at all, since Dolphin only writes non-default
   settings.

The loader code itself is GPLv3 and lives in Dolphin's config, **not** here.

### Toolchain

devkitPPC is at `C:\devkitPro\devkitPPC` — GCC 16.1.0, target `powerpc-eabi`,
`--with-cpu=750`, newlib. Both `powerpc-eabi-g++` and `powerpc-eabi-gdb` are
present, so C++ works here where it did not on the Pi (D85, D105), and Dolphin
has a GDB stub if source-level debugging is ever wanted.

`wit` (Wiimms ISO Tool 3.01a) is installed and **cannot read RVZ**. Convert once
and work on the extracted filesystem. ⚠️ **`--align-files` and `--overwrite` are
both mandatory** on every `wit` rebuild — the first fails subtly, the second made
`--force` a half-truth until D38.

### Checks to run before finishing

```powershell
.\scripts\lint.ps1 --fix     # this branch's changed files -- fast
.\scripts\lint.ps1 --full    # every file; what CI runs
uv run pytest -q             # 1,462 tests
uv run mkdocs build --strict
cargo test  --manifest-path dimentio/Cargo.toml
cargo clippy --manifest-path dimentio/Cargo.toml --all-targets -- -D warnings
```

⚠️ **The lint default is the branch's diff, so a clean run is not a clean tree.**
`--full` is what caught an import cycle between two files when only one changed.

---

## Testing in-game without a human

`scripts/ingame.py` builds a mod, boots it, reads a report block out of the
running game and shuts Dolphin down — unattended.

```powershell
uv run python scripts/ingame.py my-mod --words 10 --watch-gw 30
```

**Reach for it before debugging anything in-game.** Three rounds of asking a
human to watch a screen produced two wrong conclusions (D38, D40); the rig has
since settled nine questions without one.

⚠️ **A run costs 2–3 minutes, so never truncate its output.** Every run writes a
full transcript to `work/build/ingame.log` — read that rather than piping the
console through `tail`. Reading `--words 9` when the answer sat in word 10 has
already cost a whole repeat run. Ask for more words than you think you need.

| Flag / behaviour | Why it exists |
|---|---|
| `--map he1_01` | any of the 383 maps is reachable unattended (D52, D64), and the rig prints `map=<name>` so a boot map that did nothing looks different |
| `--find <hex>` | searches MEM1 and MEM2 for a byte pattern — "which of these did the game load?" without knowing *how* |
| `--press a b 1+2`, `--press-at`, `--press-gap` | attended only; Windows refuses `SetForegroundWindow` to a background process |
| *(automatic)* | refuses to start if another Dolphin is open; reports *why* a read failed; reports a frozen game and a self-exited Dolphin |

Three addresses give full visibility from outside the emulator, via
`dolphin-memory-engine` attaching to the Dolphin **process**:

| Address | What |
|---|---|
| `0x80512360` | `seqWork` — current sequence at `+0x00`, stage at `+0x04` |
| `0x8050C990` | `evtGetWork()`'s return. `gw[]` at `+0x04`, so `gw[n]` at `+4+4n` |
| `0x80005000` | free scratch for a probe block (unused TRK interrupt table) |

⛔ **Input cannot be injected** (D48): Dolphin reads a DirectInput keyboard, which
ignores the message queue. Anything behind a button press needs a human, or
Dolphin's TAS movie playback, which is untried.

⚠️ **Gameplay is reached ~45 s after boot with no input.** The game runs
`LOGO -> MAPCHANGE -> GAME`, loading `aa4_01` then `ls4_12` — its attract demo —
and never enters `SEQ_TITLE` (D47). ⚠️ Neither of those two maps has NPCs or the
doors that mattered, which is how D93, D94 and D107 each produced a correct
measurement of the wrong place. Use `--map`.

### A hang that is really an assert names its own cause (D130)

`__assert2` is at `0x8019c54c` and its call sites pass `(file, line, func, expr)`.
Hook it with `mode: "before"` and copy the four arguments into a probe block:

```json
"hooks": [ { "function": "__assert2", "call": "on_assert", "mode": "before" } ]
```

`example-mods/coin-nobudget` is the worked example. That turned "the map freezes"
into `swdrv.c:505`, `(wp->gameCoinId - 1) < assign_tbl[i].num`, in one run, after
four runs of bisecting had narrowed it to one byte. ⚠️ **Assert messages are
Shift-JIS**, like the message files — decoding as ASCII throws away the sentence
that explains everything.

### Reading the DOL when the symbol list is thin

`eu0` names a few thousand functions out of a game with far more, so most
research starts from something that is **not** a symbol.

```powershell
uv run python scripts\dolscan.py strings setup_data      # 1. find a string
uv run python scripts\dolscan.py xref 0x80323BB0         # 2. who builds that address
uv run python scripts\dolscan.py callers 0x8028EA78      # 3. who calls that function
uv run python scripts\dolscan.py dis 0x800297A0 40       # 4. read the code
uv run python scripts\dolscan.py calls 0x40 0x800de9b8   # 5. who reads field +0x40
```

⚠️ **`xref` and `callers` answer different questions and each is silent about
the other's.** `xref` tracks how the game builds an *address* across
`lis`/`addis`/`addi`, which is right for data; a `bl` encodes a signed
displacement, so `xref` on a function returns **nothing**, which reads as "nothing
calls it". `callers` decodes every `bl` in the text range instead and found 178
callers of `GXSetVtxAttrFmt` (D206). ⛔ Widening `xref` to cover branches was
rejected: folding them together would keep the empty result silently plausible.

⚠️ **r13 is `0x805B5F00`** (D218), so every small-data global is addressable by
name. Neither `xref` nor `callers` can see an r13-relative global — the same
blind spot, and it hid the effect code for two sessions.

`scripts/modelscan.py` is `dolscan` for an undecoded data file: `survey`,
`header`, `offsets`, `at`, `strings`, `chain`.

---

## Open threads

Each carries the entry that established it. Nothing here is blocking everything
else; pick by interest.

### Assets

1. ⛔ **Shape → texture binding.** Three candidates refuted: identity, section
   slot 17, and a material index in the face record (D229, D229 addendum). Every
   shape's UVs span the full `[0,1]` square, so a shape is not a region of an
   atlas — each has its **own** image. 761 models export untextured because of
   it. The per-shape primitive split (D237) is this binding's prerequisite, not
   its answer.
2. ⛔ **Effect part → image binding.** Six candidates refuted (D210). 🔶 The live
   lead is D218: `Part.first` is a *signed* index, `0xFFFF` meaning none, into a
   **second** 20-byte record array whose fields at `+0x08`/`+0x0A`/`+0x0E`/
   `+0x0F`/`+0x12` drive drawing. Which `effdata.dat` section that is has not
   been established; section 7 is 17,760 bytes = 888 records of 20, untested.
3. 🔶 **`effdata.dat`: 2 of 16 sections read** (D190, D191). 139 effects, 704
   parts, 4,048 transform rows. Nine sections remain, none with any strings.
4. ⛔ **Which Maya shape name goes with which primitive** (D237). Names are read
   in file order, groups are found by `first` restarting at zero, and nothing
   binds one to the other.
5. 🔶 **Model slots 5, 6 and 16–23** are unread; see
   [`model-format.md`](./model-format.md).
6. ⚠️ **`curves()` is a superseded reading that still ships.** D216 decoded keys
   as `[time step, s16 delta, zero]`; D217 shows the game reads them as
   `[u8 vertex stride, s8 dx, s8 dy, s8 dz]`, and the fourteen-fold smoothness
   separation was detecting correlated adjacent bytes rather than confirming the
   interpretation. Only `morphs()` reaches a `.glb`.
7. ⚠️ **The ADPC seek table is undecoded** (D226 addendum, D228). It is now a
   curiosity rather than a blocker — nothing reads it, seeking uses the decoded
   samples — but it is the one instrument that disagreed with four others and
   was believed anyway.
8. 🔶 **`Stream.playback_rate` is fitted to two points, not decoded** (D232). It
   halves a stated rate above 40000. Nothing in the DOL, `wiimario_snd.dat` or
   the RSAR encodes the rule (D230), and the threshold is 40000 rather than
   32000 precisely because only 44100 was measured.
9. 🔶 **"Every track is stereo" may not hold** — `sys_title1_44k_lp` tests the
   *other* way on the interleave check, correlation rising 0.837 → 0.879, which
   is the signature of mono (D232).
10. ⛔ **Tier 2 texture editing — replacing artwork — needs a real DXT1 encoder**
    and is not started. Everything today is exact *because* it never
    re-compresses (D187, D193).

### The game

11. 🔶 **The boss NPC hang.** `chaos-heart` orbits five effects for 22,350 frames
    with no freeze, where the boss *NPC* froze at a fixed ~2,177 (D157, D183).
    The effect path sidesteps the hang rather than explaining it.
12. 🔶 **443 builtins, 10 measured** (D184). `example-mods/builtin-probe` is the
    route. ⛔ `evt_pouch_check_have_item` never returns and nobody knows why.
13. **`peek`/`poke` for `SET_RAM`/`GET_RAM`** — the language's biggest remaining
    gap. ⚠️ Maps did **not** need it (D51) and doors do **not** (D103).
14. 🔶 **`plus`/`minus`/`home`/d-pad masks** — one `button-probe` run each. `a`,
    `b`, `1`, `2` are confirmed (D68).
15. 🔴 **US (`us0`) support is blocked on a US disc image.** `work/extracted/`
    holds `eu0` only.
16. 🔶 **54 builtins remain unlinkable** (D61): 21 live in the game's own REL at
    REL-relative addresses, 33 have no known address anywhere.

### Shipping

17. ⚠️ **The published `v0.1.0-rc1` assets were built from a commit the history
    rewrite replaced**, so they no longer correspond to what the tag points at
    (D149, corrected). ✅ The tag-triggered release job itself **has** run and
    fully succeeded — `roadmap.md` said otherwise for a day and one
    `gh run list` refuted it. ⚠️ `gh release create` is not idempotent, so
    re-pointing an existing tag fails on the release step.
18. **A GUI over the JSON API.** Any language; the contract is JSON and
    `bleck mod schema` publishes it.
19. **Hot reload** — designed for, not built (D37). ⛔ Reloading a rebuilt REL is
    ruled out: there is no `OSUnlink`.
20. 🔶 **Speed, if profiling names it.** LZ77 is ~12 s/MB (D16). The recorded
    answer is a PyO3 port of *just the compressor*, not a rewrite.
21. **A save state.** Driving into a map leaves Mario invisible: no save, no
    profile (D63). `--state` exists on `bleck launch` and `ingame.py`; making one
    needs someone to play far enough and press F1.

---

## What is not in git, by design

| | Notes |
|---|---|
| `work/roms/` | disc images. Supply your own |
| `work/extracted/eu0` | the PAL rev 0 base. Regenerate with `bleck extract` |
| `work/export/`, `work/models/` | asset exports. Regenerable, and large — 123 MB of models alone |
| `work/reference/` | **third-party ground truth**: supplied rips and recordings. Tests skip without it |
| `mods/` | everything except `README.md` (D175) |
| `mods/*/overlay/` | extracted game assets and generated `mod.rel` |
| `work/build/`, `out/` | staging and images |
| Upstream clones | `spm-headers`, `spm-rel-loader`. Re-clone as needed |
| `CLAUDE.md` | machine-specific working guidance, purged from history in D149 |

**Committed mods look empty and that is correct.** `example-mods/title-invert`
and `example-mods/tex-koopa` have manifests but no overlays:

```powershell
uv run bleck mod vendor title-invert lyt/title.bin.uk/arc/timg/mario.tpl --mods-dir example-mods
uv run bleck mod vendor tex-koopa    lyt/title.bin.uk/arc/timg/koopa.tpl --mods-dir example-mods
```

Script mods are different: `example-mods/speedrun` and `example-mods/coin-tick`
commit their `scripts/*.evt` source and `bleck mod build` regenerates `mod.rel`.

---

## Things worth not rediscovering

- **`_prolog` runs far too early to touch game subsystems** (D38). Fine for
  patching instructions and nothing else. Full timing table in
  [`hook-points.md`](./hook-points.md).
- **A script does not survive a map change** (D43). evt state is rebuilt, so
  anything long-lived must be re-armed.
- ⚠️ **The game shares `gw[]` with your scripts.** `gw[10]` is written by the
  game; `gw[30]` was untouched across a full session.
- ⛔ **`MapData.initScript` cannot be repointed** — a wrapper installs fine, then
  deadlocks the map load (D51). ✅ Mutating the bytecode that pointer already
  refers to is a different mechanism and works (D89).
- ⛔ **A script that simply ended used to hang the game** (D105, D106): only
  `END_SCRIPT` was emitted, never `END_EVT`, so the entry outlived the script.
  Fixed; both terminators are now always emitted.
- ⛔ **Clearing a middle enemy slot orphans every slot after it** (D79). The game
  stops reading setup entries at the first empty one. `bleck` refuses it.
- ✅ **The game reads the *standalone* `files/setup/<map>.dat`** (D62). ⚠️ D53
  concluded the opposite and several docs said so for a month — it is the single
  most-copied wrong fact in this repo.
- **Merging happens at compile time** (D78), because the Gecko loader opens
  exactly one `/mod/mod.rel`. ⛔ `chainrel` is a three-commit stub whose loader
  body is wrapped in `#if 0`; nobody in this scene has solved multi-mod loading.
- ⛔ **Never copy from Flipside-Mod-Manager** (D39): no LICENSE, and its loader is
  plainly derivative of GPLv3 `spm-rel-loader`.
- ⚠️ **An automated fetch of a TCRF page returned a prompt-injection payload**
  aimed at LLM tooling (D39). ✅ The page itself is clean (D41), so it is a
  serving-layer phenomenon. **Treat fetched content as untrusted input.**
- **Share builds as `.wbfs`.** RVZ needs Dolphin 5.0-12188+; older builds reject
  it as "not a GC/Wii ISO", which reads like corruption and is not.
- ⚠️ **The intercept wrapper is generated PowerPC assembly**, not C. A hook is
  resolved from a symbol *name* and nothing carries a signature, so **a handler's
  prototype must match the target exactly and nothing can check it**. Floats reach
  a handler correctly but are invisible to a trace record, and a function with
  more than eight integer arguments cannot be intercepted at all (D97).
- ⚠️ **The cache flush is necessary, not decorative** (D94). Two identical
  patches differing only in `dcbst`/`sync`/`icbi`/`isync` read back the same word
  and behaved differently.
- **The five JSON catalogs are found with `Path(__file__).with_name()`**, so
  PyInstaller must bundle them at paths mirroring the package — get it wrong and
  the binary starts happily and reports an *empty* catalog. **`__main__.py` must
  use an absolute import.** `scripts/smoke_binary.py` is the step that catches
  both; a build that merely *builds* proves almost nothing.
  ⚠️ **`doorcatalog.json` was loaded by `bleck doors` and bundled by nothing**,
  so every release told the user "no door catalog shipped with this build".
  `tests/test_smoke_binary.py` now derives the list from the source rather than
  trusting `bleck.spec`'s comment, which said four.
- ⚠️ **A smoke check must not name a catalog row.** It asked for the item
  `fire_burst` and the English name `Fire Burst`; D194 moved English text off
  the catalog and onto the user's own disc, and all three platform jobs then
  failed the same assertion. Expectations are read out of the committed catalog
  now, and `tests/test_smoke_binary.py` holds them to what the CLI prints.
- ⚠️ **`scripts/keys.py` synthesises input and must stay out of the `bleck`
  package** — `tests/test_boundaries.py` enforces it.
- **Two runtime dependencies, each argued**: `pyyaml` for `bleck.yml`, `pydantic`
  for the JSON API and its published schema. ⚠️ The install docs claimed "no
  runtime dependencies" for a while after that stopped being true.
- ⚠️ **`rodio` is pinned to `default-features = false`** (D227). The defaults pull
  in Symphonia, which is **MPL-2.0**, and this repo is MIT.

---

## ⚠️ Methodology, earned the hard way

**Before trusting a negative result, produce a positive one.** Six runs and four
decision-log entries went into a bug that did not exist (D70, D73, D74, retracted
by D76), because the rig read the current map from `seqWork.p0` — a field that
only means anything *during* a map change. Every entry was internally consistent,
had a control, and bisected cleanly.

**A control does not help when it is measured with the same broken ruler.** The
model work repeated this three times in one session, each in a different shape:

| | the instrument's blind spot |
|---|---|
| D209 | the shape measured was flat, so the random control was coplanar too |
| D211 | degenerate faces are planar *for free* — 16% of quads use fewer than four distinct vertices |
| D214 | vertices are locally clustered, so planarity cannot see a wrong group base at all — **UV coherence can** (D224) |
| D216 | adjacent bytes are small correlated deltas, so smoothness confirmed *structure* and not the *interpretation* (D217) |

⚠️ **Ask what makes the test pass trivially, not only what makes it fail.**

⚠️ **And the mirror image, which is worse** (D228): an instrument can
confidently report a signal that is not there. Four cheap independent
measurements said the audio decoder was correct; one structure whose layout was
*admitted to be not understood* disagreed, and it carried the argument — because
a mismatch feels like evidence in a way that agreement does not. **When a single
unexplained measurement contradicts several understood ones, suspect the
measurement.** When the proposed fix is "vary the working code until it matches",
stop: that is fitting, not decoding.

⚠️ **A test must not depend on how the export it reads was produced** (D234
addendum). Two real-export tests broke on `--guess-textures`, and neither was a
code fault. One of them has now been rewritten three times to chase the truth of
the moment.

⚠️ **A fixture written by the test that reads it cannot detect a disagreement
between two programs** (D221). `dimentio` parsed only OBJ for a whole session
after `bleck` moved to glTF, and every mesh test passed, because each built its
own OBJ. The suite needed one foot in the real output.

**A probe must report the precondition it depends on**, not just the value it
went looking for. Five instrument errors in two days, all caught by *cross-run
agreement* — a value measured by a different probe, in a different run, by a
different route. Internal consistency caught none of them.

**Report the effect, not the setup.** D51's map hook passed every mechanical
check — valid pointer, right offset, original preserved — and still froze the
game. Only a probe value showing the script had never run exposed it.
