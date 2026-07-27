# Handoff — picking this up on another machine

Written 2026-07-27, moving from the Linux dev box (Raspberry Pi 4) to Windows.

This is the conversational context that is **not** already captured elsewhere.
For anything else:

- [`decision-log.md`](./decision-log.md) — why every choice was made (D1–D31)
- [`roadmap.md`](./roadmap.md) — what to build next and what blocks it
- [`disc-layout.md`](./disc-layout.md) — observed facts about the disc
- [`../docs-site/`](../docs-site/) — user-facing docs

---

## Where the project actually is

**The asset pipeline is finished and proven.** A disc built by `bleck` boots in
Dolphin and renders modified textures — confirmed visually, with a two-mod
dependency chain (Mario *and* Bowser inverted on the title screen). That closed
the single biggest assumption in the project: **bit-exact LZ77 is not required.**

Working and verified: LZ77, U8 (byte-exact repacking on 383/383 archives),
format detection, disc extract/build in ISO/RVZ/WBFS, mod overlays, dependency
resolution, conflict detection. 145 tests, pylint 10.00/10.

**Code injection is the active track.** The toolchain is proven — a distro
PowerPC compiler produces a valid REL — but nothing is integrated into the CLI
and no custom code has ever *run*.

---

## Immediate next steps

In order. The first is a decision, not a task.

### 1. Decide the licensing question

`spm-rel-loader` is **GPLv3**, including the Gecko loader code we need.
`spm-headers` is MIT except its `mod/` folder. `bleck` is **unlicensed**.

Nothing upstream has been copied into this repo — the clones live in a scratch
directory deliberately, so this stays open. Options are in
[`code-mods.md`](./code-mods.md). Unwinding this later is much worse than
deciding now.

### 2. Install the C++ cross-compiler

D26 proved the C toolchain. Upstream's framework is C++17.

- Linux: `sudo apt install -y g++-powerpc-linux-gnu`
- Windows: install devkitPPC via devkitPro — **this is the better option there**,
  and sidesteps the ABI risk below entirely.

### 3. Get one hook running

This is the milestone. Everything else in the code track assumes our REL both
loads and behaves correctly, and that is untested.

⚠️ **The specific risk:** Debian's compiler targets `powerpc-linux-gnu` (SysV);
devkitPPC targets `powerpc-eabi`. `-meabi` asks for EABI conventions, but
differences around small-data registers and struct passing could produce code
that builds cleanly and misbehaves at runtime.

**On Windows this risk mostly disappears** — devkitPPC installs normally there,
so use it rather than a distro compiler.

⚠️ **`-fno-pic -fno-PIE` is mandatory with a distro compiler** (not with
devkitPPC). Without it you get `Unsupported relocation type 252` from
`pyelf2rel`, an error that gives no hint about the cause.

---

## What exists on the Linux box that Windows will not have

None of this is in git, by design:

| | Notes |
|---|---|
| `roms/` | Disc images. Gitignored. Supply your own. |
| `extracted/eu0` | The PAL rev 0 base. Regenerate with `bleck extract`. |
| `mods/*/overlay/` | Gitignored — contains extracted game assets. |
| `build/` | Staging and output. Regenerable. |
| Upstream clones | `spm-rel-loader`, `spm-headers` in scratch. Re-clone as needed. |

**The committed mods will look empty and that is correct.** `mods/title-invert`
and `mods/tex-koopa` have manifests in git but no overlays, so
`bleck mod status title-invert` reports "overrides nothing yet". Re-vendor to
restore them:

```powershell
bleck mod vendor title-invert lyt/title.bin.uk/arc/timg/mario.tpl
bleck mod vendor tex-koopa    lyt/title.bin.uk/arc/timg/koopa.tpl
```

Then invert the pixel data from `0x40` to the end of each — the script is in
[`../docs-site/guides/first-mod.mdx`](../docs-site/guides/first-mod.mdx).

---

## Environment on Windows

```powershell
winget install --id=astral-sh.uv -e
git clone git@github.com:Coolroo/bleck.git
cd bleck
uv sync --extra dev
uv run pytest          # expect 145 passed
```

Then install **Wiimms ISO Tools** (`wit.exe`) and **Dolphin**
(`DolphinTool.exe`), and put both on PATH or set `BLECK_WIT` /
`BLECK_DOLPHIN_TOOL`. Full detail in [`windows.md`](./windows.md).

⚠️ **`bleck` has never actually run on Windows.** The portability work is
informed fixes plus tests that simulate the Windows paths from Linux (D27, D30).
`uv run pytest` passing there is the first real confirmation — please check it
before assuming anything else works.

### Docs site

```powershell
powershell -c "irm bun.sh/install.ps1 | iex"
cd docs-site
bun install
bun run dev        # http://localhost:3000
```

⚠️ **The dev server has never been started.** `bun run check` (Mintlify's own
broken-link validator) passes, and structure/frontmatter/links were verified by
script — but nothing has rendered visually.

---

## Open decisions, carried forward

1. **Licensing** — blocks vendoring any upstream code. See above.
2. **One code mod per disc.** The Gecko loader loads exactly one
   `/mod/mod.rel`, but our chains allow many mods. Proposed: treat that path as
   implicitly exclusive (caught by existing conflict machinery), then adopt
   [`chainrel`](https://github.com/SeekyCt/chainrel) once a single code mod
   works.
3. **Rust rewrite** — raised and deliberately deferred. The honest case rests on
   distribution (a single binary beats a Python environment for end users) and
   compressor speed. Revisit after the code track lands; a PyO3 port of just the
   compressor captures most of the benefit at a fraction of the risk.

---

## Things worth not rediscovering

- **The base is immutable and must stay that way.** `_detach` unlinks
  unconditionally rather than checking `st_nlink`, because Windows does not
  report link counts reliably — a check that silently returns 1 there would
  write straight through a hardlink into the base.
- **Setup files exist in two byte-identical copies** and we still do not know
  which the game reads (D13). `bleck` warns at build time. Now that booting
  works, this is directly testable and worth settling.
- **`--align-files` is mandatory** on every `wit` rebuild; omitting it fails
  subtly rather than loudly.
- **Share builds as `.wbfs`.** RVZ needs Dolphin 5.0-12188+; older builds reject
  it as "not a GC/Wii ISO" — which reads like a corrupt file but is not.
- **Record expensive results rather than re-running them.** The LZ77 compressor
  is ~12 s/MB; baselines are in D16.
