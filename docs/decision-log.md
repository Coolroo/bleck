# Decision Log — spm-modkit

**Purpose:** a living record of *why* choices were made, so reasoning survives
context compaction. Append entries; don't rewrite history. Mark superseded
decisions rather than deleting them.

Companion docs:
- [`state-of-spm-modding.md`](./state-of-spm-modding.md) — ecosystem research snapshot (2026-07-26)
- [`disc-layout.md`](./disc-layout.md) — factual findings about SPM's disc contents

**Legend:** ✅ verified by direct observation · 🔶 hypothesis, not yet tested · ⛔ ruled out

---

## 2026-07-26

### D1 — Research the ecosystem before writing any code ✅

**Decision:** Run a deep multi-source research pass first; produce
`state-of-spm-modding.md` before touching the ROMs.

**Why:** SPM modding is a small niche with a real risk of rebuilding something
that already exists, or of picking a technically-correct-but-abandoned path. A
survey up front is cheap relative to that waste.

**Outcome:** Paid off immediately. The single most important finding inverted the
obvious assumption: **the practiced path is REL code injection, not decomp
rebuilding.** Had we started from "the decomp is only 2.34% done, that's
hopeless," we'd have drawn exactly the wrong conclusion. That framing was
explicitly refuted 0–3 by adversarial verification.

---

### D2 — Keep the WBFS; don't re-source an ISO ⛔→✅

**Considered:** obtaining a "proper" ISO instead of the WBFS dumps on hand.

**Rejected because:** WBFS is a *container*, not a lossy format. It strips unused
sectors filled with deterministic pseudo-random junk, which WIT regenerates on
demand — so WBFS→ISO can be bit-identical to the original dump. Re-sourcing would
have bought nothing.

**Further:** we don't want an ISO at all for the development loop. The modding
cycle is `extract → drop in /mod/mod.rel → rebuild`, and WIT reads WBFS directly
as an extraction source. ISO generation is a *release* step, not a dev step.

---

### D3 — Extract the US disc first, despite US being the wrong dev target ✅

**Tension:** research says PAL rev 0 (eu0) is the reference build — all upstream
documentation is anchored to it, and NTSC-U work is explicitly discouraged
upstream pending automated symbol porting. But only US dumps were on hand.

**Decision:** extract US rev 0 anyway, immediately.

**Why:** the question it answered — *what formats does this disc actually use?* —
is region-independent. Disc layout and asset formats are identical across
revisions; only code addresses shift. So this was a zero-risk way to resolve the
single biggest open question from the research (open question #1: texture/model
formats) without waiting on a PAL download.

**Outcome:** correct call. Resolved the format question in about ten seconds of
extraction. See D6.

---

### D4 — Repo relocated to `/mnt/sdd` ✅

Originally `/home/coolroo/repos/spm-modkit` (SD card, 14 GB free). Now
`/mnt/sdd/repos/spm-modkit` (2.7 TB free).

**Why it matters:** disc extractions are ~400 MB each, and we will want several
(us0/us1/us2/eu0) plus rebuilt ISOs plus intermediate artifacts. Also relevant:
the extraction target is a spinning-disk-scale volume, not the Pi's SD card,
which the SD card would have worn under repeated rebuild cycles.

---

### D5 — Acquire PAL rev 0 for development, keep US for release targeting ✅

**Why:** eu0 has the largest symbol list by a wide margin (33,661 B), is the
zero-argument default in `spm-rel-loader`, and is what every upstream doc
describes. US rev 1 — one of the dumps we started with — has the *second
smallest* list of all eight builds (17,309 B).

Developing against eu0 and porting to US later is strictly easier than fighting
sparse symbol coverage from day one. This is not a permanent commitment to PAL;
it's choosing where to absorb the friction.

⚠️ **Not yet confirmed which PAL revision the download is.** eu0 vs eu1 matters
less than it might: PAL revisions share symbol addresses (which is why
spm-headers ships no `eu1.lst`). So either PAL rev is usable. Still worth
recording once verified.

---

### D6 — Format question resolved: SPM uses standard Nintendo TPL ✅

The research flagged "no dedicated SPM texture/model tooling" as a gap, but
explicitly labelled it an **argument from absence** and predicted the real
situation was *integration, not format research*. That prediction was correct.

**Evidence:** `spmario.tpl` and `a/p_wii_mario-` both begin `00 20 AF 30` — the
standard Nintendo TPL magic. 115 `.tpl` files ship with extensions; many more are
extensionless inside `/a`.

**Consequence for the toolkit:** do **not** invest in reverse-engineering texture
formats. Existing Wii tooling already reads TPL. The gap is wiring it up, which
is a much smaller job.

---

### D7 — RVZ is a real obstacle; WIT cannot read it ✅

The PAL download arrived as a TorrentZip containing a **`.rvz`** — Dolphin's
compressed disc image format.

Two distinct snags, worth separating:

1. **`unzip` failed** ("End-of-central-directory signature not found") but the
   archive is *fine* — `7z` lists and extracts it without complaint. This was a
   TorrentZip quirk, not a truncated download. **Lesson: don't diagnose a
   download as incomplete on one tool's say-so.** I nearly did, and started
   checking whether the file was still growing.
2. **WIT 3.01a genuinely cannot read RVZ.** It supports WDF/WIA/CISO/GCZ.
   RVZ is Dolphin-specific and postdates WIA.

**Implication:** RVZ→ISO conversion needs `dolphin-tool` from the `dolphin-emu`
package. On Debian trixie arm64 this is available but pulls a large dependency
chain (~215 packages, Qt included) for what is ultimately one CLI binary.

**Alternatives if that proves annoying:**
- Windows is available to this project — `DolphinTool.exe` ships with Dolphin there
- Some builds ship `dolphin-emu-nogui` with a lighter dependency set

**Resolved:** `dolphin-emu` installed; `dolphin-tool` lives at
`/usr/games/dolphin-tool`. RVZ→ISO took ~71 s.

📝 **Correction to my own reasoning here.** I claimed the install was "~215
packages," which pushed me to recommend Windows as a lighter path. That number
was a miscount of `apt-get --print-uris` output *lines*, not packages — the real
figure was **8**, and `/` moved 46% → 47%. The Windows recommendation was
therefore poorly founded. Recorded because the mistake was in the *measurement
method*, which is repeatable: use `apt-get install -s | grep -c '^Inst'`.

---

### D8 — eu0 confirmed and adopted as the development base ✅

`dolphin-tool header` on the PAL image: Game ID **`R8PP01`**, **Revision 0**,
Region PAL. This is exactly `eu0` — the reference build, not eu1. D5's intent is
satisfied.

**Then the decisive finding:** diffing the extracted us0 and eu0 file trees gives
**82 differences, every one an addition in eu0. There are no US-only files.**

`eu0 ⊃ us0`, strictly. This removes the last hesitation about developing on PAL —
there is no content coverage lost by doing so. The earlier framing ("choosing
where to absorb the friction") turns out to understate it: on the asset side
there is no tradeoff at all, only on the address side.

**PAL-exclusive content worth noting:** `map/go1_03.bin` (a map absent from the
US build), `rel/relD.bin` (a third REL variant), and a complete `msg/JP/`
Japanese text set on a European disc.

---

### D9 — LZ77 hypothesis strongly corroborated, still not confirmed 🔶

Having a second region made this testable in a way one build could not. All
**five** REL files across both discs begin with `0x10` and carry a 24-bit
little-endian size field yielding a **consistent 3.47–3.53× ratio**.

Five independent files, two regional builds, one tight ratio band. This is
essentially certain to be Nintendo LZ77 type-0x10.

**But it stays marked 🔶 until something is actually decompressed.** Per the
repo's own rule: an untested inference is not a finding, however good the
evidence looks. Confirming it is cheap and gates all REL work — it should be the
next real task.

**Guess already ruled out:** `relD`/`relF` are *not* German/French. The US disc
carries neither language yet ships `relF.bin`. Recorded so nobody re-derives the
dead end.

---

### D10 — LZ77 confirmed; first code written ✅

**Superseded D9's 🔶.** Wrote [`tools/lz77.py`](../tools/lz77.py); all five RELs
decompress to *exactly* their declared sizes, and every output parses as a valid
Nintendo REL v3 (module ID 1, `sectionInfoOffset` 0x4C, clean section tables).
Conclusive.

**Why this was the right first thing to build.** It was the cheapest experiment
with the largest blast radius: a ~90-line decompressor either unblocks all REL
work or invalidates the approach. It unblocked it, and produced three unplanned
findings as a side effect (below). Confirming a load-bearing assumption early
beats building on it and discovering the problem later.

**Design note:** kept as a plain module with a `decompress(bytes) -> bytes` core
and a thin CLI, rather than a script. The compressor will need to live beside it,
and the map/asset tooling will import it — so it's a library first.

⚠️ **We can decompress but not recompress.** Nothing can be rebuilt onto a disc
until an LZ77 *compressor* exists. That is now a blocking gap for any REL-editing
workflow, though the mainstream `/mod/mod.rel` injection path does not need it.

---

### D11 — Unplanned findings from the decompressed RELs ✅

Three things fell out that were not the goal:

**1. `relD.bin` is a debug build** — and a PAL disc ships it. It contains
`Debug:Stage Skip ON`, retains 34 embedded source filenames vs 21 in the retail
builds (the 13 extras include `relocatable_module.c` and the SDK's
`GXGeometry.h`), and has 23 sections vs 18–19. This is real RE value that only
exists on PAL — a second, unanticipated argument for D5/D8's choice of eu0.

**2. The map naming scheme is corroborated from a second direction.** The RELs
embed source filenames — `aa2_02.c`, `aa3_01.c`, `gn1_03.c`, `ta1_04.c` — that
mirror `map/*.bin`. Map data and map code use one naming scheme, which should
make cross-referencing scripts to code straightforward.

**3. `rel` vs `relF` is a non-question, for now.** Their string sets are 99.8%
identical and they differ by one section. Recorded as unresolved rather than
guessed at, per the repo rule.

---

### D12 — Map containers solved; the format stack is entirely standard ✅

`map/*.bin` is **LZ77 → U8 archive → members**. All 383 eu0 map files are
LZ77-headed and every one yields a Nintendo U8 archive.

**The pattern from D6 repeats, and is now a trend worth naming: SPM uses stock
Nintendo formats throughout.** TPL textures, LZ77 compression, U8 archives, REL
modules. Four format questions, four standard answers, zero bespoke formats.

**Implication for the toolkit's scope.** The value is *not* in format reverse
engineering — that work is largely already done by the wider Wii scene. It is in
**integration and workflow**: composing these layers, round-tripping them safely,
and the cross-region symbol problem. Scope the project accordingly; resist the
pull toward format archaeology.

Wrote [`tools/u8.py`](../tools/u8.py), which transparently un-LZ77s its input, so
the two layers compose without the caller thinking about it.

---

### D13 — A modding trap found before it cost anything ✅

Setup files exist in **two byte-identical copies**: standalone in `files/setup/`
*and* embedded inside some map archives (17 of the first 40). Verified by
matching SHA-256.

**Why this matters:** editing the wrong copy is a silent no-op — code that looks
right, changes that do nothing, no error anywhere. It's the most expensive kind
of bug to find by trial and error and the cheapest to find by reading the disc.

🔶 **Which copy the game loads is unresolved and is now a blocker** for any
setup-editing feature. Recorded prominently rather than discovered later.

**Also corrected a claim I made an hour ago in conversation:** I said setup files
were "exactly 11,204 bytes — a fixed-size structure," generalizing from a
six-file sample. Across all 227 there are **17 distinct sizes** (2,804–11,980 B).
The fixed-layout assumption that invited would have been wrong. Logged because
the failure mode — sampling six and saying "all" — is repeatable.

---

### D14 — LZ77 compressor written; bit-exactness attempted, not achieved 🔶

Both encoders in [`tools/lz77.py`](../tools/lz77.py) round-trip correctly against
the decompressor oracle:

| Encoder | `aa1_01` output | vs Nintendo |
|---|---:|---:|
| Nintendo (original) | 424,712 | — |
| `compress` (greedy, overlap-aware) | 425,773 | +0.25% |
| `compress` (greedy, pre-fix) | 424,955 | +0.06% |
| `compress_literals` | 1,272,969 | +200% |

**Attempting bit-exactness paid off even though it failed.** Token-diffing our
stream against Nintendo's found a real bug: at input offset 19 they emit
`(len 13, disp 3)` where we emitted `(len 3, disp 3)`. Same displacement, shorter
match — our search only looked *inside* the already-emitted window, so it could
not find **overlapping** matches that read bytes the copy itself produces. The
decompressor handled these; the compressor couldn't find them.

⚠️ **Counter-intuitive result: fixing the bug made output slightly larger**
(424,955 → 425,773), while halving runtime (19.5s → 11.5s). Not a regression in
correctness — it's that **greedy longest-match is not optimal parsing**. Taking a
longer match now can force a worse parse later. The pre-fix encoder was
accidentally better on this file. The principled fix is lazy matching (defer a
match if the next position offers a longer one), not reverting.

**Both versions are correct. Neither is bit-exact.** Nintendo's exact tie-breaking
remains unreproduced.

---

### D15 — Stop hand-rolling; evaluate existing libraries first 🔶

Prompted by the right question: *does this already exist?* It does.

| Library | Language | Notes |
|---|---|---|
| [libWiiPy](https://docs.ninjacheetah.dev/archive/lz77.html) | Python | **Wii-specific**, has an `lz77` module — and likely U8 too |
| [ndspy](https://github.com/RoadrunnerWMC/ndspy) | Python | LZ10 compress/decompress, NDS-focused |
| [nlzss](https://github.com/magical/nlzss) | Python | Dedicated Nintendo LZ compress/decompress |
| [AuroraLib.Compression](https://github.com/Venomalia/AuroraLib.Compression) | C# | Broad; explicitly covers Wii LZ77/LZ10 |
| [PyFastGBALZ77](https://github.com/LagoLunatic/PyFastGBALZ77) | Python | Speed-focused |

**This is D12's principle applied to our own code.** I wrote "resist the pull
toward format archaeology — the value is integration" and then spent a session
hand-optimizing an LZ77 encoder. Worth naming.

**Recommended position** (not yet acted on):

- **`libWiiPy` is the most promising** — Wii-specific and may cover *both* LZ77
  and U8, potentially replacing `tools/u8.py` as well.
- **Keep ours regardless, as a zero-dependency fallback and a cross-check.** It
  is ~150 lines, fully understood, and already within 0.25%. Cross-validating two
  independent implementations against the same corpus is cheap and catches real
  bugs — the overlap bug is proof.
- **Do not chase bit-exactness further by hand.** The payoff (byte-identical
  rebuilds) is real but the disc is 89% empty, so a 0.25% size delta costs
  nothing functionally.

🔶 **Open:** benchmark libWiiPy against our corpus of 383 map files + 5 RELs
before committing either way.

---

### D16 — Benchmarked. **Keep ours.** ✅ (supersedes D15's recommendation)

Ran the benchmark. The result inverted the expectation.

**Baseline metrics — `map/aa1_01.bin`, raw 1,131,524 B, Nintendo 424,712 B.**
Treat these as fixed; do not re-measure unless the encoder changes (ours is slow
enough that repeated runs are not worth the wall-clock).

| Encoder | Output | vs Nintendo | Time |
|---|---:|---:|---:|
| Nintendo (original) | 424,712 | — | — |
| **ours** — greedy, overlap-aware | **425,773** | **+0.25%** | **11.6 s** |
| ours — greedy, pre-overlap-fix | 424,955 | +0.06% | 19.5 s |
| **libWiiPy 0.6.0 L1** | **498,350** | **+17.3%** | **391.6 s** |
| ours — all-literals | 1,272,969 | +200% | ~0 s |

**Ours produces 14% smaller output, 34× faster.** Not a close call.

**Also a compatibility problem:** libWiiPy's compressor prepends a 4-byte `LZ77`
magic before the standard `0x10` header. SPM's files are bare `0x10` streams, so
its output needs the first 4 bytes stripped before the game would accept it —
its decompressor likewise expects that magic and rejects SPM files as-is.

**What libWiiPy *is* good for: an independent decompression oracle.**
`decompress_lz77` agrees byte-for-byte with ours on `aa1_01`. Two independently
written decompressors agreeing is strong evidence both are correct — keep it as a
dev-only cross-check, not a runtime dependency.

**Neither reaches bit-exactness.** libWiiPy diverges from Nintendo at byte 24;
ours at byte 23. Nintendo's exact tie-breaking is still unreproduced by anyone
we've found.

**Standing decision:** `tools/lz77.py` is the implementation. Reference
implementations are for learning and cross-validation, not for depending on.

---

### D17 — U8 writer is bit-exact across the entire corpus ✅

`tools/u8.py` gained `read_all` / `write`. Validated by
[`tools/verify_roundtrip.py`](../tools/verify_roundtrip.py):

> **383 files: 383 identical, 0 differing, 0 skipped**

Every eu0 map archive survives `LZ77 decompress → U8 unpack → U8 repack`
**byte-identically**. Not a sample — the whole corpus.

**This is the bit-exactness that eluded us on LZ77**, achieved on the container
layer. It means a modified archive differs from the original *only* where we
intended, which makes diffing a real verification tool.

**What made it work: measuring the original layout before writing any code.**
32-byte file alignment, contiguous packing, no trailing padding, `dataOffset`
aligned up from the header, and — the part that would have been guessed wrong —
**node order is a flat depth-first listing that must be preserved exactly.**
`write` therefore takes an ordered list rather than a dict or a directory tree.

**Deliberate scope limit:** the verifier does *not* exercise compression. At
~12 s/MB that would turn a ~4-minute check into hours for no extra signal about
the U8 writer. Per the repo's record-don't-re-run rule, this result stands as
recorded; re-run only if `u8.py` changes.

🔶 **Known limitation:** `_parent_index`/`_subtree_end` are O(n) per directory,
making `write` O(n²) in entry count. Irrelevant here — the corpus tops out at a
handful of entries per archive — but it would matter for a large archive. Not
optimizing until something demands it.

⚠️ **Still cannot rebuild a disc.** We can now unpack and repack archives
bit-exactly, but putting a *modified* archive back requires recompressing, and
our LZ77 output is +0.25% and not bit-exact. The container layer is solved; the
compression layer is good-enough-but-not-exact.

---

### D18 — Consolidate everything behind one CLI: `bleck` ✅

Named for Count Bleck. Full design in [`cli-design.md`](./cli-design.md).

**Why:** operations are currently spread across `wit`, `dolphin-tool`, and
several Python modules with differing conventions. A modder shouldn't need to
know that map files are LZ77-wrapped U8 archives, that rebuilds require
`--align-files`, or that node order matters. The tool should hold that knowledge.

**Design decision that fell out of D17 and shapes the interface:** unpacking a U8
archive to a plain directory **loses node order**, which bit-exact repacking
depends on — filesystems don't preserve it and directory iteration order isn't
guaranteed. So `unpack` must emit a `.bleck.json` manifest and `pack` must
consume it. Packing without a manifest still works but must *warn* that
byte-exactness isn't guaranteed.

This is a good example of why D17's corpus validation was worth doing before
designing the CLI: the ordering constraint would otherwise have been discovered
after the interface was built around directories.

**Also promoted `compress_literals` from curiosity to feature.** At ~12 s/MB, real
compression makes iteration painful; an instant `--store` mode costs 1.125× on a
disc that is 89% empty. Speed matters more than size here.

**Scope held open deliberately:** whether `build` should also handle Gecko loader
setup and `/mod/mod.rel` placement is unresolved, pending actually exercising the
REL workflow. Leaning toward a separate `bleck mod` verb rather than overloading
`build`.

---

### D19 — `bleck` implemented ✅

`tools/` became the `bleck/` package with a console-script entry point. All eight
verbs from the design work; round-trip through the CLI
(`unpack` → `pack --raw`) is **byte-identical** to the decompressed original.

**Two things changed during implementation:**

**1. `--force` moved from the top-level parser onto every subcommand.** As first
written, `bleck --force pack dir out` worked but `bleck pack dir out --force` —
the form anyone would actually type — failed with "unrecognized arguments".
Caught by testing the natural invocation rather than the one I'd written. Fixed
with a shared `parents=[common]` parser.

**2. Added `--raw` and `--keep-iso`, neither in the original design.** `--raw`
writes uncompressed U8, letting the container layer be verified independently of
the ~12 s/MB compressor; `--keep-iso` retains the ISO converted from RVZ, which
costs ~70 s to regenerate. Both exist to avoid repeating expensive work — the
same principle as the record-don't-re-run rule.

**Deliberately not done:** no test suite yet. `verify` is the de facto test
(383/383 from D17), which covers the container layer well but nothing else.
Worth real tests before the surface grows.

~~⚠️ **Untested end-to-end:** nothing here has produced a disc a real game has
booted.~~ **Resolved in D25 — a disc built by `bleck` boots and renders the
modified textures.**

---

### D20 — Package restructured; test suite added ✅

**Structure.** `cli.py` was a single 300-line module mixing parsing, dispatch,
and every command. Split by responsibility, with commands grouped by the layer
they act on:

```
bleck/
  formats/    lz77, u8, detect          — file formats
  common/     errors, fsio, manifest    — shared, no format or CLI knowledge
  backends/   disc                      — external tool wrappers (wit, dolphin-tool)
  cli/
    app.py                              — parser assembly + dispatch only
    commands/  inspect, archive, disc, stream
```

Each command module exposes `CATEGORY` and `register(add)`; `app.py` iterates
`commands.MODULES` and knows nothing about individual commands. Adding one means
adding a module and listing it — no core changes.

Also deleted the standalone `main()` functions left in `lz77.py` and `u8.py` from
before the CLI existed. Two ways to invoke the same logic is exactly the drift
this restructure exists to prevent.

**Tests.** 73 tests, **1.85 s** on the Pi. Two constraints shaped them:

- The compressor runs ~12 s/MB, so tests compress only small synthetic inputs.
  Real-data compression is marked `slow` and deselected by default
  (`addopts = "-m 'not slow'"`).
- Game data is not in the repo, so tests needing it skip cleanly. A fresh clone
  runs green.

**The suite immediately earned its place** by catching a real bug: `pack --store`
produced byte-identical output to `--raw`, i.e. it wasn't compressing at all.
Cause was conflated semantics — `--store` was treated as "don't compress", then
the manifest's `compressed: False` overrode it entirely. Now `--raw` decides
*whether* to compress and `--store` decides *which encoder*, either overriding
the source.

**Hardware note.** Raspberry Pi 4B, Cortex-A72 4×1.8 GHz, 8 GB RAM. RAM is not
the constraint (5.4 GB free); single-thread CPU is. Anything designed for this
repo should assume a slow core and plan around it rather than around memory.

---

### D21 — Enforced coding standards ✅

Full detail in [`coding-standards.md`](./coding-standards.md). Two project rules,
enforced by custom pylint plugins rather than convention, plus ruff and stock
pylint. One entry point: `./scripts/lint.sh [--fix]`.

**Rule 1 — return named types, never `dict`/`tuple`** (`C9001`). Nesting counts:
`list[tuple[str, int]]` fails. Unions, `typing.Tuple[...]`, and string
annotations are all checked.

This was not free. Existing code returned tuples in five places, each replaced
with a frozen dataclass: `Match` (lz77), `U8Item` / `_RawNode` / `_OpenDir` (u8),
`Unwrapped` / `DirectoryListing` (archive commands), `DiscInfo` / `DiscField`
(disc backend). The refactor is a genuine readability win — `match.is_usable`
reads better than `length >= MIN_MATCH` on an anonymous first element.

**Rule 2 — environment access confined to `bleck/common/env.py`** (`C9002`).
Every variable is declared once as an `EnvVar` with a description, so `DECLARED`
is the complete list of what can be configured. Scattered `os.getenv` calls are
invisible and fail silently on a typo. Wired into real behaviour rather than left
decorative: `BLECK_WIT` / `BLECK_DOLPHIN_TOOL` override tool discovery and
`BLECK_EXTRACT_ROOT` sets the default extract destination.

**Both plugins verified against a deliberate-violations file** rather than
assumed to work — bare dict, bare tuple, nested tuple, `os.environ`, `os.getenv`
all caught, and the documented escape hatch confirmed to suppress correctly.

**Two config decisions worth recording:**

⚠️ **`jobs` must stay 1.** With `jobs > 1`, pylint loads custom plugins once per
worker and reports every plugin message **twice** (verified on pylint 4.0.6).
Cost us a confusing round of double output. Parallelism isn't worth it.

**Switched to absolute imports.** Ruff's `TID252` flagged parent-relative imports
(`from ...formats import lz77`). My first instinct was to silence the rule; the
rule was right. `from bleck.formats import lz77` says where things come from
without counting dots.

**Also disabled `redefined-outer-name`** — requesting a pytest fixture shadows
its name by design, so it fired on nearly every test and flagged nothing real.

---

## Standing principles

These emerged from the above and should guide later choices:

1. **Prefer the extracted filesystem as the working representation.** ISO/WBFS/RVZ
   are transport formats. Convert once, work on files.
2. **`--align-files` is mandatory on every rebuild.** Upstream calls it out
   explicitly; omitting it breaks things subtly rather than loudly.
3. **Treat "no tool exists" claims as unverified until a file-tree check
   contradicts them.** D6 is the worked example — the gap evaporated on contact
   with the actual disc.
4. **Anchor to eu0 for anything address-dependent**, and treat US support as a
   porting problem to be solved later, ideally by automating it (which is the
   highest-leverage gap identified in research).

---

### D22 — Mods implemented: overlays, dependency chains, conflict detection ✅

Full design in [`mods.md`](./mods.md). `bleck/mods/` — manifest, registry,
resolver, overlay, conflicts, builder — plus a `bleck mod` command group.
113 tests, 10.00/10 lint.

**Verified against real game data**, not just fixtures:

- A mod editing `lyt/title.bin.uk/arc/timg/mario.tpl` produced a staged disc
  differing from the base in **exactly one file**, with the archive's other
  **34 members byte-identical and node order preserved**.
- The **base stayed pristine** — still 0 differences against a fresh ISO extract
  after builds.
- Two mods in a chain editing **different members of the same archive** merged
  cleanly, both edits present.
- Two **independent** mods editing the **same member** produced a conflict with
  byte ranges and a non-zero exit.

**Bugs the tests caught, both real:**

⚠️ **Dependency filtering existed in only one of two code paths.** Conflict
detection dropped edits superseded by a dependent mod, but the builder did not —
so a mod overriding its own dependency reported clean, then hit a phantom
conflict during staging and silently kept the base file. Fixed by promoting the
filter to a shared `effective_edits`, used by both. Two code paths reasoning
independently about the same question is the underlying smell.

⚠️ **The D13 duplicate-setup warning never fired**, because it matched
`setup/...` while real disc paths carry the `files/` prefix. A warning that
cannot trigger is worse than none — it reads as "checked, fine."

**Design decisions worth recording:**

- **Hardlink staging.** Unchanged files are hardlinked from the base, so a build
  writes only what differs. `_detach` breaks the link before any write — writing
  through a hardlink would edit the base in place, the exact failure this design
  exists to prevent. Verified: untouched staged files show link count 2, edited
  ones 1. Falls back to copying across filesystems.
- **`BuildContext`** groups the five values every build helper needs. Pylint
  flagged six-positional-argument functions; the fix was a named type rather
  than raising the limit — the same rule we apply to returns.
- **`ModSpec` in tests** for the same reason: an 8-parameter helper became a
  frozen dataclass instead of an exemption.
- **Overlays mirror the extract root**, so `sys/main.dol` is moddable, and the
  directory is `overlay/` so paths read `overlay/files/...` rather than
  `files/files/...`.

**Open-question calls made** (from mods.md): manifests committed, overlay
contents gitignored (they contain extracted game assets); ISO output — 26 s
proved acceptable, and `--no-iso` covers fast iteration; no `unvendor`; binary
merge opt-in; `"remove"` supported.

~~⚠️ **Still nothing has booted.**~~ **Resolved in D25 — confirmed on real
hardware-equivalent emulation.**

---

### D23 — RVZ output, and the Pi can boot after all ✅

**Dolphin boots SPM on the Pi 4.** The earlier assumption that emulation was
out of reach here was wrong — `dolphin-emu-nogui -p headless -v Null` reaches
`Active title: Super Paper Mario (R8PP01)`, fakes Wii BS2, and the apploader
loads `main.dol` and the RELs via a series of `DVDRead`s. With
`Logger.Logs.FILEMON=True` it then names every asset the game reads
(`sound/wiimario_snd.brsar`, `msg/UK/global.txt`, `sptexture.tpl`, …), which is
a precise instrument for confirming a modded file is actually loaded.

⚠️ **But it is too slow to reach the title screen**, and a Null video backend
shows no picture — so visual confirmation of a texture change is not possible
here. Emulation validation belongs on a desktop; the Pi run is a smoke test that
proves the disc is bootable and readable.

**Hence RVZ output.** A 4.5 GB ISO is painful to move to another machine; RVZ is
Dolphin-native and ~18× smaller.

    bleck mod build title-invert out.rvz     # 4,482 MB -> 249 MB in ~50s

Format is **inferred from the output extension**, with `--format {iso,rvz}` to
override — less to remember than a flag. `wit` can only write ISO, so RVZ goes
through a temporary ISO that is removed afterwards (`--keep-iso` retains it).

**Three bugs found while wiring this up:**

⚠️ **The staging ISO shadowed the output path.** Using `out.with_suffix(".iso")`
collided with a real `spm-modded.iso` the user already had, and `wit` refuses to
overwrite. Now a hidden `.{stem}.staging.iso`.

⚠️ **`dolphin-tool` needs block size and compression stated explicitly** for RVZ
("Block size must be set for GCZ/RVZ/WIA"). Now 128 KiB / zstd / level 5 —
level 5 rather than the 19 seen on retail dumps, since 19 costs far more time
for a few percent, the wrong trade for an iteration artifact.

⚠️ **`bleck info` would have slurped a whole disc image into memory.** `wit`
cannot parse RVZ, so `identify` returned empty and the code fell through to
byte-level format sniffing — reading 249 MB to guess at a format. Now disc
images are identified by extension, RVZ headers come from `dolphin-tool header`,
and unrecognised images say so instead of being read.

---

### D24 — WBFS output, because RVZ needs a recent Dolphin ✅

Dragging our RVZ onto Dolphin on Windows produced *"Is an invalid GCM/ISO file,
or is not a GC/Wii ISO"* — Dolphin's generic unrecognised-format message.

**Cause: RVZ requires Dolphin 5.0-12188 (2020) or newer.** The last *stable*
release, 5.0 from 2016, predates the format entirely and is still what many
people have installed. Our file was fine — `dolphin-tool header` reads it, and
the local `dolphin-emu-nogui` is a 2025 build, so the Pi never saw the problem.

**Lesson worth generalising: "it works here" says nothing about the consumer's
toolchain**, and picking the newest format by default optimised for size at the
cost of the thing actually being openable.

**Added `wbfs` as a third format.** ~424 MB — larger than RVZ's ~249 MB, much
smaller than a 4.5 GB ISO — and supported by Dolphin for many years. `wit`
writes it directly, so no intermediate ISO is needed.

    bleck mod build title-invert out.wbfs     # 18s, 424 MB, universally readable

Verified the mod survives the WBFS path, not just that the container parses:
extracted the built WBFS and confirmed **both** modified members
(`arc/timg/mario.tpl`, `arc/timg/koopa.tpl`) present, 35 members preserved, node
order intact.

**Format guidance:** wbfs to share, rvz when the target Dolphin is known-recent,
iso only when something demands it.

---

### D25 — END-TO-END VALIDATED: a bleck-built disc boots and renders the mod ✅

**Confirmed visually in Dolphin on Windows: the Super Paper Mario title screen
shows Mario and Bowser with inverted colours.**

This closes the assumption every other decision rested on. The full chain works:

```
LZ77 decompress → U8 unpack → replace member → U8 repack
  → LZ77 RE-COMPRESS → disc rebuild → game loads and renders it
```

**The specific question answered: bit-exact compression is NOT required.** Our
greedy encoder produces a stream ~0.25% larger than Nintendo's with entirely
different token boundaries (D16), and the game accepts it without complaint.
That retires the open worry from D16 and D19 — matching Nintendo's exact
tie-breaking would be satisfying, but it is not necessary.

**Also validated in the same run**, since the shipped mod was a two-mod chain:

- **Dependency resolution end-to-end.** `tex-koopa → title-invert` linearised,
  and *both* mods' edits appear on screen — Bowser from the dependency, Mario
  from the target.
- **Archive-aware merging against the real game.** Two mods edited different
  members of one archive; both landed, and the other 33 members were untouched
  enough that the title screen rendered normally.
- **The immutable-base design.** The base was never written to, yet the built
  disc is correct.

**What this means going forward:** the asset pipeline is proven, not
provisional. Work built on it — `map.dat` internals, texture tooling, the REL
workflow — no longer carries the risk that the foundation is silently wrong.

**Remaining known-unknowns are now much narrower:**

- 🔶 Which setup-file copy the game reads (D13) — still unresolved, still warned
  about at build time.
- 🔶 `rel.bin` vs `relF.bin` (D11).
- ⚠️ Untested: whether a *large* number of modified archives, or edits to
  `main.dol`/RELs, behave as well as one archive did.

---

### D26 — PowerPC toolchain works without devkitPPC ✅

**A distro cross-compiler produces a valid REL.** devkitPPC is unobtainable here
(`apt.devkitpro.org`: 403, empty arm64 package lists), so this was the gating
question for code mods. Debian's `gcc-powerpc-linux-gnu` 14.2.0 answers it.

Full recipe and verification in [`code-mods.md`](./code-mods.md).

**The one non-obvious requirement: `-fno-pic -fno-PIE`.** Debian's GCC defaults
to PIE and devkitPPC does not, so without these it emits `R_PPC_REL16_HA`
(type 252) relocations and `pyelf2rel` fails with
`UnsupportedRelocationError: Unsupported relocation type 252`. With them, only
`R_PPC_ADDR16_HA/LO` and `R_PPC_REL32` appear. This would be genuinely hard to
guess from the error message alone.

Only `-mgcn` of the upstream flags is rejected — devkitPPC-specific multilib
selection, safely dropped since `-mcpu=750 -meabi` are explicit.

**Two upstream findings that simplify the design:**

- **`pyelf2rel` (PyPI 1.0.9) replaces the C++ `elf2rel`.** Upstream's Makefile
  wants `$(TTYDTOOLS)/bin/elf2rel`, a binary the user must build. The same
  author's Python port installs cleanly and exposes an importable API, so
  `bleck` can call it in-process.
- **The Gecko loader ships pre-assembled** in `spm-rel-loader/loader/*.txt`, one
  per region — a `C2` insert at `0x8023E5FC` for eu0/eu1 with `./mod/mod.rel`
  embedded as ASCII. No assembler needed; it is data we can ship.

**Nice cross-validation:** `bleck info`, written to parse the *game's* RELs,
correctly identifies our freshly built one as `REL v3 (13 sections)`. Two
independently-written pieces agreeing.

⚠️ **Structural validity is not runtime correctness.** devkitPPC targets
`powerpc-eabi`, Debian's targets `powerpc-linux-gnu` (SysV). ABI differences
could still produce code that builds and misbehaves. Must be proven by booting,
as the asset pipeline was in D25.

⚠️ **`g++-powerpc-linux-gnu` is not installed** and upstream uses C++17.

⚠️ **Licensing is unresolved and blocks vendoring.** `spm-rel-loader` is GPLv3
including the loader code; `spm-headers` is MIT except its `mod/` folder. `bleck`
is unlicensed. Decide before copying any upstream code into this repo.

---

### D27 — Windows 11 support ✅

The CLI now targets Windows as well as Linux. Four real portability gaps, none
of which would have shown up on this host:

**1. Tool names differ.** Dolphin ships `dolphin-tool` on Linux but
`DolphinTool.exe` on Windows, so `shutil.which("dolphin-tool")` would simply
fail there. Replaced the flat name/hint constants with a `ToolSpec` carrying
per-platform executable names, search directories, and install hints. Windows
looks in `C:\Program Files\Dolphin` and friends; POSIX keeps `/usr/games`
(where Debian hides it off PATH). Errors now list what was tried and name the
`BLECK_WIT` / `BLECK_DOLPHIN_TOOL` override.

**2. `scripts/lint.sh` was bash-only.** Logic moved to `scripts/lint.py`, with
`lint.sh` and a new `lint.ps1` as thin wrappers. Both find the venv in its
platform-appropriate location (`bin/` vs `Scripts/`). ANSI colour is suppressed
on Windows consoles that would render it as garbage.

**3. ⚠️ `_detach` relied on `st_nlink`, which Windows does not report reliably.**
This was the dangerous one. Staged files are hardlinks to the base; `_detach`
broke the link before writing by checking `st_nlink > 1`. If Windows reports 1
for a hardlinked file, that check silently passes and the write goes **straight
through to the base** — corrupting the one thing this whole design protects.
Now unlinks unconditionally: cheap, and it cannot get this wrong.

**4. Windows refuses to delete read-only files.** `shutil.rmtree` on a staging
tree inherited from a read-only base would fail. Added `builder.remove_tree`
with an `onexc` handler that clears the read-only bit and retries.

**Testing approach:** `tests/test_platform.py` (21 tests) exercises the Windows
paths *on Linux* by patching `disc.IS_WINDOWS`, plus filesystem behaviours that
are genuinely testable here — read-only removal, hardlink failure fallback, a
full build with `os.link` monkeypatched to raise, posix-style path storage, and
CRLF manifest parsing. A Windows regression should surface here rather than on a
user's machine.

⚠️ **Not actually run on Windows yet.** These are informed fixes and simulated
tests, not confirmation. The honest status is "should work"; running `bleck`
on Windows 11 is what would make it "does".

---

### D28 — Roadmap and Windows setup written down ✅

Added [`roadmap.md`](./roadmap.md) (forward-looking: what to build next, what
blocks what) and [`windows.md`](./windows.md) (setup for the Windows target).
The decision log stays backward-looking; the two do not overlap.

**The state worth stating plainly:** the asset pipeline is finished and proven
(D25). Code injection is the active track, and its toolchain is proven (D26) but
nothing has been integrated or run.

**Ordering, and why:**

1. **Licensing first** — `spm-rel-loader` is GPLv3 including the Gecko loader,
   and `bleck` is unlicensed. Nothing upstream has been copied into this repo
   yet; the clones are in scratchpad deliberately. Unwinding a licensing mistake
   later is much worse than deciding now.
2. **`g++-powerpc-linux-gnu`** — cheap, and upstream is C++17.
3. **One hook actually running** — this is the code track's D25. Until a REL we
   built demonstrably *runs*, everything above it rests on an untested
   assumption, and the risk is specific rather than vague: Debian's compiler
   targets SysV, devkitPPC targets `powerpc-eabi`, so code can build cleanly and
   misbehave.

**Also noted as newly unblocked by D25:** the setup-file duplication (D13) and
the `rel.bin`/`relF.bin` question (D11) both needed a bootable game to settle,
and now have one. D13 in particular is worth doing — a build-time warning that
says "we don't know which copy the game reads" is a confession, not a feature.

**Deferred with reasons recorded** rather than dropped: `map.dat` needs a
visualiser before editing is tractable (the feedback loop is otherwise "rebuild
400 MB, boot, squint"), and cross-region symbol porting — the highest-leverage
gap in the wider ecosystem — only matters once there is code worth porting.
