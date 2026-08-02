# spm-modkit

Modding toolkit for **Super Paper Mario** (Wii, 2007).

## Orientation

| Path | What it is |
|---|---|
| `docs/vision.md` | **Where this is going** — a full SPM mod editor, and what that forces now |
| `docs/handoff.md` | **Start here on a new machine** — what works today, what a *person* has confirmed versus what only tests believe, the open threads and the standing traps |
| `docs/roadmap.md` | **What to build next**, and what blocks what |
| `docs/coding-standards.md` | **Enforced rules.** Read before writing code |
| `docs/state-of-spm-modding.md` | Ecosystem research snapshot (2026-07-26) — tools, gaps, prior art |
| `docs/tool-comparison.md` | **Internal.** What `bleck` does that the scene does not, and vice versa. Includes the evtpatch licence problem |
| `docs/decision-log.md` | **Living.** Why choices were made, chronologically |
| `docs/disc-layout.md` | **Living.** Observed facts about SPM's disc contents |
| `docs/function-behaviour.md` | **Living.** What game functions do, measured by tracing them |
| `docs/model-format.md` | **Living.** The character model format in `files/a/` — the 24-slot section table, per-shape rebasing, morph animation, and the refuted candidates |
| `docs/cli-design.md` | The `bleck` CLI's shape and rationale |
| `docs/mods.md` | How mods, overlays, dependencies and conflicts work |
| `docs/code-mods.md` | Compiled PowerPC code mods — design + proven toolchain |
| `docs/scripting.md` | **The scripting language** — compiles to the game's own `evt` VM |
| `docs/hook-points.md` | **When custom code can safely run.** Read before writing a hook |
| `docs/plan-config.md` | ✅ Built: `bleck.yml` and named button combos |
| `docs/plan-merging.md` | ✅ Built: several code mods merged into one REL |
| `docs/plan-textures.md` | 🟢 Planned: declarative texture edits, and why texture mods cannot be shared yet |
| `docs/hardware.md` | ✅ Built: Riivolution patch output, and the output-kind table |
| `docs/windows.md` | Windows 11 setup |
| `docs/macos.md` | macOS setup |
| `docs-site/` | **User-facing** docs — install, usage, reference. Material for MkDocs, published to GitHub Pages |
| `docs-site/findings/` | **Third audience**: SPM researchers who do not use `bleck`. Measured facts + evidence, published (D121) |
| `bleck/api/` | **The JSON contract** other programs integrate against. Versioned; see `handoff.md` |
| `bleck.spec` | PyInstaller build. ⚠️ Read the traps in `handoff.md` before touching it |
| `example-mods/` | **Every mod this project has built** — worked examples and probes. Pass `--mods-dir example-mods` |
| `mods/` | **The user's own mods.** `BLECK_MODS_DIR` defaults here. **Git-ignored** — see the rule below |
| `work/upstream/spm-headers` | Cloned reference — struct layouts and addresses. Not vendored |
| `work/roms/` | Disc images (WBFS/RVZ). Not source. Large. |
| `work/extracted/` | `wit EXTRACT` output, one dir per build (`us0`, …). Regenerable. |
| `LICENSE` / `THIRD-PARTY-NOTICES.md` | MIT, and what upstream requires. **Read the rule below before copying anything in** |

Read `decision-log.md` before proposing an approach — it records paths already
ruled out and why. Read `roadmap.md` to see what is next and what is blocked.

## ⚠️ The methods live in `.claude/skills/`, and unlike this file they travel

Fourteen skills, a directory each with a `SKILL.md` loaded on demand (D254):
**six methods** — `decode-by-disassembly`, `control-every-statistic`,
`verify-the-emitted-artifact`, `render-to-look`,
`ground-truth-from-reference-rips`, `slow-command-discipline` — and **eight
tools** — `ingame-testing`, `hunting-a-hang`, `reading-the-game-live`,
`catalog-dumps`, `reading-undecoded-data`, `bleck-cli-workflows`,
`linting-and-ci`, `arm64-container`.

⚠️ **`.claude/` is not git-ignored and `CLAUDE.md` is** (D149). So a skill
reaches another machine and this file does not — which is why a two-page method
belongs in a skill rather than here, where every session pays for it whether the
task needs it or not.

## RULE: `bleck` is MIT — keep derived code MIT-compatible

- ⛔ **`spm-rel-loader` and `spm-headers/mod/` are GPLv3.** Copying from either
  relicenses this whole repo. `spm-headers`' `include/`, `decomp/` and
  `linker/` are MIT and are what `bleck` reads.
- ⚠️ **Derived data ships the notice with it.** `catalog.json` carries the full
  MIT text, not a URL. Anything else derived that lands under `bleck/` needs a
  row in `THIRD-PARTY-NOTICES.md`.
- ⛔ **No game assets.** `work/` is git-ignored; keep it that way. Addresses and
  struct offsets are facts and are fine to record.

⚠️ **Read `vision.md` before making a design decision.** The goal is a full
editor, GUI included. The constraint that bites most often: **edits are
declared as data and generated at build time, never shipped as baked bytes** —
a blob cannot be undone, reviewed, or opened in an editor.

⚠️ **Two doc trees, different audiences.** `docs/` is the living design record
for maintainers (why, and what is true). `docs-site/` is the published site for
users (how to install and use). A user-visible behaviour change should update
both.

⚠️ **`mkdocs.yml` sets `docs_dir: docs-site` on purpose.** MkDocs would
otherwise default to `docs/` and publish the internal design record.

---

## RULE: `mods/` is untracked scratch; examples are *copied* to `example-mods/`

**Everything under `mods/` is git-ignored** except its `README.md`. Write new
probe mods there freely — that is what it is for, and nothing needs cleaning up
afterwards.

When a mod earns its keep — it demonstrates a concept, or it produced a finding
recorded in `docs/decision-log.md` — **copy** it to `example-mods/` and commit it
there. Copy, do not move: the working version stays where the work is happening.
Drop `overlay/` from the copy; it is build output.

```bash
cp -r mods/my-mod example-mods/my-mod && rm -rf example-mods/my-mod/overlay
uv run bleck mod check my-mod --mods-dir example-mods
```

⚠️ **A mod named in `docs/` must exist in `example-mods/`**, or the reference
rots the moment the scratch copy is deleted. This is the same rule as the
`--mods-dir example-mods` note above, seen from the writing end.

## RULE: Return named types

**Never return `dict` or `tuple` — including nested, like `list[tuple[str, int]]`.**
Define a small frozen dataclass instead, so every value has a name.

This is enforced by a pylint plugin (`C9001`), not just convention. The escape
hatch is `# pylint: disable=container-return`, for genuine library boundaries
only.

The point is readability: a signature should say what comes back.
`tuple[int, int]` tells a reader nothing.

## RULE: Environment access goes through `bleck/common/env.py`

`os.environ` and `os.getenv` are rejected everywhere else (pylint `C9002`).
Declare each variable as an `EnvVar`, add it to `DECLARED`, and read it with
`env.text` / `env.flag` / `env.path`. Scattered env reads leave no discoverable
list of what is configurable.

## RULE: Comments say what the code does, not how we feel about other projects

**Do not editorialise in source files.** No comment or docstring should:

- position a feature against a named third-party project, or describe it as an
  answer, alternative or workaround for one
- discuss another project's licence, or why we did not use it
- narrate strategy, competitive positioning, or legal reasoning

State what the code does and what will break if it changes. **Reasoning goes in
`docs/`**, which is the project's record and is where a reader looks for it.
Licence obligations live in `THIRD-PARTY-NOTICES.md` and the rule at the top of
this file; comparisons live in `docs/tool-comparison.md`, which is marked
internal.

⚠️ Enforced structurally as well: **a run of `#` comment lines may be at most
3** (pylint `C9003`). `#:` attribute docs and tool directives such as
`# pylint: disable` are exempt. The escape hatch is
`# pylint: disable=comment-too-long`, for something that genuinely must sit with
the code — a measured memory layout, or a table whose columns need naming.

## RULE: Capture output to a file; never filter raw stdout

**Redirect a command's full output to a file, then read slices from the file.**

```bash
./scripts/lint.sh --full > "$CLAUDE_JOB_DIR/tmp/lint.txt" 2>&1
uv run pytest -q       > "$CLAUDE_JOB_DIR/tmp/tests.txt" 2>&1
```

Piping straight into `tail`/`head`/`grep` throws away output that has already
been paid for, so seeing more means running the command again. The linter, the
full test suite and `dolscan` sweeps are all slow enough to notice, and
`scripts/ingame.py` costs 2-3 minutes -- which is why it already writes
`work/build/ingame.log` and the rule above says to read that rather than re-run.

⚠️ **When a filter turns out too narrow, re-read the file.** Never re-run the
command to widen a query.

## RULE: Run the linters before finishing

```bash
./scripts/lint.sh --fix          # this branch's changed files only -- fast
./scripts/lint.sh --full         # every file; what CI runs
```

Every project rule above lives there, alongside ruff and pylint. Full detail in
[`docs/coding-standards.md`](docs/coding-standards.md).

⚠️ **The default is the branch's diff, so a clean run is not a clean tree.**
Run `--full` before concluding the repo passes: a per-file check cannot see an
import cycle between two files when only one of them changed, which is exactly
what `--full` caught when `code.replace` landed.

## RULE: Keep the living docs current

**Any agent doing substantive work in this repo must record its reasoning in
`docs/` as it goes — not at the end, and not only on request.**

This exists because context gets compacted. Reasoning that lives only in a
conversation is lost; reasoning in `docs/` survives.

### When to write

Append an entry when you:

- Choose between real alternatives, or **rule an approach out**
- Discover a fact about the game, disc, or tooling that changes what to build
- Hit a blocker, or resolve one
- Find that an earlier assumption was wrong

Do **not** log routine mechanics (ran a build, listed a directory) unless the
result was surprising.

### Where to write

- **`decision-log.md`** — *why*. Chronological, dated, append-only.
- **`disc-layout.md`** — *what is true about the disc*. Factual reference.
- New topic-specific docs are fine; link them from `decision-log.md`.

### RULE: Before trusting a negative result, produce a positive one

**Six runs and four decision-log entries (D70, D73, D74) went into a bug that
did not exist**, because the rig read the current map from `seqWork.p0` — a
field that only means anything *during* a map change. A run that changed maps
looked identical to one that did not.

Every one of those entries was internally consistent, had a control, and
bisected cleanly. **A control does not help when it is measured with the same
broken ruler.**

So: before concluding something did not happen, show the instrument can see it
happening. And treat "works by eye, invisible to the rig" as a finding *about
the rig* — that discrepancy was visible for a day before anyone said it aloud.

Related: prefer the two-line test to the new tool. D71 built a whole script to
read a bound address, correctly, to answer a question that did not matter; one
extra `gw` write would have been more discriminating and taken minutes.

### RULE: Record expensive results; don't re-run them

Some operations here are slow — the LZ77 compressor runs ~12 s/MB, and reference
encoders can take minutes per file. **Measure once, write the number into
`docs/`, and cite the recorded value thereafter.**

Re-run a benchmark only when the code under test has actually changed. Never
re-run one just to restate a number in conversation. Baseline metrics live in
`decision-log.md` (D16) — read them instead of regenerating them.

The same applies to disc extraction, RVZ conversion, and full-corpus sweeps:
these produce artifacts on disk. Check whether the artifact already exists before
recomputing it.

### How to write

Follow the existing entry format. Non-negotiable parts:

1. **Mark confidence explicitly.** ✅ verified by direct observation · 🔶
   hypothesis, not yet tested · ⛔ ruled out. Never present an untested inference
   as a finding — several already-recorded hypotheses (LZ77 compression, `/a`
   container format) are load-bearing and must stay visibly unproven until tested.
2. **Record rejected alternatives and the reason.** A decision without its
   discarded options is not reusable.
3. **Append; don't rewrite.** When something turns out wrong, add a superseding
   entry and mark the old one — do not delete it. The wrong turn is often the
   most useful part of the record.
4. **Cite evidence.** Byte magics, file sizes, quoted README lines, command
   output. "TPL magic `00 20 AF 30`" beats "it's a TPL."
5. **Log your own mistakes.** D7 records a misdiagnosis (a TorrentZip read as a
   truncated download) precisely so nobody repeats it. Do the same.

---

## Working notes

- **Anchor to PAL rev 0 (`eu0`)** for anything address-dependent. It has by far
  the largest symbol list and all upstream docs target it. US support is a
  porting problem, deliberately deferred.
- **`--align-files` is mandatory** on every `wit` rebuild. Upstream calls this
  out; omitting it fails subtly.
- **Work on the extracted filesystem.** ISO/WBFS/RVZ are transport formats —
  convert once, then work on files.
- **The modding path is REL code injection, not decomp rebuilding.** The decomp
  (~2.34% matched) is a symbol/documentation source. Do not treat its low
  completion as a blocker; that inference is explicitly wrong.
- **The asset pipeline is validated end to end** (D25): a disc built by `bleck`
  boots and renders modified textures. Bit-exact LZ77 is *not* required — ours
  is ~0.25% larger with different token boundaries and the game accepts it.
  Build on this foundation without re-litigating it.
- **Share builds as `.wbfs`.** RVZ needs Dolphin 5.0-12188+ (2020); plain 5.0
  stable rejects it as "not a GC/Wii ISO".
- **Setup files: the game reads the *standalone* `files/setup/<map>.dat`** (D62).
  The copy embedded in the map archive is ignored, so editing only that one is a
  silent no-op. `bleck` writes both and warns at build time.
  ⛔ **D53 said the reverse and is superseded** — it is the single most-copied
  wrong fact in this repo, so check which way round a doc has it before trusting
  it.
- **Any map is reachable unattended** (D52). A script attached to `aa4_01` can
  call `evt_seq_mapchange("<map>", 0)`; `example-mods/goto-map` is the worked example.
  This is what makes testing anything outside the attract demo possible.
- **Verify "no tool exists" claims against the actual disc** before building
  anything to fill the supposed gap. One such gap already evaporated on contact.
- **Several code mods now merge into one `mod.rel`** (D78). The loader's
  one-REL limit is real and unchanged; merging happens at *compile* time, so
  `chainrel`'s unsolved runtime chaining is not on this path.
- **A mod can read the controller** (D66). ⚠️ D48 said input cannot be
  *injected into Dolphin from outside*, which is a statement about automating
  tests. It says nothing about the game reading its own pad, and reading it that
  way closed off button-triggered features for weeks.
- ⛔ **Clearing a middle enemy slot orphans every slot after it** (D79). The
  game stops reading setup entries at the first empty one. `bleck` refuses it.
- **A function can be watched without being broken** (D96, D97). `code.hooks`
  takes `mode: "before"` / `"after"` as well as `"replace"`, so running
  *alongside* the original is a manifest field, not a hand-written pattern — the
  generated wrapper restores the original instruction around the call. Recording
  arguments and return values on top of that is still hand-written;
  `example-mods/fn-trace-probe` is the pattern and `example-mods/intercept-probe` the declared
  form. ⚠️ **A handler's prototype must match the target exactly** or it corrupts
  the call, and nothing can check this — a symbol list has no signatures. Floats
  reach a handler correctly but are invisible to the trace record, and a function
  with more than eight integer arguments cannot be intercepted at all. Findings
  go in `docs/function-behaviour.md`.

## Environment

- Dev host is **aarch64 Linux** (Raspberry Pi); **Windows 11 is a supported
  target** for the CLI and is where emulation testing happens.
- `wit` (Wiimms ISO Tool 3.01a) is installed. It cannot read **RVZ**.
- **devkitPPC is the toolchain, on every host including aarch64 Linux** (D249).
  devkitPro publishes `devkitppc-gcc` for `linux/aarch64`; D26's "unobtainable
  here" was a Cloudflare 403 read as an empty package list. **C++ comes in the
  same package** (D85), and `bleck` derives `powerpc-eabi-g++` from whichever
  `gcc` it located.
- ⛔ **Debian's `powerpc-linux-gnu-gcc` 14.2.0 compiles but cannot currently
  produce a REL** (D250, superseding D26 in part). Its gcc injects no linker
  script, so `ld -r` never merges sections; and GCC 14.2.0 emits `addend=-4`,
  which `pyelf2rel` packs unsigned and refuses. Do not reach for it as a
  fallback without reading D250.
- `sudo` requires a password — ask the user to run installs via `! sudo apt …`.
- **Tool paths come from `.env`, loaded automatically** — do not export
  `BLECK_*` per command. Copy `.env.example` if it is missing. The real
  environment still wins, so a one-off override works.

## ⚠️ `bleck`'s subcommands are flat, and the module names are not commands

`bleck/cli/commands/` contains `disc.py`, `emulate.py` and `inspect.py`, and
⛔ **there is no `bleck disc`, `bleck emulate` or `bleck inspect`.** Each module
registers its subcommands at the **top level**, so the file names are an internal
grouping and nothing more. The twenty that exist:

```
build   doors   effect  extract  info    items   launch  ls      lz      maps
mod     model   pack    script   setup   sound   symbols texture unpack  verify
```

Eight of them nest further — `mod`, `script`, `model`, `texture`, `sound`,
`effect`, `symbols` and `setup` — so `mod build`, `model export`,
`texture list`. ⚠️ **`bleck build` and `bleck mod build` are different
commands.** ⛔ `bleck toolchain install` is advertised in
`bleck/backends/toolchain.py` and does not exist (D239).

## The scripts you will actually use

`scripts/` is the research toolkit. These come up constantly; the rest
(`lint.*`, `smoke_binary.py`, `module_notes.py`) run themselves or are imported
by a generator.

| Script | For |
|---|---|
| `ingame.py` | **Build, boot, read memory, shut down — unattended.** See the rule below |
| `dolscan.py` | **Read the DOL**: disassemble, find strings, cross-reference them |
| `check_binding.py` | Whether a button combination reached the game |
| `dump_npcs.py` / `dump_items.py` / `dump_maps.py` / `dump_doors.py` | Regenerate a committed catalog from a running game |
| `dump_effects.py` | **List all 174 effects** -- reads the DOL, needs no running game |
| `modelscan.py` | **Read a character model, or any undecoded data file** — what `dolscan` is for the DOL. Nine subcommands: `survey`, `header`, `offsets`, `at`, `strings`, `vectors`, `streams`, `chain`, `mesh` |
| `evtdis.py` | **Read the game's own scripts.** `--template 196` lists a template's script pointers |
| `dump_builtins.py` | **Regenerate the language reference** in `docs-site/scripting/`. `--check` is what CI runs |
| `container_verify.py` | **Rebuild example mods with whatever cross-compiler is installed** and diff each `mod.rel` against the one in that mod's `overlay/`. The arm64/devkitPPC gate (D249) |
| `tint_tpl.py` | **Recolour a CMPR TPL in the endpoint domain** — the prototype for `plan-textures.md`'s declarative `tint`. Never decompresses, so the result is exact |

### `dolscan.py` — when there is no symbol for it

`eu0` names a few thousand functions out of a game with far more, so most
research starts from something that is **not** a symbol. The technique that
keeps working (D128, D130, D133, D136):

```bash
uv run python scripts/dolscan.py strings setup_data      # 1. find a string
uv run python scripts/dolscan.py xref 0x80323BB0         # 2. who builds that address
uv run python scripts/dolscan.py dis 0x800297A0 40       # 3. read the code
uv run python scripts/dolscan.py calls 0x40 0x800de9b8   # 4. who reads field +0x40
```

⚠️ **`xref` tracks register values across `lis`/`addis`/`addi`** because the game
builds addresses as a base register plus an offset. A naive two-instruction
search finds *nothing* — that is why `assign_tbl` took a purpose-built tool
rather than grep. `--window 0x40` also reports bases near the target, which is
how the string tables in D128 were found.

⛔ **`xref` cannot find who *calls* a function** — a `bl` is a displacement, not
an address, so it returns nothing and that reads as "nobody". Use
`dolscan.py callers <addr>`. This is what unblocked model geometry after four
failed attempts at pattern-matching the file (D206, D207): **when a format will
not yield, find the code that reads it and let the game state its own layout.**

`calls` finds "reads a struct field, then calls something" — how D136 showed a
door reads `interactScript` live rather than caching it at map load.

### ⚠️ A hang that is really an assert names its own cause

`__assert2` is at `0x8019c54c` and its call sites pass `(file, line, func,
expr)`. Hook it with `mode: "before"` and copy the arguments into a probe block:
that turned "the map freezes" into `swdrv.c:505` in one run, after four runs of
bisecting had narrowed it only to a single byte (D130). `example-mods/coin-nobudget` is
the worked example. **Assert messages are Shift-JIS**, like the message files.

## RULE: Test in-game by reading memory, not by asking

`scripts/ingame.py` builds a mod, boots it, reads a report block out of the
running game and shuts Dolphin down — unattended.

```bash
uv run python scripts/ingame.py my-mod --words 10 --watch-gw 30
```

**Reach for it before debugging anything in-game.** Three rounds of asking a
human to watch a screen produced two wrong conclusions (D38, D40); the rig has
since settled seven questions without one.

⚠️ **Every mod named in these docs lives in `example-mods/`, not `mods/`**
(D147). `bleck` looks in `mods/` by default, so a bare `bleck mod check mr-l`
reports "no mod named" — pass `--mods-dir example-mods`, which every **`bleck`**
command accepts. Build a *new* probe under `mods/`; that is what it is for.

⛔ **`scripts/ingame.py` does not accept `--mods-dir`.** It shells out to
`bleck mod build <mod> …` with no such flag, so the mod is resolved against
`BLECK_MODS_DIR` — which defaults to `mods/`. To run an example mod through the
rig, set the variable for the call:

```powershell
$env:BLECK_MODS_DIR = "example-mods"; uv run python scripts/ingame.py coin-tick --words 12
```

⚠️ **A run costs 2–3 minutes, so never truncate its output.** Every run writes a
full transcript to `work/build/ingame.log`; read that rather than piping the
console through `tail`. Reading `--words 9` when the answer sat in word 10 has
already cost a whole repeat run. Ask for more words than you think you need —
they are free — and re-read the log, which is free too.

⚠️ **This host has the REL loader enabled as a Dolphin cheat** (D86):
`%APPDATA%\Dolphin Emulator\GameSettings\R8PP01.ini`, listed under
`[Gecko_Enabled]`, with `EnableCheats = True`. So a mod can run **even when the
DOL carries no loader at all**. Before concluding that an embedded loader
worked, move that file aside and re-run.

⚠️ **Report the *effect*, not just the setup.** D51's map hook installed
perfectly by every mechanical check and still froze the game — only a probe
value showing the script had never run exposed it. "Installed: yes" would have
read as success.

⚠️ **Controller input cannot be injected *unattended*** (D48). The blanket form
of that claim is over-broad: `ingame.py --press a b 1+2` works, via `SendInput`
in `scripts/keys.py`, which injects below DirectInput's polling where D48's
`SendKeys`/`PostMessage` did not. What it needs is a **Windows host, an unlocked
session and Dolphin in the foreground** — so it is attended, and CI cannot use
it. Gameplay is reached ~45 s into an unattended boot, and the attract demo
loads `aa4_01` then `ls4_12` — which is what makes map hooks testable with
nobody watching.

## Cross-platform rules

**Linux, Windows 11 and macOS are all supported. Keep it that way:**

- **Platform differences are data, not conditionals.** They live in
  `bleck/platforms/{linux,macos,windows}.py` as `PlatformProfile` values.
  Never add `if platform.system() == ...` outside that package — add a field to
  the profile instead.
- **No shell scripts as the only entry point.** `scripts/lint.py` is the real
  implementation; `lint.sh` and `lint.ps1` are wrappers.
- **External tools differ by name and location.** `dolphin-tool` on Linux,
  `DolphinTool.exe` on Windows, `DolphinTool` inside `Dolphin.app` on macOS.
  Add candidates to the profile, never a bare `shutil.which("name")`.
- **Store paths posix-style.** Manifests and archive members use `/` and must
  survive a Windows↔Linux round trip; use `.as_posix()` when recording.
- **Never rely on `st_nlink`.** Windows does not report it reliably. `_detach`
  unlinks unconditionally for this reason.
- **Deleting read-only files fails on Windows.** Use `builder.remove_tree`,
  not `shutil.rmtree`.
- `tests/test_platform.py` exercises the Windows paths by patching
  `disc.IS_WINDOWS`, so regressions surface on Linux CI.
