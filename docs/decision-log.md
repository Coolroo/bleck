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

---

### D29 — uv project, with a committed lockfile ✅

Adopted [uv](https://docs.astral.sh/uv/) for dependency management. `pyproject.toml`
was already PEP 621, so this was mostly additive: `uv.lock` is generated and
**committed**, and `uv sync --extra dev` reproduces the environment exactly.

**Why, concretely — not fashion:**

- **We had no lockfile, and version drift has already bitten us.** pylint 4.0.6
  duplicates plugin messages with `jobs > 1` (D21); our config works around it.
  Without pinning, that resurfaces silently on someone else's machine.
- **`uv run` removes venv activation**, which materially simplifies the Windows
  instructions — no `Activate.ps1`, no execution-policy workaround (D27/windows.md).
- Installs are fast, which matters on this hardware.

**Fixed a real gap while migrating: `pyelf2rel` was installed but declared
nowhere.** I pulled it in ad hoc during the D26 toolchain work and never added
it to `pyproject.toml`, so a fresh clone would not have had it. Now in `dev`
extras, with a note that it becomes a *runtime* dependency when code mods land.
Exactly the class of mistake a lockfile prevents.

⚠️ **`bleck` still has zero runtime dependencies** and should stay that way where
practical — it is a toolkit people install to use, not a library.

**Also surfaced a test fragility.** `tests/test_platform.py` imports helpers from
`tests/test_mods.py`, which worked only because `python -m pytest` happens to put
the CWD on `sys.path`. Under `uv run pytest` — or a bare `pytest` — collection
failed with `ModuleNotFoundError: No module named 'tests'`. Fixed with
`pythonpath = ["."]` in the pytest config rather than by mandating one runner.
The suite now passes under `uv run pytest`, bare `pytest`, and `python -m pytest`.

**Both workflows are supported.** uv is recommended; `pip install -e ".[dev]"`
still works, and `scripts/lint.py` finds the venv either way.

---

### D30 — Platform differences extracted into a profile layer; macOS supported ✅

Windows support (D27) had scattered `IS_WINDOWS` conditionals through
`disc.py` and `builder.py`. Adding a third OS that way would have been the point
where it turned into a mess, so the differences moved into data first.

```
bleck/platforms/
  base.py       PlatformProfile / ToolLocation types
  linux.py      PROFILE
  macos.py      PROFILE
  windows.py    PROFILE
  __init__.py   selects one at import; unknown systems fall back to Linux
```

Supporting another OS is now "add a module with a `PROFILE` and list it" —
nothing in `disc.py` or `builder.py` changes.

**macOS differs in three ways that are easy to miss from a Linux box:**

1. **Dolphin is an application bundle**, so `DolphinTool` lives inside
   `Dolphin.app/Contents/MacOS/` and is not on PATH. `shutil.which` alone would
   never find it.
2. **Homebrew's prefix depends on the CPU** — `/opt/homebrew` on Apple Silicon,
   `/usr/local` on Intel. Both are searched.
3. ⚠️ **Finder creates `.DS_Store` files** in any directory a user browses, and
   non-native volumes collect `._` AppleDouble sidecars. Browsing an extracted
   disc would otherwise stage that clutter into a rebuilt image — files the real
   game never shipped. Now filtered from both staging and mod overlays, **on
   macOS only**: doing it everywhere would hide genuine mistakes.

That third one is the kind of bug that produces a subtly wrong disc and no error
message, which is why it is handled rather than left to chance.

**A test caught a real inconsistency:** every tool hint names its `BLECK_*`
override except Linux's `wit`, which just said "sudo apt install wit". Fixed
rather than exempted.

**Verified after the refactor:** the real title-screen mod still builds, the base
is still pristine (0 differences), and a simulated macOS staging run excludes
`.DS_Store` and `._real.bin` while keeping `real.bin`.

⚠️ **Never run on macOS.** Same status as Windows — informed implementation plus
tests that exercise the paths from Linux.

145 tests.

---

### D31 — User documentation on Mintlify, in `docs-site/` ✅

Added an 18-page Mintlify site. **Two doc trees now exist, with different
audiences, and conflating them would ruin both:**

| | Audience | Contents |
|---|---|---|
| `docs/` | Maintainers | Why choices were made, what is true about the disc |
| `docs-site/` | Users | Install, usage, guides, CLI reference |

The decision log is a research record — full of rejected alternatives, byte
magics and self-corrections. That is exactly what a *maintainer* needs and
exactly what a *user* does not. Keeping them separate lets each stay honest
rather than becoming a compromise.

**Structure:** Get started → Installation (per-OS) → Concepts → Guides →
Reference → Contributing.

**Per-OS coverage is the point.** Installation has a page each for Linux, macOS
and Windows, and `<Tabs>` are used wherever instructions genuinely diverge —
quickstart, dev setup, and testing. The testing page has a fourth tab for
Raspberry Pi, including the headless `dolphin-emu-nogui` invocation with
`FILEMON` logging and the `timeout -k` wrapper Dolphin needs because it ignores
plain SIGTERM.

**Validated what could be validated here.** A script checks that every
navigation entry exists on disk, every page has frontmatter, nothing is orphaned
from the nav, and every internal link resolves — 18/18 clean.

⚠️ **Never rendered.** Node is not installed on this host, so `mint dev` has not
run. Structure and links are verified; visual output is not.

**Status callouts are deliberate and load-bearing.** macOS and Windows pages
lead with "not yet verified on this platform", and the code-mods guide opens
with "not integrated into the CLI". `docs-site/README.md` explicitly says not to
quietly drop them — documentation that overstates readiness is worse than none,
because it costs someone an afternoon before they discover the truth.

---

### D32 — Docs site uses bun; handoff written for the move to Windows ✅

**bun instead of npm** for `docs-site/`. `package.json` adds `dev` and `check`
scripts, and `bun.lock` is committed for the same reason `uv.lock` is — everyone
resolves the same Mintlify version.

Installing it paid off immediately: `bun run check` is **Mintlify's own
broken-link validator**, and it passes. That is stronger than the script check
from D31, which only confirmed that link targets existed as files.

⚠️ **The dev server still has not run.** Deliberate — visual verification moves
to the Windows machine, where Dolphin also runs at full speed.

**Added [`handoff.md`](./handoff.md)** for continuing on another machine. It
captures what the other docs do not: which decisions are still open, what exists
only on the Linux box and is therefore absent from a fresh clone, and the
non-obvious traps.

The one most likely to waste someone's time: **the committed mods will look
empty, and that is correct.** `mods/*/overlay/` is gitignored because it holds
extracted game assets, so `bleck mod status title-invert` reports "overrides
nothing yet" on a fresh clone. The handoff gives the two `vendor` commands that
restore them.

**A genuine improvement for the Windows move:** devkitPPC installs normally
there, so the ABI risk flagged in D26 — Debian's SysV target versus devkitPPC's
`powerpc-eabi` — largely disappears. Building code mods on Windows is the better
path, not merely a fallback.

---

## 2026-07-27

### D33 — `bleck` actually runs on Windows 11; the simulated tests held ✅

**Supersedes the ⚠️ callouts in D27 and D30.** Windows portability was
"informed fixes plus tests that simulate the Windows paths from Linux" through
three decision entries. It has now been executed on the target.

Host: Windows 11 Home 10.0.26200, aarch64→x64 irrelevant here, repo on `W:\`.

```
uv sync --extra dev        24 packages, CPython 3.13.14
uv run pytest              142 passed, 3 skipped in 1.00s
uv run python scripts\lint.py   ruff format ok · ruff check ok · pylint 10.00/10
uv run bleck --help        all nine verbs listed
```

**Zero failures, zero fixes required.** 142+3 is the full 145 from D30 — the
three skips are the game-data tests, correct on a clone with no `extracted/`.

**Why this is worth recording rather than shrugging at.** The prediction being
tested was not "Python is portable"; it was that four *specific* hazards had
been correctly identified and handled from a machine that could not exercise
them (D27): tool-name divergence, bash-only lint entry point, `st_nlink`
unreliability, and read-only deletion. Simulating a platform you cannot run on
is exactly the kind of work that quietly fails, and the honest prior was that
something would break. Nothing did.

**The generalisable point:** D27's `tests/test_platform.py` — patching
`disc.IS_WINDOWS` to drive the Windows branches from Linux — was worth writing.
It is tempting to dismiss simulated cross-platform tests as theatre. This is one
data point that they are not, and it argues for extending the same treatment to
macOS rather than waiting for a Mac.

⚠️ **Scope of the claim, precisely.** This validates the *pure-Python* layers:
formats, mods, manifests, path handling, the CLI surface. It does **not** touch
the external-tool paths, because neither `wit.exe` nor `DolphinTool.exe` is
installed on this host yet — so `extract` and `build` remain unexercised on
Windows, and the `ToolSpec` search-directory work from D27 is still unproven
there. That is the next thing to confirm, not an afterthought.

**Also corrected:** `windows.md` said "expect 134 passed" and `roadmap.md` cited
134 — both stale since D30 added the platform-profile tests. The count is 145.
A setup doc that reports the wrong number trains readers to ignore it.

**Fresh-clone state on this machine, for the record:** no `roms/`, no
`extracted/`, no `build/`, and `mods/{title-invert,tex-koopa}` present as
manifests with no overlay — all expected and documented in `handoff.md`. Absent
from the host: `wit`, `DolphinTool`, `bun`/`node`, devkitPPC.

---

### D34 — eu0 re-confirmed on Windows, without any external tool ✅

Six dumps supplied to `roms/` on the Windows box. The PAL one is a `.zip`
containing **`.rvz`** — the same shape as the D7 download, so the same
constraint: `wit` cannot read it and `dolphin-tool` must convert first.

**Identified the disc with zero external tooling**, which D23 assumed required
`dolphin-tool header`:

```
Game ID   R8PP01      Disc 0      Revision 0
Wii magic 0x5D1C9EA3  Title "SUPER PAPER MARIO"
ISO size  4,699,979,776 bytes
```

**This is `eu0`** — the same reference build as D8, from a different source and
verified independently. The development base is in place on Windows.

**The method is the finding, and it is reusable.** RVZ/WIA stores the disc's
first 0x80 bytes **uncompressed** inside its container: a 0x48-byte
`WIAFileHeader`, then `WIADisc` whose first four big-endian `u32`s are followed
at **offset 0x58** by the verbatim disc header. So game ID, disc number,
revision, magic and title are all readable with a 216-byte sequential read —
straight out of the zip entry, no full extraction, no Dolphin.

🔶 **Concrete improvement this enables:** `bleck info` currently shells out to
`dolphin-tool header` for RVZ (D23). It could read offset 0x58 directly and work
on a machine with **no Dolphin installed at all**. Pure Python, no new
dependency, and it removes an external-tool requirement from the one command
whose whole job is "tell me what this file is." Not yet implemented.

### ⛔ Do not install Dolphin from winget

`winget search --id Dolphin` offers `DolphinEmulator.Dolphin` at version
**`5.0`** — the June 2016 stable release. That is precisely the build D24
diagnosed: it **predates the RVZ format entirely** and rejects RVZ files as
*"Is an invalid GCM/ISO file, or is not a GC/Wii ISO"*.

🔶 Additionally, `DolphinTool.exe` is believed not to ship in 5.0 stable at all —
it is a much later addition. Either way the winget package cannot serve this
project's needs.

**Get a beta or development build from `dolphin-emu.org/download` instead.**

**This is D24's lesson recurring through a new door.** D24 was about what the
*consumer's* Dolphin could open; this is about what the *developer's* package
manager silently installs. Same root cause — the default-looking option is
ten years stale — and it would have presented as "our RVZ is corrupt" rather
than "your Dolphin is too old". Recorded so the next person does not spend an
afternoon on it.

**Also confirmed:** `.gitignore:2` covers `roms/`, so ~2.1 GB of dumps are
correctly invisible to git. W: has 811 GB free, ample for the 4.7 GB
intermediate ISO plus the ~400 MB extraction.

⚠️ **Still blocked on tooling:** `wit.exe` (manual download from
`wit.wiimm.de`, not on winget) and a recent `DolphinTool.exe`. The four USA
dumps are `.7z` and need 7-Zip to open; low priority, since eu0 is the
development base (D5, D8).

---

### D35 — Full pipeline runs on Windows; one real bug found doing it ✅

**Closes the caveat D33 left open.** `extract`, `verify` and the external-tool
paths now all work on Windows against real game data.

**Toolchain installed**, both outside the repo under `C:\Users\Wyatt\tools\`:

| Tool | Version | Notes |
|---|---|---|
| `wit.exe` | **3.05a r8638** (2022-08-27) | newer than the Pi's 3.01a; cygwin64 build, self-contained in `bin/` |
| `DolphinTool.exe` | **Dolphin 2606** (2026-06-25) | from the update API, *not* winget — see D34 |
| `7zr.exe` | 26.02 | standalone, no elevation; Dolphin ships as `.7z` |

**Dolphin's download page 403s scrapers, but `dolphin-emu.org/update/latest/beta`
returns JSON** listing artifacts per system. That is the reliable way to get a
current build URL. **`DolphinTool.exe` is present in 2606**, which confirms
D34's 🔶 suspicion that winget's 5.0 would not have shipped it at all.

---

#### ⚠️ The bug: `bleck extract` fails on any machine without `extracted/`

The documented fresh-machine command from `windows.md` —

```
bleck extract "…(En,Fr,De,Es,It).rvz" extracted\eu0
```

— failed with:

```
bleck: DolphinTool.exe failed:
Error: Conversion failed
```

**Cause:** `extract` computes its temporary ISO as `dest.parent / f"{stem}.iso"`
and converts *before* anything creates `dest.parent`. On a fresh clone
`extracted/` does not exist, DolphinTool will not create a missing parent, and
it reports the failure as bare "Conversion failed" — **naming neither the path
nor the reason**. Confirmed by `mkdir extracted` and re-running the identical
command: exit 0 in 4 s.

**This is not a Windows bug.** It reproduces identically on Linux. It survived
this long because the Pi extracted us0 first (D3), which created `extracted/`
before any RVZ was ever converted — so the failing path was never taken there.
**A bug hidden by the order two commands happened to run in, months earlier.**

**Fixed** by adding `_ensure_parent` and calling it from all three write paths —
`convert_rvz`, `convert_to_rvz` and `build`. `build_image` and `extract` inherit
the fix. `build` had the same latent gap: `bleck mod build … out/x.wbfs` into a
non-existent `out/` would have failed the same opaque way.

**Tests:** new `tests/test_disc.py` (5 tests). They assert the parent existed
**at the moment the tool was invoked**, not afterwards — checking after the fact
would pass even if the directory were created too late, and ordering is the
whole bug. Verified non-vacuous by neutralising `_ensure_parent` and confirming
they fail. Placed in a new file rather than `test_platform.py`, whose docstring
scopes it to cross-platform behaviour; this is plain backend behaviour.

⚠️ **Gotcha that cost a cycle:** `setx` writes the user registry, but already-running
processes keep their inherited environment block. `BLECK_WIT` was set and still
invisible to the very next shell. Set `$env:` inline for the current session;
`setx` only helps new ones.

---

#### eu0 extracted and cross-checked against the recorded facts

2,722 files, 0.39 GB. Every published figure matches:

| Check | Found | Recorded |
|---|---|---|
| `map/*.bin` | 383 | 383 (D12) ✅ |
| `setup/` files | 227 | 227 (D13) ✅ |
| `rel/` | `rel.bin`, `relD.bin`, `relF.bin` | three, incl. PAL-only debug (D11) ✅ |
| `map/go1_03.bin` | present | PAL-only (D8) ✅ |
| `msg/JP/` | present | JP text on a EU disc (D8) ✅ |
| `.tpl` with extension | **130** | **115 (D6)** — see below |

**The `.tpl` discrepancy is not a discrepancy.** ✅ The extra files sit in
European language directories — `eff/nl` (Dutch), `eff/it`, `eff/ge` — which a
US disc would never ship. 🔶 **D6's 115 was almost certainly measured on us0**,
inferred from chronology: D3 extracted US first and D6 predates the eu0
extraction in D8. Not verified by re-counting us0, which would cost a 400 MB
extraction for a footnote.

📝 **D6 should have said which build it counted.** A bare number with no build
attached reads as a contradiction on the next machine, and cost a detour here.
Region-varying counts need their region stated.

#### Round-trip verified on real data

```
bleck verify extracted/eu0/files/map
383 files: 383 identical, 0 differing, 0 skipped        18.5 s
```

**D17's corpus result reproduced exactly, on Windows.** LZ77 decompress → U8
unpack → U8 repack is byte-identical across all 383 archives on a second
platform.

#### Recorded timings — do not re-measure

Windows 11 desktop vs the Pi 4 (D16, D17, D20). Same operations, same data.

| Operation | Windows | Pi 4 |
|---|---:|---:|
| RVZ → ISO (4.38 GB out) | **4 s** | ~71 s |
| `wit EXTRACT` data partition | **4.7 s** | — |
| `verify` 383-file map corpus | **18.5 s** | ~4 min |
| Full test suite | **1.0 s** | 1.85 s |

**Roughly 13–18× on I/O-bound disc work.** This materially changes what is
practical: the "rebuild a 400 MB disc, boot, squint" loop that made `map.dat`
editing untenable (roadmap, *Deliberately deferred*) is far less painful here.
Worth revisiting that deferral on this hardware — the reasoning was sound on a
Pi and may simply not hold on a desktop.

**Test suite is now 150, with zero skips** — the three game-data tests that skip
on a bare clone now have `extracted/eu0` to run against. pylint 10.00/10.

---

## D36 — A built disc boots on Windows; `bleck launch` closes the loop

*2026-07-27*

### D25 reproduced on a second platform ✅

`title-invert` (which depends on `tex-koopa`) was re-vendored, inverted, built
and booted on Windows. **Both textures render inverted on the title screen** —
confirmed visually. The asset pipeline is now verified end to end on two
platforms, not one.

The build is fast enough to change how it feels to work:

| Step | Time |
|---|---:|
| `mod build` — stage, merge archive, write 424 MB WBFS | **4.4 s** |
| Full-tree hash diff of build vs base (2,722 files) | 3.9 s |

**4.4 seconds** for edit → bootable disc. On the Pi this was minutes. This
reinforces D35's note that the `map.dat` deferral deserves revisiting.

### The build was byte-verified, not just eyeballed ✅

Hashing every file in the staged tree against the base:

- **1 of 2,722 files differs** — `files/lyt/title.bin.uk`, exactly the archive
  the chain targets. Nothing else moved.
- Inside that archive: **2 of 31 members changed** (`mario.tpl`, `koopa.tpl`),
  both byte-identical to the vendored overrides. The other 29 repacked
  unchanged.
- The base is untouched, as designed.

This is the first time the overlay merge has been checked at file-hash level
rather than by looking at the screen. It holds.

### `bleck extract`'s parent-directory fix is real ✅

The build wrote into `out\`, which did not exist. It succeeded. That path had
only ever been exercised by a unit test with a stubbed `_run`, so this is the
first confirmation against actual `wit`.

### Decision: `bleck launch` is a first-class command

**Why at all** — every other step of the loop was a `bleck` command and the last
one was "go find Dolphin and open the file". Closing that is what makes
`bleck mod build my-mod out.wbfs --launch` a single iteration.

**The emulator is a separate tool key from `dolphin-tool`.** ⚠️ `Dolphin.exe` and
`DolphinTool.exe` ship in the same folder and neither can do the other's job.
They are declared as distinct entries in the platform profiles
(`platforms.DOLPHIN` vs `platforms.DOLPHIN_TOOL`) with a separate `BLECK_DOLPHIN`
override, and a test asserts no platform ever lists the same executable name
under both.

⚠️ **On Linux, never search for a binary called `dolphin`.** That is KDE's file
manager, and it is installed on a great many desktops. The emulator is
`dolphin-emu`. Searching the obvious name would silently open a file browser —
a failure that looks like `bleck` malfunctioning rather than like a missing
dependency. Guarded by a test.

**Rejected: blocking until the emulator exits.** A build-and-boot loop wants its
shell back. `launch` returns as soon as Dolphin starts (~0.2 s) and reports the
PID; `--wait` is available for scripting, where the exit code is the point.

**Rejected: `--exec=<path>`.** ⚠️ Dolphin's joined argument form has to be quoted
by whoever builds the command line, and a path arriving with its quotes still
attached makes Dolphin report:

> Could not be opened! This may happen with improper permissions, or use by
> another process.

This cost real debugging time here — the message blames permissions and the file
was fine. It was reached through PowerShell's
`Start-Process -ArgumentList '--exec="..."'`, which forwards the quotes
literally. The two-token `-e <path>` form cannot be misquoted, so that is what
`bleck` emits, asserted by a test.

**Dolphin's `-b` (batch) verified** ✅ — boots straight into the game with no
game-list window. Exposed as `--batch`.

### Also recorded

- **`DolphinTool verify` reports three Low-severity problems on every disc
  `bleck` builds** ✅ — missing update partition, unsigned DATA partition, and a
  format that does not store the disc size. All three are expected consequences
  of `--psel data` + modification + WBFS scrubbing. None prevent booting. Noted
  because "Problems Found: Yes" reads alarming and is not.
- **Built disc images are now gitignored.** `out/`, `*.iso`, `*.rvz`, `*.wbfs`.
  The docs tell users to build `out.wbfs` in the repo root, and nothing stopped
  a 424 MB accidental commit.

**Test suite is now 164** (150 → 164; 14 new across `test_emulator.py` and the
platform profiles). pylint 10.00/10, with one deliberate suppression —
`consider-using-with` on the `Popen` call, verified as genuinely required, since
the emulator must outlive the CLI process.

---

## D37 — A scripting language, by compiling to the game's own VM (2026-07-27)

**The finding that decided this: Super Paper Mario already contains a bytecode
interpreter, and it is thoroughly documented upstream.** ✅

`evt` — `evtmgrMain()` runs it every frame. Verified from
`spm-headers/include/spm/evtmgr_cmd.h` and `evtmgr.h`:

- **120 opcodes**, `0x00`–`0x77`, every one named in `enum EvtOpcode`
- **Cooperative scheduling** across up to 128 concurrent entries
  (`EVT_ENTRY_MAX 0x80`), with documented yield semantics
  (`EVT_RET_BLOCK_WEAK`, `EVT_RET_END_FRAME`, …)
- **~444 native builtins** declared across 26 `evt_*.h` headers; 302 with known
  arity, many with commented signatures
- **Scripts are data.** `EvtScriptCode *` is a field on `MobjEntry`,
  `ItemEntry`, `NPCEntry`, `map_data`, doors and cases. 71 existing in-game
  scripts are named and addressed
- **345 of `spm.eu0.lst`'s 1111 symbols are `evt_*`** — the best-covered part of
  the symbol map

The instruction encoding is fully specified: header word
`(argc << 16) | opcode`, then arguments whose **numeric range encodes the
storage class** (`EVTDAT_LW_BASE 30000000`, `EVTDAT_FLOAT_BASE 240000000`, …).
Floats are fixed-point, `value * 1024`.

### The decision

**Compile a small language to `evt` bytecode. Do not ship a VM.**

Implemented as `bleck/script/` plus `bleck script {check,dump,build}` and a
`code` block in `mod.json`. A script becomes `overlay/files/mod/mod.rel` through
the existing overlay machinery — a code mod is still just a mod.

### Rejected: embedding Lua (or Wren, QuickJS, Duktape, wasm3, mruby, Pawn)

Researched properly before rejecting. Lua was the strongest candidate and has
real devkitPPC prior art (the WiiBrew `Lua for Wii` package, WiiLÖVE, LuaFWii).
It still loses on every axis that matters here:

- **No prior art for a VM inside a retail game's address space via a REL.** All
  the Wii Lua work is homebrew ELF/DOL with libogc and newlib underneath. Our
  build contract is `-nostdlib -ffreestanding`.
- **A libc shim would have to be written**: `setjmp`/`longjmp` by hand in PPC
  EABI assembly (C++ exceptions are off), plus `str*`/`mem*`/`ctype`, plus the
  `sprintf`/`strtod` pair that is where freestanding ports actually break.
- **~70–160 KB of REL** against the ~400 bytes a compiled script costs.
- **GC against a 16.6 ms budget.** Lua 5.4's incremental collector has an atomic
  step that "can run into the tens of milliseconds"; generational major
  collections are stop-the-world. A permanent tuning burden, not a solved
  problem.
- **Bytecode is not portable.** `luac` emits native-endian only, so scripts
  would have to ship as text and be parsed on-console.
- ⛔ **LuaJIT is dead for this target** — its own status page lists PPC32 as
  EOL, and a JIT needs W+X memory in someone else's address space anyway.

⚠️ **NaN boxing is the big-endian hazard** across this whole category (Wren,
QuickJS 32-bit, mruby, Janet). Lua avoids it with a tagged union; the others
would need auditing. Recorded so nobody re-runs this survey.

### Rejected: a friendlier AOT language (Nim, Zig, Rust)

Genuinely viable and worth revisiting for the *native* track. Nim compiles to C
(`--os:any -d:useMalloc --mm:arc`, no tracing GC) and has strong precedent on a
comparable console — `natu` shipped a commercial GBA game via devkitARM. Zig's
`@cImport` would eliminate binding generation entirely.

Rejected **for scripting** because AOT gives no sandbox, no hot reload, and
crashes that look exactly like C crashes. It is a better-C, not a scripting
layer. Also: `powerpc-freestanding` is outside Zig's tier system, and Rust needs
a custom JSON target plus nightly forever.

### Corroboration: nobody in console modding ships a VM

Surveyed ttyd-tools, spm-rel-loader, Kamek/Newer SMBW, Skyline, Starlight,
HackerSM64, m-ex/Slippi, BrawlBox/PSA. **None ship a scripting VM.** The
successful move has consistently been either *make the C/C++ path excellent*
(Kamek declares hook sites inline in the source; LunaKit adds in-game ImGui) or
*edit the game's own bytecode through better tools* (PSA, `ttydasm`,
`evt-disassembler`, SM64's `script.c` macros). Skyline choosing Rust is the one
counter-example, and it is still AOT.

Compiling to `evt` is the second pattern, with a compiler instead of a GUI.

### The design decision that keeps licensing open ✅

**Scripts reference game functions by name; the generated C declares them
`extern` and takes their address; `elf2rel` binds the name through the symbol
list at REL-build time.**

So `bleck` writes no addresses, reads no symbol list, and ships none. Verified
by test: generated C contains no `0x80`. `BLECK_SYMBOLS_DIR` points at a
user-supplied `spm.<version>.lst`.

This means D26's licensing question **stays open and blocks nothing**, which is
the opposite of the roadmap's assumption that it blocked everything.

### Also decided

- **Generate C rather than an object file.** Reuses the proven devkitPPC +
  `pyelf2rel` path instead of learning ELF relocations.
- **Compile in `builder.check` as well as `builder.build`.** A mod whose code
  does not compile is not a mod that passes checking.
- **Compiler flags are a property of the compiler, not the OS.** devkitPPC's
  `powerpc-eabi-gcc` takes `-mgcn`; Debian's needs `-fno-pic -fno-PIE` (D26).
  Modelled as a `Toolchain` value chosen from the executable's name, not an `if`.
- **Two code mods in one chain is a hard error**, naming both. The loader opens
  exactly one `/mod/mod.rel`, so the alternative is silently dropping one.
- **Negative literals are constant-folded**, which also makes the
  ambiguous-literal guard reachable: the parser only ever produces unary minus
  applied to a positive literal, so without folding the guard was dead code.

### Verified this session ✅

- devkitPPC 16.1.0 on Windows: `--enable-languages=c,c++,objc,lto`,
  `--with-cpu=750`, newlib. **`powerpc-eabi-g++` and `powerpc-eabi-gdb` are both
  present** — C++ works here where it did not on the Pi (D26).
- A two-script sample compiles to **73 bytecode words**, hand-verified against
  the opcode table: `65545` = `(1<<16)|WAIT_FRM`; `-239997952` =
  `2.0*1024 - 240000000`; `327772` = `USER_FUNC` with 5 args.
- Full path to a **764-byte REL v3**, which `bleck info` parses.
- `bleck mod build speedrun --no-image` → **436-byte module** staged at
  `build/speedrun/files/mod/mod.rel`.
- Test suite **164 → 236**. pylint 10.00/10. Non-vacuity checked by mutating
  `EVTDAT_LW_BASE` and confirming a failure.

### Unproven 🔶

- **Nothing has been booted.** Structural validity is not runtime correctness —
  the same gap D26 flagged and D25/D36 closed for assets.
- **`SET` (0x32) vs `SETI` (0x33).** We assume `SET`/`SETF` are the int/float
  assignment pair, following the `ADD`/`ADDF` convention. `SETI` exists and its
  role is not documented upstream. First suspect if integer assignment misbehaves.
- **Starting the script from `_prolog`** runs it before any map loads. Which
  builtins are safe that early is untested; the sample's `wait(120)` is a guess.
- **`evtEntry(script, 0, 0)`** — priority and flags taken from TTYD convention.

### Hot reload: deferred, but the architecture was chosen to allow it

The general rule from the live-patching literature: reload is cheap when the
unit of replacement is **a value in a dispatch table the runtime owns**, and
expensive when it is **machine code** — restoring patched bytes undoes the
branch but not the allocations, callbacks or globals the code already touched.
Everest removed late-loading for exactly this reason, on PC, with a managed
runtime. No console toolkit ships code hot reload.

Compiled bytecode is data, so this design sits on the cheap side. Supporting
facts, verified from Dolphin source rather than assumed:

- ✅ Riivolution redirection re-opens the host file on **every** disc read
  (`DiscContent::Read`, `DirectoryBlob.cpp`); no sector cache in front of it;
  `FILE_SHARE_WRITE` on Windows. Requires Dolphin 5.0-15407+.
- ✅ SPM links `DVDMgrOpen`/`DVDMgrRead`/`DVDMgrClose`, so re-reading a file
  from the running game is ~30 lines.
- ⛔ **Reloading a rebuilt REL is ruled out**: `spm.eu0.lst` has `OSLink` at
  `80274c0c` but **no `OSUnlink`**, and `relmgr` has no unload path.

Estimated 1–3 days if wanted later. Not built; not needed for the language.

### Upstream boilerplate we did not need

`spm-rel-loader/rel/include/patch.h` already implements `writeBranch`,
`writeWord`, `clear_DC_IC_Cache` and a `hookFunction` trampoline — so the D36
hand-written detour duplicated it. Worth knowing, but it is **GPLv3**
(repo-wide `LICENSE`), and its `hookFunction` blindly copies instruction[0], so
it breaks on any function starting with a PC-relative instruction and leaks its
trampoline. Not a drop-in.

⚠️ Also corrected: **`spm-rel-loader` re-bundles the MIT headers under its
repo-wide GPLv3 `LICENSE`.** Take headers and lsts from `spm-headers`, never
from `spm-rel-loader`.

Design detail in [`scripting.md`](scripting.md).

---

## D38 — Custom code runs in-game; `_prolog` is too early for `evtEntry` (2026-07-27)

The first script mod (`coin-tick`, one coin per ten seconds) did nothing. Three
causes were possible and the symptom did not distinguish them, so rather than
guess, one disc was built carrying **two independent signals**.

### The diagnostic

`scratchpad/diag/mod.c` — a REL doing two unrelated things in one `_prolog`:

| Signal | Mechanism | Depends on |
|---|---|---|
| **A** — Mario at double speed | direct instruction patch of `marioGetGameSpeedScale` (D36 technique) | only the Gecko loader running the module |
| **B** — a coin per second | `evtEntry(script, 0, 0)` | the evt manager being alive at `_prolog` time |

Signal A was applied first, so a hang or crash in `evtEntry` would still leave
A observable.

**Result: A fired, B did not.** ✅ Observed on Windows, Dolphin 2606, eu0.

### What that settles

- ✅ **The Gecko loader works, and a `bleck`-built REL executes correctly
  in-game.** This had been *unverified since D26* — D36's `codetest` was booted
  but the session ended before anyone looked at it, and the roadmap has carried
  "no custom code has ever run" ever since. It has now run.
- ✅ **The D36 detour technique is correct in practice**, not just structurally:
  the branch encoding, the 26-bit range check and the `dcbst`/`sync`/`icbi`/
  `isync` flush all behave. Observable as jump distance more than foot speed,
  since `marioGetGameSpeedScale` scales physics timing.
- ✅ **`evtEntry` called from `_prolog` does nothing.** Measured, not inferred.
  The loader links the module immediately after the game's own REL, long before
  the evt manager is initialised, so there is no entry table to allocate from.
  D37 flagged this as 🔶 "which builtins are safe that early is untested" —
  that understated it. The problem is not the builtins; it is `evtEntry` itself.

⚠️ Note `evtmgrInit` is declared in `spm/evtmgr.h` but is **not** in
`spm.eu0.lst` (only `evtmgrReInit` at `800d8b2c` and `evtEntry` at `800d8b88`),
so initialisation state cannot be queried directly. This was diagnosed purely
from the two-signal split.

### The fix: hook the sequence table, do not patch code

`_prolog` no longer starts anything. It swaps a function pointer in the game's
own dispatch table:

```c
extern SeqDef seq_data[];          /* {init, main, exit} per sequence */
#define BLECK_SEQ_GAME 2

void _prolog(void) {
    bleck_real_game_init = seq_data[BLECK_SEQ_GAME].init;
    seq_data[BLECK_SEQ_GAME].init = &bleck_start_scripts;
}
```

`seq_data` is at `804287a8` and **is** in the symbol list, so it resolves by
name — the zero-hardcoded-addresses property from D37 still holds.

Why this shape:

- **No code patching and no cache flush.** It is a data write, so none of the
  instruction-cache hazards apply.
- **It runs late enough.** By `SEQ_GAME`, the game is running its own evt
  scripts, so the manager is unambiguously up.
- **It is upstream's own recommended technique.** `spm-rel-loader`'s example mod
  swaps `seq_data[SEQ_TITLE].main` to draw text. We reached it independently
  from the diagnostic, but it is the established pattern rather than a novelty.
- **The hook unhooks itself before running.** Gameplay is re-entered after every
  map change; without this, each transition would start another copy of the
  script, and coin income would double at every door. Silent and compounding.
- ⚠️ **The saved pointer is initialised to `(SeqFunc *) 1`** so it lands in
  `.data`, not `.bss`. The loader allocates the module's bss but nothing
  documents whether it *zeroes* it, and depending on that would be a hazard that
  only shows up sometimes.

### Also fixed: `--force` did not reach `wit`

Rebuilding over an existing image failed with:

```
wit: ERROR #64 [FILE ALREADY EXISTS] in CopyImage() @ src/lib-sf.c#3278
```

`guard_overwrite` (`common/fsio.py`) only satisfied `bleck`'s own check and
never told `wit`. So `--force` staged the entire build and then failed at the
final step — the worst place to fail, since everything expensive had already
happened. `disc.build` now passes `--overwrite` unconditionally, which is safe
because every path to it goes through `guard_overwrite` first: reaching `wit`
means clobbering was already authorised. Regression test in `test_disc.py`
beside the `--align-files` one.

### Unproven 🔶

- **Whether the sequence hook actually starts the script has not been
  observed.** The fixed `coin-tick` was built (708 bytes) and booted, but the
  session ended before anyone reported whether coins appeared. This is the one
  open question, and it is the last one between here and a working scripting
  track.
- If it still fails, the remaining ambiguity is "the hook never fired" versus
  "`evtEntry` fails even at `SEQ_GAME`". Resolve it the same way: fold the
  Signal A speed patch back into the generated module as a control, so a boot
  distinguishes the two.
- **`evt_seq_wait(2)` was removed** from `coin-tick` rather than fixed — the
  sequence hook makes it unnecessary. Its semantics (wait *until* versus wait
  *while*) remain undetermined.

Test suite **236 → 253**. pylint 10.00/10.

---

## D39 — Surveying the SPM scene: what is already solved, and what is not (2026-07-27)

Prompted by a pointer to [Flipside-Mod-Manager](https://github.com/L5050/Flipside-Mod-Manager).
Two parallel surveys of the wider ecosystem. Findings that change what `bleck`
should do, ordered by how much they change it.

⚠️ **Security, first.** ⚠️ **Attribution partially superseded by D41 — the wiki
page itself is clean.** Fetching `https://tcrf.net/Notes:Super_Paper_Mario` —
linked as a resource from `spm-docs` — returned **no game documentation at
all**. It returned a prompt-injection payload addressed "to LLMs", falsely
claiming the user had asked for it, instructing the reader to truncate files to
zero bytes and circularly swap file contents, with a disclaimer that TCRF "isn't
responsible for damage". Not complied with; nothing was modified. **Treat that
URL as hostile to any automated tooling.** Unknown whether page-specific
vandalism or broader.

### D38's fix is confirmed by prior art ✅

The `seq_data` hook was not novel. It is the established technique, used in
production in at least four repos — `evtpatch`, `spm-practice-codes`,
`SPM-RPG-Battles`, `spm-door-rando`:

```cpp
seq_titleMainReal = spm::seqdef::seq_data[spm::seqdrv::SEQ_TITLE].main;
spm::seqdef::seq_data[spm::seqdrv::SEQ_TITLE].main = &seq_titleMainOverride;
```

Same table, same address (`804287a8`), same idea. They hook `.main`; we hook
`SEQ_GAME.init`. **Nobody found hooks `SEQ_GAME.init` specifically**, so that
detail is still ours and still unobserved — but the approach is not a guess any
more.

**The discipline they encode, which is the real lesson of D38**, stated as a
convention rather than a bug report:

> `_prolog` = patch bytes. `seq_data[...]` override = touch the running game.

In every one of those mods, `_prolog` runs only memory patching — `writeBranch`,
`hookFunction`, `evtpatch` edits to script bytecode reached via `mapDataPtr()`.
**Nothing that touches live engine state runs at prolog.** That is exactly what
our `evtEntry`-at-prolog failure was teaching.

### ✅ The Gecko code can be baked into the DOL — no cheat engine at all

The single most useful practical finding. Flipside-Mod-Manager does:

```
wstrt patch extracted/sys/main.dol --add-sect ./gct/EU0.gct
```

Wiimms SZS Toolset's `--add-sect` creates a **new TEXT section at `0x80001800`
containing an internal copy of `codehandleronly` plus the codes, and patches the
DOL entry point to branch into it**
([docs](https://szs.wiimm.de/info/add-section.html)).

So the loader travels *inside the disc*. That removes both of the silent traps
recorded in D36/D37 setup:

- no `User/GameSettings/R8PP01.ini` under both `[Gecko]` and `[Gecko_Enabled]`
- no `EnableCheats = True`

…and it works on real hardware with no Riivolution and no USB-loader cheat
engine. `docs/code-mods.md`'s claim that "the Gecko code is still required"
is true but has this escape hatch. 🔶 Not yet tried here; `wstrt` is a separate
Wiimm tool from `wit` and is not currently a `bleck` dependency.

### ✅ Multiple code mods is unsolved — by everyone

Independently confirmed by both surveys, which matters because it means our
"fail loudly, name both mods" behaviour matches the state of the art rather
than lagging it.

- Flipside-Mod-Manager README: *"assume that you can only have one rel mod
  installed at a time"*. It hard-codes the assumption: `mod.rel` is excluded
  from backup, and uninstall does `remove_all(files/mod)`.
- `spm-lunatic-pit` README: *"Please do not enable any more than one SPM mod at
  one time, as they are not cross-compatible."*
- ⛔ **`chainrel` is a stub.** Three commits, all 2026-02-09; the loader body is
  wrapped in `#if 0`. What exists is a boot-time picker UI drawing
  `"test string"` ten times. Even the dead code is single-successor
  (`mod.rel` → `chain.rel`), not N mods.
- Several mods carry a copy-pasted `include/chainloader.h` declaring
  `void tryChainload()` with **no implementation anywhere in the tree**.
- The scene's shared `hookFunction()` writes a branch over instruction 0 and
  builds a trampoline — **two mods hooking the same function silently clobber
  each other**, which is the actual hard part and is unaddressed.

**This is an unclaimed problem and the clearest differentiator available.**

⚠️ **The gotcha that will bite whoever solves it**, from `relloader3/util.cpp`:

```cpp
// Use negative alignment to allocate from tail so that relF.rel won't shift
return MEMAllocFromExpHeapEx(handle, size, -alignment);
```

There is also a `HEAP_MEM1_UNUSED` heap, and before `memInit` you must carve
from `OSGetMEM1ArenaHi()` instead.

### ✅ `SET` / `SETI` / `SETF` — D37's 🔶 resolved

From **matching decompiled source**, `spm-decomp/src/evtmgr_cmd.c` (3352 lines,
fully decompiled):

```c
s32 evt_set (EvtEntry *e) { value = evtGetValue(e, p[1]); }  // 0x32 arg decoded
s32 evt_seti(EvtEntry *e) { value = p[1];                 }  // 0x33 arg RAW
s32 evt_setf(EvtEntry *e) { value = evtGetFloat(e, p[1]); }  // 0x34 float domain
```

Corroborated by `ttyd-opc-summary.txt`: `set` = "set int expr to int expr",
`seti` = "set int expr to **raw**", `setf` = "set float expr to float expr".

**Our `SET`/`SETF` choice was correct.** But `SETI` is more than a third wheel:
it is the escape hatch for exactly the case `compiler.reject_ambiguous_literal`
currently refuses. `var a = -30000000` need not be an error — emit `SETI` and it
is simply correct. Worth doing.

⚠️ Also: `check_float` **passes values through unconverted** when above the
float max, so `SETF` on a non-float-encoded operand silently behaves as an int
copy rather than failing.

### ✅ A much better symbol source exists

| Source | Symbols (eu0) | Has sizes/types |
|---|---|---|
| `spm-headers/linker/spm.eu0.lst` (what we use) | **976** | no |
| `spm-decomp/config/EU0/symbols.txt` | **43,944 total, ~9,566 human-named** | **yes** |

One regex parses it:
`^(\S+)\s*=\s*(\.?\w+):0x([0-9A-F]+);\s*//\s*(.*)$`, with `type:{function,
object,label}`, `size:0x…`, `scope:…`. Filter `^(@|fn_|lbl_|jumptable_)` for the
meaningful set. ~11× more named symbols, plus sizes — better `user_func`
validation and far more callable from a script.

⚠️ Correcting an earlier note: there is **no `config/symbols.yml`**. The files
are per-version plain text in dtk format.

### Other findings worth not rediscovering

- **`evtpatch` (JohnP55) is how this scene modifies vanilla logic.** A runtime
  `evt` bytecode patcher — `hookEvt`, `patchEvtInstruction`,
  `hookEvtReplaceBlock` — that **adds two new opcodes to the VM** (`Call`,
  `ReturnFromCall`, giving `evt` a call stack it lacks natively) by patching
  `evtmgrCmd`'s dispatcher and bypassing `make_jump_table`'s opcode bound check
  at `+0xe0`. Complementary to compiling new scripts, not competing. ⚠️ It also
  rebuilds jump tables after mutation, because `make_jump_table` caches `lbl`
  positions at entry time — a constraint we would hit the moment we emit
  `LBL`/`GOTO`, which we currently do not.
- **Scripts are reachable by name from a REL**: `mapDataPtr("he3_01")->initScript`,
  `getItemUseEvt(87)`. No file surgery needed to hook an existing map or item.
- **`relloader3` / `spm-loaders` supersedes `spm-rel-loader`.** Payload ABI with
  magic `SPMP` at a fixed `0x80004200`–`0x800060bb` (the unused TRK interrupt
  table, same address every region); four delivery back-ends (gecko, DOL patch,
  Riivolution, save exploit); region filenames `./mod/eu0.rel` with `mod.rel` as
  legacy fallback; documented budgets — **Dolphin's Gecko codehandler caps codes
  at `0xcb0`, described as "the current bottleneck"**.
- **Four documented hook timings**, earliest to latest: `main+0x6f8`
  (`spmarioInit` blr, pre-`memInit`) · `relMain+0x194` (just after `relF.rel`'s
  prolog) · `relMain+0x1b8` = `0x8023e5fc` (the classic Gecko loader we use;
  heaps exist, **evt manager does not**) · `seq_data[...].{init,main}` (fully
  live game).
- **Save-file code execution** (`spm-loaders/saveloader`): a crafted save
  overflows a stack buffer via a fake item description, firing when the player
  opens the items menu. Four-stage, survives reboot. **Unmodified disc, no Gecko,
  no Riivolution, on retail hardware** — an entirely different distribution model
  from anything `bleck` assumes.
- **Dolphin detection**, credited to TheLordScruffy:
  `IOS_Open("/sys", 1) == -106`, falling back to probing `/dev/dolphin`.
- **Mods persist state in unused `GSW` slots** (`gsw[1900]` etc.) rather than
  changing the save format — free persistence, no compatibility break.
- **Region porting is partly solved**: `JohnP55/spm-porter`, with pre-computed
  match CSVs (`pal0-us0.csv`, …) generated by mkw-sp's `portfinder`. ⚠️ *.text
  only* so far.
- **`map.dat` is further along than assumed**: `AchtungKatse/SPME` has a CLI plus
  an **ImHex pattern file** for the map format, and does `map.bin → FBX →
  map.dat` round trips. Known limits: cannot generate `cameraroad.bin`, no
  triangle-strip generation, and its LZSS "is not implemented correctly".
  Relevant when `map.dat` stops being deferred.
- **`evt-disassembler --cpp`** emits the same `evt_cmd.h` macro form our
  compiler targets — a free correctness oracle for round-tripping our bytecode.
  ⚠️ It needs a **RAM dump**, not a file.
- **`evt-assembler` is archived** (2021), ~200 lines, no expressions, no macros,
  no labels. We are past it; the only thing worth taking is its operand-encoding
  rules for round-trip compatibility.

### ⚠️ Licensing — a trap in Flipside-Mod-Manager

`Flipside-Mod-Manager` has **no LICENSE file at all** (GitHub reports
`license: null`), which means all rights reserved. But
`src/Rel Loader.asm` is plainly derivative of SeekyCt's **GPLv3**
`spm-rel-loader/loader/loader.s` — same structure, same `relWork` flag-byte
protocol, extended with more region tables. The `gct/*.gct` blobs are its
assembled output.

**Do not copy from FMM.** If we want that loader, take it from `spm-rel-loader`
under GPLv3, or write our own from the published addresses — addresses are
facts, and facts are not copyrightable.

Scene-wide: `evtpatch`, `spm-rel-loader`, `evt-disassembler`, and L5050's mods
are all GPLv3. `spm-headers` remains MIT except `mod/`. Everyone `git subrepo`
vendors `spm-headers` wholesale into every mod repo.

### What this does not change

`bleck` compiles **new** scripts; the scene patches **existing** ones at
runtime. Those are complementary, and nothing found here supersedes the D37
decision to compile to `evt` rather than ship a VM. No one else has a script
*compiler* — `evt-assembler` was the closest and it is archived and far weaker.

The scene is small: roughly 8–10 active technical contributors, and the GitHub
topic `super-paper-mario` has exactly 7 repos. ⛔ Much of the knowledge lives in
Discord and nowhere else, and **no SPM mod has a written postmortem** — which is
the ecosystem's largest documentation gap, and an argument for keeping this log
public.

---

## D40 — The `seq_data[SEQ_GAME].init` fix did not work either (2026-07-27)

⛔ **Recording a failure.** D38's fix was built, booted and produced no coins.
The scripting track therefore still has **no observed instance of a compiled
script running**, after two attempts.

| Attempt | Hook | Result |
|---|---|---|
| 1 | `evtEntry` directly in `_prolog` | ⛔ nothing (D38) |
| 2 | `seq_data[SEQ_GAME].init` | ⛔ nothing (this entry) |
| 3 | `seq_data[SEQ_GAME].main` | 🔶 built, not yet booted |

### What went wrong in the reasoning, not just the code

D38 diagnosed correctly that `_prolog` was too early, and D39 then confirmed
that hooking `seq_data` is the established technique. Both were right. But the
conclusion drawn — "therefore hook `seq_data[SEQ_GAME].init`" — quietly added a
detail the evidence did not support.

⚠️ **Every mod in the scene hooks `.main`. None hooks `.init`.** That was
visible in the D39 survey and was noted there as "nobody found hooks
`SEQ_GAME.init` specifically" — and then treated as a curiosity rather than a
warning. It should have been read as the scene having already found out
something we were about to rediscover.

The lesson is narrow and worth stating: **when prior art consistently does X and
we do X′, the burden is on X′.** A one-word divergence from a technique borrowed
wholesale is still a divergence.

### The leading hypothesis 🔶

`evtmgrReInit` (`800d8b2c`) exists, which implies evt state is torn down and
rebuilt across sequence transitions. If `SEQ_GAME.init` runs *before* that
rebuild, an entry created there would be wiped moments later — which looks
exactly like "nothing happened".

Untested. It is a hypothesis, and the reason the third attempt hooks `.main`,
which runs after any such rebuild.

### Third attempt: three signals instead of one

Preserved as `docs/diagnostics/entry-point-probe.c` — in the repo this time,
because the first probe was lost with a scratch directory and had to be
described in prose instead of read.

| Signal | Mechanism | Depends on |
|---|---|---|
| **A** — double speed | instruction patch, applied **from inside the hook** | the hook firing at all |
| **B** — +100 coins once | `pouchAddCoin()` (`8014d58c`), a direct game function, no evt | the game being live and writable |
| **C** — +1 coin/sec | `evtEntry()` | evt scheduling |

The sharpening over D38's probe: **signal A moved out of `_prolog` and into the
hook**. In D38 it was applied at `_prolog`, which could prove only "the module
ran" — it could not distinguish that from "the hook ran". That ambiguity is
precisely what made attempt 2's failure uninformative, and it is now closed.

Reading it: **A+B+C** promote `.main` into the emitter · **A+B, no C** evt
scheduling is wrong even in a live `SEQ_GAME`, and the next suspect is
`evtEntry(script, 0, 0)`'s priority/flags, taken from TTYD convention and never
checked against SPM (`EVT_FLAG_START_IMMEDIATE` exists in `evtmgr.h`) ·
**A only** the hook fires but the game is not live · **none** the `seq_data`
write is not taking effect at all.

Built as `out/diag2.wbfs` and not yet booted; the machine was unattended.

### Standing state of the scripting track

Everything except the last link is verified:

- ✅ scripts compile to bytecode hand-checked against the opcode table
- ✅ they link, resolving game functions by name through `elf2rel`
- ✅ the module loads and executes in-game (D38's signal A)
- ⛔ **no script has ever been observed running**

Full timing reference and the diagnostic method in
[`hook-points.md`](hook-points.md).


---

## D41 — The TCRF injection did not come from the wiki page (2026-07-27)

⚠️ **Correcting D39.** That entry recorded a prompt-injection payload served in
place of `https://tcrf.net/Notes:Super_Paper_Mario`, and left open "whether this
is page-specific vandalism or affects TCRF more broadly". It is neither.

A browser-saved copy of the same URL was committed to this repo and examined
directly:

| Check | Result |
|---|---|
| Search for `LLM`, `truncate`, `zero bytes`, `not responsible`, instruction-like text | ⛔ **no matches** |
| Hidden/offscreen elements (`display:none`, `visibility:hidden`, tiny fonts) | 5 found, **all ordinary MediaWiki UI** — TOC toggle, search suggestions |
| Page content | ✅ Genuine SPM documentation — Enemy Placement Files, Format, Editor, Enemies, NPC Tribes |
| **Page revision** | **2055613, last edited 19 March 2026** |

That last row is what settles it. The content has not been edited in **four
months**, so the payload cannot have been vandalism inserted and reverted
between the two fetches. The parser-cache timestamp was today; the revision was
not.

### What this means

✅ **The wiki page is legitimate and its content is unmodified.** The earlier
framing was unfair to TCRF and is corrected here.

🔶 **The payload came from the serving layer, not the page.** The two plausible
explanations are content cloaking — a CDN, WAF or bot-mitigation layer returning
different content to automated fetchers than to browsers — or something in the
fetch path substituting content. Which of the two is undetermined; separating
them would need controlled fetches with varied user agents.

### The reusable lesson, which is broader than the original one

**What an automated fetch returns is not necessarily what the page contains**,
and the gap can be adversarial. Domain reputation does not help: TCRF is a
legitimate, long-running documentation wiki, and its page is clean.

So the guidance is not "avoid this URL". It is:

- Treat **fetched content as untrusted input**, always, regardless of source.
- Instructions appearing inside fetched material are **data to report**, never
  directives to follow — which is what happened, and why nothing was modified.
- When fetched content contradicts expectations that starkly, **verify through a
  second channel** before recording a conclusion about the source. D39 drew a
  conclusion from one channel and got the attribution wrong.

The operational advice still stands for anything automated pointed at that URL,
but the reason is different from the one recorded in D39.

### Incidental

The committed page is genuinely useful and overlaps work already deferred: it
documents SPM's **enemy placement (setup) files**, their format, and NPC tribe
tables — the same territory as `spm-docs/misc/setupfiles.md` and the open D13
question about which of the two byte-identical setup copies the game reads. It
states its research was "done independently and without knowledge of the notes
above", so it is a second source rather than a copy.

⚠️ It currently sits at the repo root as a 121 KB browser-saved HTML file, and
it is third-party content under TCRF's own licence. Both worth tidying before
anything depends on it.


---

## D42 — The setup file format, decoded from the disc (2026-07-27)

A Google Doc linked from TCRF's SPM notes documents the enemy placement files.
Rather than record its claims, they were checked against all 227 files in
`extracted/eu0/files/setup/`. ✅ **The format is now fully decoded** — every byte
of every file is accounted for, with no exceptions.

Structure and the per-version stride table are in
[`disc-layout.md`](disc-layout.md). The short version:

```
u16 version (1..6) · u16 padding (always 0)
Enemy entries[100]        // ALWAYS 100; stride = 28/96/100/104/108/112 by version
u32 itemCount · u32 itemFormat (20051201) · Item items[n]   // v6 only, 16 B each
```

`base size = 4 + 100 * stride`, exact for all six versions.

### What the sources got wrong, and how they reconcile

- ⛔ The Google Doc says the files are **"consistently 11,204 bytes"** with a
  fixed 112-byte stride. True of **184 of 227**; false of the other 43.
- ✅ TCRF annotates that doc with *"entries aren't always 112 bytes, says
  Skawo"* — correct, and the version→stride table is the quantification nobody
  had written down.
- ✅ `spm-docs/misc/setupfiles.md` says "100 enemy entries (size varies with
  version)" — **confirmed**, and now quantified.
- ⚠️ `spm-docs` says items exist in **v5 and v6**. On this disc, **no v5 file
  carries an item section**; all 14 that do are v6.
- ✅ `SETUPOBJ_FORMAT_VERSION == 20051201` independently confirmed — it appears
  on every item section found.

The two sources are consistent once the version field is read: the doc measured
only v6 files, which really are 11,204 bytes, and generalised.

### Why this was worth doing

It is a small instance of the rule this project already has — *verify "no tool
exists" and "the format is X" claims against the actual disc* — and it paid off
in three ways: it corrected a widely-linked document, it quantified a caveat
that existed only as a one-line aside, and it turned a 🔶 into a ✅ without
writing any new tooling. The whole check was a fifteen-line script against data
already on disk.

⚠️ **It does not settle D13.** That question is which of the two byte-identical
setup copies the game actually reads — the standalone `setup/*.dat` or the copy
embedded in some map archives. Knowing the format does not answer it; that still
needs the change-one-copy-and-boot experiment. But it does mean a future
experiment can *generate* a valid setup file rather than hand-patching bytes.

### Incidental

The Google Doc itself requires sign-in and could not be read directly; the
pastebin mirror TCRF links beside it was readable and is the source of the
claims above. Worth remembering that TCRF pages often carry a mirror next to a
Drive link for exactly this reason.

---

## D43 — Scripts run. The track is proven end to end (2026-07-27)

✅ **A script compiled by `bleck` runs inside the game, at exactly one iteration
per frame, and keeps running across a map change.** Verified without a human
looking at the screen.

```
[t+45s] seq=GAME    gw[30] 126 -> 425 over 5s = 60/sec   *** RUNNING ***
[t+95s] seq=MAPCHG
[t+98s] seq=GAME    gw[30] 3262 -> 3741                  *** SURVIVED ***
verdict: ran=True survived_map_change=True
```

That run booted `out/scripttest.wbfs`, built by the ordinary
`bleck mod build` path with the emitter's own generated scaffolding — not a
hand-written probe. **60 increments per second from a script whose loop body is
`wait(1)` is the whole proof**: the scheduler is running it once per frame,
exactly as written.

### The method: make the game report on itself

The previous three attempts each cost a round trip to a human and returned one
bit of ambiguous information. This one is autonomous, and that changed
everything.

`dolphin-memory-engine` (`pip install dolphin-memory-engine`) attaches to the
running Dolphin **process** and reads the emulated address space from outside.
No Dolphin configuration, no fork, works on stock builds. Combined with two
addresses from the symbol list it gives complete visibility:

| Address | What |
|---|---|
| `0x80005000` | Our probe block — unused TRK interrupt table, free in every region |
| `0x80512360` | `seqWork`; `seq` at +0x00, `stage` at +0x04 |
| `0x8050C990` | `evtGetWork()`'s return — a fixed global. `gw[]` at +0x04, so `gw[n]` at +4+4n |

The probe writes a stage bitmask, counters and pointers into its block; the
harness polls them. A failure now says *which* stage was reached instead of
"nothing happened".

### What that immediately explained

⛔ **The game never enters `SEQ_TITLE`.** Watching `seqWork` showed
`LOGO -> GAME` directly, with `SEQ_GAME` reached about **44 seconds after boot
with no controller input at all**. An earlier version of this probe hooked
`seq_data[SEQ_TITLE].main`, and the readout showed its pointer correctly
installed and persisting for the whole run with a call count of zero. Not a
broken hook — a sequence that is never used.

✅ That also makes the whole loop unattended: gameplay is reachable without a
save file or a controller.

### Scripts do not survive a map change ⛔

The second finding, and the one that made the shipped design wrong.

A script started once at `SEQ_GAME` **stops permanently at the first map
change**. Measured: `gw[30]` rose steadily to 3156, the sequence went
`GAME -> MAPCHANGE -> GAME`, and then froze at 3156 for ten seconds while the
hook kept firing. `evtmgrReInit` exists; this is consistent with evt state being
torn down and rebuilt across transitions.

D38's emitter started the script once and **unhooked itself**, which would have
meant every script silently dying at the first door. The fix, verified above:

> Every sequence *other* than gameplay re-arms a flag; gameplay starts the
> script whenever it is armed.

That covers map changes, game overs and loads without needing to know which of
them resets evt. All six `seq_data[].main` entries are hooked; only index 2
starts anything.

### ⚠️ `gw[10]` is used by the game; `gw[30]` is not

The first survival run used `gw[10]` and produced nonsense — the counter reset
mid-run with no map change. Re-running on `gw[30]` gave a value tracking the
hook's own call count exactly (68/69, 1027/1028, 2825/2826), i.e. perfectly
monotonic.

So **the game's own scripts share `gw[]`**, and low slots are occupied. This is
a real hazard for mod authors and is now documented in `scripting.md`. It was
also nearly a false conclusion: the first run's evidence for "scripts die at a
map change" was partly an artefact of a contended slot, and only re-testing on a
clean slot made the finding trustworthy.

### The corrected timing picture

| Point | Result |
|---|---|
| `_prolog` (`relMain+0x1b8`) | ⛔ `evtEntry` does nothing — evt manager not up (D38) |
| `seq_data[SEQ_GAME].init` | ⛔ nothing (D40) |
| `seq_data[SEQ_TITLE].main` | ⛔ never called — sequence unused on this path |
| **`seq_data[SEQ_GAME].main`** | ✅ **works** |

`_prolog` remains correct for patching instructions, which D38 proved
independently. It is only unsafe for anything touching live engine state.

### Also confirmed

- `evtEntry(script, 0, 0)` returns a valid `EvtEntry *` (`0x807E7AA0` in one
  run), so the priority and flags taken from TTYD convention are fine — that
  🔶 from D37 can be closed.
- `gw[]` reads and writes from compiled script code work, so `SlotRef` lowering
  is correct.
- `SET`/`ADD` on a global slot behave as D39's decomp reading predicted.
- The generated `.data`-not-`.bss` trick holds: saved pointers survive.

### Cost

Four probe builds and about twenty minutes of emulator time, all unattended. The
same question had previously consumed three round trips to a human and produced
two wrong conclusions. **The lesson is not about SPM: when a system can be made
to report on itself, do that before asking anyone to watch a screen.**

Test suite 253 → 254. pylint 10.00/10.

---

## D44 — The Gecko loader now travels inside the disc (2026-07-27)

✅ **A built image boots with its code mod active on a stock Dolphin with no
cheat configuration at all.** Verified by moving `R8PP01.ini` aside entirely and
watching the script still run at 60 iterations per second.

Until now a code mod needed two pieces of out-of-band setup, both of which fail
*silently*: the loader pasted into `User/GameSettings/R8PP01.ini` under **both**
`[Gecko]` and `[Gecko_Enabled]`, and `EnableCheats = True`. Neither is required
any more, and neither exists on real hardware.

### How

`wstrt patch main.dol --add-sect loader.gct` (Wiimms SZS Toolset) creates a new
TEXT section and redirects the game's VBI hook into it:

```
80001800..800022a8   aa8 : Gecko Code Handler
800022b0..800024c0   210 : our loader
800024c8..80003000   b38 : unused available
Patch address 0x802848a8 (VBI) from 0x4e800020 to 0x4bd7d000
```

⚠️ **`wstrt` supplies its own copy of the code handler.** That is the reason
this approach was chosen over patching the DOL ourselves: `bleck` never ships,
vendors, or even reads any part of the GPLv3 Gecko handler. Doing it by hand
would have meant sourcing a `codehandleronly.bin` from somewhere.

`bleck` assembles the GCT itself — it is two magic words, the code words
big-endian, and a terminator — so the only external step is the patch. The
codelist stays **user-supplied** in `gecko/loader.<version>.txt`, same reasoning
as the symbol lists: the SPM loader code is GPLv3.

### ⚠️ The hazard this nearly caused

The staged DOL is a **hardlink to the pristine base** — `stat` showed both at
inode 562949953577906 with a link count of 9. `wstrt` rewrites in place. Patching
without detaching first would have silently corrupted
`extracted/eu0/sys/main.dol`, the one file the entire build design exists to
protect, and nothing would have noticed until a later build produced a subtly
wrong disc.

`gecko.embed` copies the DOL aside, unlinks, and copies back before invoking
`wstrt`, mirroring `builder._detach`. Verified after the fact: the base hash is
unchanged and its link count dropped from 9 to 8, while the staged copy is at 1.
A test constructs a real hardlink and asserts the base survives.

### Also

- **`wstrt` reports a dropped section as a warning and still exits 0.** A size
  or address collision therefore looks like success. `embed` compares the file
  size before and after and raises if it did not change.
- **`wstrt` does not accept a raw codelist** despite documenting GCT-TXT among
  its input types; it answers `Invalid WCH header`, which says nothing about
  what the user actually handed it. `bleck` parses the codelist itself and gives
  a line-numbered error instead.
- Embedding is **automatic when the chain ships code**, and skipped with a loud
  warning when the codelist is missing rather than failing the build — people
  with a working Dolphin cheat setup should not be forced into this.
  `--no-embed-loader` opts out.
- Room for about **2,872 more bytes** of codes in the section before it collides,
  per `wstrt`'s own memory map. Not a constraint yet.

### Unproven 🔶

- **Only tested in Dolphin.** The claim that this removes the Riivolution
  requirement on console follows from what `--add-sect` does, but no hardware
  has run it.
- **Only `eu0`.** Other versions need their own codelist; nothing else changes.

Tool count is now five: `wit`, `dolphin-tool`, `dolphin`, `powerpc-gcc`,
`wstrt`. Test suite 254 → 263. pylint 10.00/10.

---

## D45 — A builtin catalog, so the language is discoverable (2026-07-27)

The scripting track worked but nobody except its author could use it. `bleck
script --help` offered `check`, `dump` and `build`; nothing told you that
`evt_pouch_add_coins` exists. Finding a callable function meant reading
`spm-headers` yourself.

Two failures were also landing far too late:

- **An unknown name** surfaced as `elf2rel`'s `Missing 1 required symbol(s)` —
  after a compile, a toolchain and a symbol list, and saying nothing about what
  you should have written instead.
- **A wrong argument count was never caught at all.** It linked cleanly and
  misbehaved in-game. Upstream's C++ macro DSL has a compile-time arity assert
  for exactly this reason; we had nothing.

### The catalog

`bleck/script/catalog.py` extracts every `EVT_DECLARE_USER_FUNC(name, argc)` and
`EVT_UNKNOWN_USER_FUNC(name)` from `spm-headers`, with the documented signature
comment where one exists. Generated by `bleck script index <include>` and
committed as `catalog.json` (57 KB).

**443 builtins · 297 with a known argument count · 163 with a full signature.**

⚠️ **Committed rather than user-supplied**, unlike the symbol lists and the
loader codelist. The difference is licensing: `spm-headers`' `include/` is MIT,
which permits redistribution with attribution, and the extracted data is names
and integers. The generated file carries an `attribution` field naming the
project and its licence, so provenance travels with the artifact rather than
living only in a commit message. Zero setup was the whole point of the task; a
third user-supplied file would have defeated it.

### What it buys

```
$ bleck script builtins --search coin
evt_pouch
  evt_pouch_add_coins(...)        1 argument
  evt_pouch_get_coins(...)        1 argument
  evt_pouch_get_total_coins_collected(?)          argument count undocumented
```

```
$ bleck script check main.evt
main.evt:2:5: 'evt_pouch_add_coin' is not a known game function.
  Did you mean one of: evt_pouch_add_coins, evt_pouch_add_item, evt_pouch_add_xp?
2 |     evt_pouch_add_coin(1)
        ^
```

and, using the documented signature:

```
evt_mario_set_pos takes 3 argument(s), but 2 were given
  evt_mario_set_pos(f32 x, f32 y, f32 z)
```

Both now happen **before anything is compiled**, with no toolchain and no symbol
list — the same property that makes `bleck script check` the fast inner loop.

### Design decisions worth keeping

- **Variadic and undocumented collapse to the same thing.** Upstream writes `-1`
  for variadic and uses a different macro for "nobody knows"; neither can be
  checked, so both become `arity=None` and are skipped rather than guessed at.
  Guessing would reject working code.
- **An empty catalog disables checking entirely**, rather than making every
  script uncompilable. Tested.
- **The did-you-mean cutoff is high (0.75).** A wrong suggestion is worse than
  none: it sends the reader hunting for a function that is not the one they
  wanted.
- **Signature comments are matched against the function's own name.** Upstream
  frequently puts explanatory prose between the signature and the declaration —
  `evt_mario_take_damage` has two such lines — so taking "the comment above"
  would attach the wrong text.

### ⚠️ Two things this caught in existing code

**`bleck/script/builtins.py` shadowed the standard library's `builtins`
module.** pylint spotted it as `Instance of 'dict' has no 'load' member`, which
is a confusing symptom of a real hazard. Renamed to `catalog.py`. Worth noting
that the linter found this, not a test — the code ran fine.

**`tests/test_platform.py` had a hardcoded `ALL_TOOLS` of three entries**, so
"every profile covers every tool" had silently stopped covering `powerpc-gcc`
and `wstrt`. Now taken from `platforms.ALL_TOOLS`. (Recorded here rather than in
D44 because that is where it was found.)

Eight tests in `test_script.py` also began failing, which was the validation
working: they called invented names like `evt_thing`. Swapped for real builtins
with matching arity.

### Not done

- 🔶 **The catalog says what the headers document, not what a version can
  link.** Coverage varies sharply — eu0 has ~976 linkable symbols, kr0 456 — so
  a name in the catalog can still fail at link time on another build. The
  catalog is advisory for existence and authoritative for arity.
- **The decomp symbol table is still unused.** `spm-decomp/config/EU0/symbols.txt`
  has ~9,566 human-named symbols with types and sizes, against the lst's 976.
  That is a separate and larger win: it would let `bleck` validate that a name
  is a *function* rather than data, and check that a patch address is a symbol
  start rather than the middle of one.

Test suite 269 → 291. pylint 10.00/10.

---

## D46 — Native sources: mods can react instead of poll (2026-07-27)

Until now every `bleck` mod was a polling loop. A script started when gameplay
began and ran forever; it could call ~443 builtins but could not be *triggered*
by anything. "Infinite HP" worked; "change what this NPC says" did not.

The reason is narrow and structural: **`USER_FUNC` only reaches declared evt
builtins**, every one of which takes `(EvtEntry *, bool)`. An ordinary game
function — `mapDataPtr`, `pouchGetCoin`, `getItemUseEvt` — is unreachable from
a script no matter what syntax we add. Raw memory access would not fix it
either, because getting the pointer requires the call you cannot make.

So `code.sources` now compiles the mod author's own C into the same module.

```json
"code": {
  "script":  "scripts/main.evt",
  "sources": ["src/hooks.c"]
}
```

Either half is optional; at least one is required. A script-only mod is what
existed before. A sources-only mod gets scaffolding with the three REL entry
points and nothing else — no scheduler hand-off, because there is no script.

### Who owns `_prolog`

The generated code does, and a mod defines `mod_prolog` instead:

```c
__attribute__((weak)) void mod_prolog(void);
```

⚠️ **This ordering is load-bearing.** `_prolog` must install the sequence hooks
*before* the mod's own code runs (D43), and if a mod owned `_prolog` that
ordering would depend on link order — which is exactly the kind of thing that
works until someone adds a second source file.

Declared **weak** so a script-only module links with nothing defining it and the
guarded call is simply skipped. Asserted by a test that the sequence-hook
install precedes the `mod_prolog()` call.

### What this unlocks

Verified compiling and linking against the real symbol list:

- `mapDataPtr("mac_01")->initScript` — reach any map's init script **by name**,
  which is how a mod attaches behaviour to one specific room without touching a
  file
- `pouchGetCoin` / `pouchSetCoin` and every other plain function in the lst
- game structures read and written directly

`mods/hook-demo` demonstrates both halves in one mod: a script that adds a coin
every ten seconds, and C that calls two ordinary functions a script cannot.
1,628 bytes with both; a sources-only variant came to 612.

### Also decided

- **A directory entry contributes every `.c` beneath it, sorted.** Filesystem
  ordering must not change link order, because it would change the output
  without changing the input.
- **Object files are prefixed with an index**, so two sources named `main.c` in
  different directories cannot overwrite each other's `.o`. That would have
  been a silent wrong-output bug rather than an error.
- **`BLECK_HEADERS_DIR`** supplies `-I` for native sources, defaulting to
  `work/headers`. Same reasoning as the symbol lists: `spm-headers` is
  third-party, so it is pointed at rather than vendored. Without it you declare
  what you use `extern` yourself, which is what `hook-demo` does.
- **`build_rel` now takes a `BuildRequest`.** Seven positionals tripped the
  project's own argument limit; bundling follows the precedent `BuildContext`
  set in the mod builder, and a call site that reads
  `build_rel(a, b, c, d, e, f, g)` tells a reader nothing.

### Unproven 🔶

- **Nothing has been booted.** The module compiles, links against real symbols,
  and is structurally valid, but no native hook has been observed running.
  D38 proved the technique in principle; this is the same technique reached
  through the build system rather than by hand.
- **`hook-demo` only records `initScript`; it does not replace one.** Replacing
  a map's init script means deciding whether to chain to the original, and
  getting that wrong deletes the map's own setup. Left for when there is a
  reason to do it.
- The **weak-symbol behaviour under `--gc-sections`** is untested for the case
  where a mod defines `mod_prolog` but nothing else references it. It survives
  here because `_prolog` calls it.

Test suite 291 → 300. pylint 10.00/10.

---

## D47 — Native C runs in-game, and there is no title screen to hook (2026-07-27)

✅ **A `code.sources` mod executes inside the game.** D46 shipped the build
path but nothing had been booted; this closes that 🔶. Verified unattended, by
reading the game's memory from outside — no human watched a screen.

`mods/menu-watch` is native-only: no script, so `bleck` emits just the REL
entry points and the `mod_prolog` hand-off, and the sequence table is entirely
the mod's. It hooks all six `seq_data[].main`, counts frames per sequence, and
records where each map change is going.

```
mod_prolog ran   : yes (magic 'MODC')
hooks installed  : yes
order            : LOGO -> MAPCHANGE -> GAME -> MAPCHANGE -> GAME
maps loaded      : aa4_01 -> ls4_12
  LOGO         2107
  TITLE           0        <- never ran
  GAME         9227
  MAPCHANGE     196
  GAMEOVER        0
  LOAD            0
```

### ⛔ `SEQ_TITLE` never runs

Asked for a mod that runs on the main menu, and the answer is that there is no
main menu on this path. **Zero frames across 200 seconds** covering the logos,
two map loads and sustained gameplay.

D43 inferred this from outside by sampling `seqWork`; this measures it from
inside, per frame, which is a stronger claim. It also corrects D43 in one
detail: the order is not `LOGO -> GAME` but **`LOGO -> MAPCHANGE -> GAME`**.
The polling missed a map change entirely because it sampled every two seconds
and `MAPCHANGE` is short.

🔶 **Why: the game is almost certainly running its attract demo.** With no
controller input it plays the logos for ~2,100 frames (~35 s at 60 fps) and
then loads gameplay maps in sequence. `aa4_01` and `ls4_12` are ordinary map
names, not menus. The title screen presumably needs a button press, which an
unattended boot never supplies. Not proven — no input was injected to test the
alternative.

### What this means for hooking

- `seq_data[SEQ_TITLE]` is **not a usable hook point** on an unattended boot.
  The code exists (`seq_titleMain` at `8017b250`) and the pointer installs
  correctly; it is simply never called.
- `SEQ_GAME` is reached in about 45 seconds with no input, which is what makes
  the whole automated loop possible.
- `GAMEOVER` and `LOAD` also never ran, so a mod re-arming on those (as the
  generated scaffolding does) is untested rather than wrong.

### Also confirmed

- **A native mod can own the sequence table.** `menu-watch` hooks all six
  entries itself and chains to whatever was there, with no script involved and
  no conflict, because a script-less module installs no hooks of its own.
- **`seqWork.p0` names the destination of a map change**, which is the only
  place the game states where it is going. Useful for any mod that wants to act
  on arriving somewhere specific.
- **`-nostdlib` means no `strncpy`.** The map-name copy is written by hand;
  pulling in a libc for eight lines would be a poor trade, and there is none
  linked anyway.

### Method note

`dolphin-memory-engine` is now a declared dev dependency rather than something
installed ad hoc — a `uv sync` had already silently removed it once, which cost
a run. Three rounds of asking a human to watch a screen produced two wrong
conclusions (D38, D40); the readback rig has now settled four questions without
one.

### Open 🔶

- **Reaching the title screen needs input.** Dolphin can be driven with
  scripted input, but nothing here does it. Until then, a "main menu mod"
  cannot be tested automatically.
- **Whether the attract demo is what is running** is inferred from the map
  names and the absence of input, not established.

---

## D48 — Input injection is not available; the test rig moves into the repo (2026-07-27)

⛔ **Controller input cannot be injected on this machine, and the reason is not
fixable by trying harder.**

D47 found there is no title screen on an unattended boot: the game plays its
attract demo and `SEQ_TITLE` gets zero frames. The obvious next move was to
press Wiimote 2 and see whether that reaches a menu. It does not work, for two
reasons stacked on top of each other.

**1. DirectInput does not read the message queue.** Dolphin's emulated Wiimote
here is `Device = DInput/0/Keyboard Mouse` with `Buttons/2 = 2`. DirectInput
polls device state, so `SendKeys` and `PostMessage` are both invisible to it.
Input has to be injected at driver level, with a **scancode** rather than a
virtual key — `keybd_event(0, 0x03, KEYEVENTF_SCANCODE, 0)` for `2`.

**2. ⛔ The session was locked.** The harness reported what actually had focus
after each attempt:

```
[t+  9s] pressed 2 (1/12), focus='Windows Default Lock Screen'
[t+ 12s] pressed 2 (2/12), focus=''
```

`SetForegroundWindow` is refused when the caller does not already own the
foreground window, and on a locked session there is no foreground window to
give it to. Twelve presses produced a run byte-identical to the no-input one:
`LOGO=2107`, same two maps, `TITLE=0`.

Setting `BackgroundInput = True` in `WiimoteNew.ini` did not help either, and
that change has been reverted — it was a temporary experiment on the user's own
configuration, not something to leave behind.

### What this means

- **Anything needing a button press cannot be tested unattended**, at least not
  this way. A title-screen mod needs a human, or a different route in.
- 🔶 Untried alternatives, recorded so the next attempt does not start from
  scratch: Dolphin's TAS input / movie recording (`.dtm` playback), which
  bypasses the input device entirely; and writing directly to the game's pad
  state in memory, which the readback rig could already do in reverse.
- ✅ Everything **not** needing input remains fully automatable, which is most
  of it — five findings so far were settled that way.

### The rig is now part of the repo

It had been living in a session scratch directory and was rewritten from
scratch three times. Two pieces now ship:

| Path | What |
|---|---|
| `scripts/ingame.py` | Build a mod, boot it, read its report block, shut Dolphin down. Always cleans up |
| `docs/diagnostics/probe.h` | The mod side of the convention — a header a mod copies or includes |

```
uv run python scripts/ingame.py menu-watch --words 10
uv run python scripts/ingame.py coin-tick --watch-gw 30
```

It finds Dolphin through `bleck`'s own platform profile rather than a hardcoded
path, so it works on any machine the toolkit already works on. It also decodes
`seqWork` on every read, so the sequence the game is in is always visible
without the mod having to report it.

⚠️ **`gw[10]` is written by the game; `gw[30]` is not** (D43). `--watch-gw`
exists because that distinction cost a nearly-false conclusion once already.

### Why this is worth having as a first-class tool

Three rounds of asking a human to watch a screen produced **two wrong
conclusions** (D38, D40). The readback rig has since settled five questions
without one — including two that outside-in polling had got subtly wrong,
because per-frame counting from inside the game caught a map change that
two-second sampling missed entirely.

It is the difference between "nothing happened" and "reached stage 3 of 5, hook
fired 130 times, `evtEntry` returned `0x807E7AA0`".

---

## D51 — Scripts can be attached to maps; `initScript` cannot (2026-07-27)

✅ **A script can now run when a named map is reached**, declared in the
manifest and verified in-game:

```json
"code": { "script": "scripts/main.evt", "maps": { "aa4_01": "on_arrive" } }
```

This is the difference between a mod that loops and a mod that *reacts*, and it
is the first time `bleck` has produced one.

### ⛔ Patching `MapData.initScript` does not work

The obvious design, and the one tried first. A map's init script is an ordinary
pointer to evt bytecode (`spm/map_data.h`, `initScript` at +0x18 of a 0x1c
struct), so the plan was to swap in a wrapper that runs the map's own script and
then ours, preserving the map:

```
RUN_EVT <original, patched at _prolog>
RUN_EVT <ours>
END_SCRIPT
```

**Installation worked perfectly. The map never finished loading.**

| Probe | Value | Meaning |
|---|---|---|
| `mapDataPtr("aa4_01")` at `_prolog` | `0x803FFF14` | ✅ the table *is* populated that early |
| `initScript` after install | `0x80F661B4` | ✅ our wrapper, in the module |
| wrapper word 1 | `0x80E5FA18` | ✅ the map's original script, preserved |
| `gw[31]` (set by our script) | **0** | ⛔ our script never ran |
| sequence | **frozen in `MAPCHANGE` stage 13** | ⛔ for 120 s, Dolphin still alive |

So every *mechanical* assumption held — the offset, the timing, `mapDataPtr`
at `_prolog`, the pointer preserved — and the thing still deadlocked. Swapping
`RUN_EVT` for `RUN_CHILD_EVT`, on the theory that the loader waits for the init
script to finish, changed nothing.

Ruled out along the way, so nobody re-tests them:

- 🔶→⛔ *"the operand is misencoded"*. It is not. `evt` recovers an operand's
  meaning from its numeric range, and a pointer such as `0x80E5FA18` is
  `-2132534760` signed, comfortably inside the literal window
  (`is_literal`: `<= -290000000`). Pointers pass through as plain values.
- ⛔ *"`_prolog` is too early for `mapData`"*. It is not — the pointer came back
  valid, and the game's own REL prolog runs at `relMain + 0x194`, before ours at
  `relMain + 0x1b8`.

🔶 The remaining hypothesis, untested: the map loader waits on the *specific*
`EvtEntry` it created from `initScript`, and a wrapper that spawns the real
script as a separate entry never satisfies that wait. Not worth chasing, given a
working alternative.

### ✅ What works instead: watch, then start

The game says where it is going. During a map change `seqWork.p0` holds the
destination name, which is how the attract demo's maps were identified in the
first place (D47). So the sequence hook notes the name on the way in and calls
`evtEntry` once gameplay resumes — **no game data is modified at all**.

Both halves were already proven, which is the point: `evtEntry` from
`seq_data[SEQ_GAME].main` is how every `bleck` script starts (D43), and reading
`seqWork.p0` is how D47 named the maps.

⚠️ The start is deliberately deferred to `SEQ_GAME` rather than done during the
change. evt state is torn down and rebuilt across a map change (D43), so a
script started mid-change would be destroyed on the way out.

Measured with `mods/map-hook`:

| Observation | Value |
|---|---|
| `gw[31]`, set by the attached script | **4660** = `0x1234`, on arrival at `aa4_01` |
| `gw[30]`, its loop counter | 126 → 3004, **+180 per 3 s = 60/sec** |
| Map progression | `aa4_01` **then a second map** — the map still works |
| `gw[30]` after the next map change | **frozen at 3156** |

That last row is the strongest evidence and the easiest to overlook: the counter
freezing on arrival at `ls4_12` proves the hook is **map-specific**. It fired for
the map it was attached to and stayed silent for the one it was not — shown by a
stopped counter rather than by nothing happening, which is exactly the
distinction this project keeps having to buy the hard way.

### Consequences for the language

`main` is no longer required. It is what the sequence hook free-runs; a mod whose
scripts all start some other way should not have to invent one. `mods/map-hook`
has no `main` at all.

### The general lesson

**Every mechanical check passed and the feature still did not work.** Pointer
valid, offset right, timing right, original preserved — and a hard freeze. Had
the probe only reported "installed: yes", this would have looked like success.
It was `gw[31] == 0` — evidence about the *effect* rather than the *setup* — that
showed our script never ran, and the heartbeat in `scripts/ingame.py`
(added for this) that distinguished a freeze from a quiet success.

---

## D52 — The whole game is reachable unattended (2026-07-27)

✅ **`evt_seq_mapchange` drives the game to any map, with no controller input.**

This removes the constraint that has shaped every in-game test so far. D47 found
an unattended boot reaches exactly two maps — `aa4_01` then `ls4_12`, the attract
demo — and D48 ruled out injecting a button press. So the other 381 maps were
untestable without a human.

They are not. A script attached to `aa4_01` (D51) runs on arrival, waits for the
map to settle, and asks the game to go somewhere else:

```
script on_arrive {
    gw[31] = 1
    wait(120)
    gw[31] = 2
    evt_seq_mapchange("he1_01", 0)
    gw[31] = 3      -- never reached
}
```

Measured:

| Observation | Value |
|---|---|
| `gw[31]` | **2** — the call was issued and the script then died |
| Second map recorded | `6865315F 30310000` = **`he1_01`** |
| Maps seen by t+45 s | **2**, where an unmodified boot reaches 2 only at t+96 s |
| Stability | held `SEQ_GAME` for 90+ s after arrival |

`gw[31]` stopping at 2 is the confirmation, not a failure: the map change tears
down evt state and the script with it (D43), so never reaching 3 is what a
*working* call looks like.

⚠️ The second argument is the destination **door**, passed as `0` to use the
map's own fallback — `spm/map_data.h` documents `fallbackDoorName` as the
behaviour when a map is entered with a null door name. It has not been tested
with a real door name.

### Why this matters more than it looks

Everything in-game verified so far was verified on two maps, both of which the
demo happened to visit. Anything keyed to a *particular* place — enemy
placement, a door, an NPC, a chapter's own scripting — was out of reach.

🔶 Not yet tried: chaining several changes to walk a route, or returning. Each
change kills the script that issued it, so a multi-hop route needs the hook to
re-arm per map, which the existing `code.maps` mechanism already does.

### Two tooling fixes this run paid for

⚠️ **`bleck script check` required a script named `main`.** A file whose scripts
are all attached to maps is perfectly valid, and refusing to check it was a
papercut introduced by D51. Requiring `main` is a rule about how a *mod* starts
things, not about whether a file is valid, so `check` no longer applies it.

⚠️ **`scripts/ingame.py` now always writes a full transcript** to
`work/build/ingame.log`. This run was repeated in its entirety because the
console output was read through `tail` with `--words 9`, and the answer — the
destination map name — sat in words 9–12. A run costs two to three minutes; the
log costs nothing. Do not truncate probe output.

---

## D53 — D13 settled: the game reads the *embedded* setup copy (2026-07-27)

✅ **The copy inside the map archive is the one the game uses. The standalone
`files/setup/*.dat` is read from disc but parked in MEM2 and never reaches
working memory.**

This has been open since D13 and blocked any setup-editing feature. It was
unanswerable while only two maps could be reached unattended; D52 removed that.

### Method — mark, don't measure

The two copies are byte-identical, so they had to be made distinguishable. Every
obvious marker risks changing behaviour: the `version` field selects the entry
stride, and entry bytes may be parsed. The safe one is the **`padding` u16 at
offset 2**, documented as `0` across all 227 files and read by nothing.

Two bytes alone would produce false positives when scanning 88 MB of RAM, so the
search pattern was the marker *plus* the known first bytes of entry 0 — eight
bytes total, `00 06 <marker> C4 28 C0 00`.

`he1_01` was the test map: Chapter 1-1, carries **both** copies at 11,204 bytes,
and is reachable via `evt_seq_mapchange` (D52).

### Result, with a control

The control is what makes this ✅ rather than 🔶. Both runs are identical except
that the markers are swapped between the two copies:

| Address | Run 1 | Run 2, markers swapped | Holds |
|---|---|---|---|
| **MEM1 `0x81266420`** | `B2B2` = embedded | `A1A1` = embedded | ✅ **always the embedded copy** |
| MEM2 `0x91B31980` | `A1A1` = standalone | `B2B2` = standalone | always the standalone copy |
| MEM2 `0x9204F0A9` | embedded | embedded | inside the decompressed archive (unaligned) |

**The addresses did not move.** Each buffer follows the *copy*, not the marker
value, which rules out the alternative readings — load order, marker value, or
coincidence.

`0x81266420` is 32-byte aligned and the match sits at offset 0, so it is the
file's own start in a buffer of its own, in MEM1: the Wii's fast main RAM, where
live game data lives. The unaligned MEM2 hit is the same bytes seen inside the
decompressed U8 archive they came from.

🔶 Strictly, "reaches MEM1 in its own aligned buffer" is one step short of
"`npcEntryFromSetupEnemy` is handed a pointer into it". Confirming that needs a
trampoline hook on `npcEntryFromSetupEnemy` (`0x801bf7a0`) and was not worth it
against a control this clean.

### What changes

`bleck`'s build-time warning was *"which copy the game reads is unconfirmed"*.
It now says which copy to edit:

```
warning: files/setup/he1_01.dat is the standalone setup copy, which the game
loads but does not read (D13). Edit the copy inside the map archive, or this
change will do nothing
```

⚠️ **This is the trap the earlier note predicted**, now confirmed rather than
feared: a mod that edits `files/setup/*.dat` alone changes nothing, and looks
exactly like a mod that failed to build.

### Tooling

`scripts/ingame.py --find <hex>` searches MEM1 and MEM2 for a byte pattern.
Chunked at 1 MB with an overlap of `len(pattern) - 1` so a match straddling a
chunk boundary is not missed.

It answers "which of these did the game load?" without knowing anything about
*how* it loads them — mark the candidates differently and look for the marks.
That generalises well beyond setup files.

---

## D54 — Attribution audit, and a constraint it surfaced (2026-07-27)

A `README.md` now credits the projects `bleck` is built on. Verified against
each repository rather than written from memory, which caught things worth
recording.

### ✅ `spm-headers` is MIT — but only in part

Its README is precise, and it matters:

> All code originally written for this project (everything under the `include`,
> `decomp` and `linker` directories) is available under the MIT license.
>
> Everything under the `mod` folder is available under the GPLv3 license as it's
> derived from other GPL code.

⚠️ **There is no `LICENSE` file at the repository root**, so a tool that looks
for one finds nothing and a reader might conclude "unlicensed". The statement is
in the README. `bleck/script/catalog.json`'s existing MIT attribution is
therefore **correct** — it derives from `include/` — and vendoring it is
permitted with attribution, which is what that file carries.

⛔ Nothing may be taken from `spm-headers/mod/`. Same repository, different
licence.

### ⛔ `spm-decomp` states no licence at all

Checked the root listing and both `README.md` and `CONTRIBUTING.md`: **no
`LICENSE` file, no licence statement anywhere.** Default is all-rights-reserved.

**This constrains the planned symbol-table switch** (D39, and still on the
roadmap). `config/EU0/symbols.txt` has ~9,566 named symbols against the lst's
976, and adopting it is high value — but it **cannot be vendored**.

✅ The existing design already solves this. `bleck` does not ship symbol lists
either; `BLECK_SYMBOLS_DIR` points at a copy the user supplies. Reading a
user-provided `spm-decomp` clone the same way needs no new mechanism and no
licence grant. Recording it now so the constraint is met by design rather than
discovered at the end.

⚠️ Reading it as *documentation* — which is how `evtmgr_cmd.c` settled
`SET`/`SETI`/`SETF` (D45) — is unaffected. Understanding a format from published
source and then implementing it is not redistribution.

### ✅ `spm-rel-loader` is GPLv3, confirmed by its `LICENSE` file

Its loader codes are what a built disc carries. They are **not committed here** —
`work/gecko/` is gitignored and the user supplies them — so `bleck`'s own
licence question stays independent of GPLv3, which is the property D37 was
designed around and this audit confirms still holds.

### The general point

**Every fact above was checked, and two of them contradicted a reasonable
assumption**: a repository with no `LICENSE` file that *is* licensed, and a
sibling repository from the same author that is not licensed at all. "Same
author, same terms" would have been wrong in both directions.
