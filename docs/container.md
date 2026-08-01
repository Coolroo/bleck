# The arm64 Linux container

**Status: the image builds, and a code mod builds through it.** Every example
mod `container_verify.py` covers now produces a `mod.rel`, and two of the four
are byte-identical to the same mod built by devkitPPC on Windows.

This is for an Apple Silicon Mac. `.devcontainer/` holds it; everything here was
measured by building the image and running commands inside it.

⚠️ **The instrument was emulation.** Every ✅ below came from `linux/arm64` under
qemu on an x86_64 Windows host, not from a Mac. That proves the packages exist
for arm64, that arm64 binaries run, and what the compiler emits. It proves
nothing about speed, about Docker Desktop versus OrbStack, or about how macOS
maps file ownership — those stay 🔶.

⛔ **Nothing built here has been booted on a Wii or in Dolphin.** "Builds, and
matches the reference byte for byte" is not "runs". See the last section.

---

## The toolchain is devkitPPC, natively (D249)

✅ **devkitPro publishes devkitPPC for aarch64 Linux**, and has since 2020. An
Apple Silicon host therefore gets the game's own `powerpc-eabi` ABI with no
Rosetta, no qemu, and none of the SysV differences this page used to be about.

```
https://pkg.devkitpro.org/packages/linux/aarch64/dkp-linux.db.tar.gz
    devkitppc-gcc      16.1.0-1
    devkitppc-binutils 2.46.0-1
```

⚠️ **Two things make that URL look absent, and D26 was caught by both.**
Cloudflare returns **403 to a non-browser User-Agent** — the body is a Cloudflare
challenge page, not an error — and **directory listings are off**, so
`/packages/linux/aarch64/` is a real 404 while every file inside it is a 200.
Read D249 before re-deriving "devkitPro does not ship this".

The image takes it from **`devkitpro/devkitppc`**, upstream's own multi-arch
docker image, pinned to an index digest so the stage resolves to whichever of
`linux/amd64` and `linux/arm64` is being built. That is the route upstream asks
for: *"Please do not use pacman on your CI workflows. We provide docker images
for this purpose."* Only `devkitPPC/` and `licenses/` are copied — 289 MB — and
not devkitARM, portlibs or wut.

✅ **Observed inside the built image:**

```
uname -m                        aarch64
powerpc-eabi-gcc                (devkitPPC) 16.1.0
powerpc-eabi-g++                (devkitPPC) 16.1.0
powerpc-eabi-ld                 GNU ld (GNU Binutils) 2.46.0.20260210
e_machine of powerpc-eabi-gcc   183  (EM_AARCH64)
python3 --version               Python 3.13.5
```

That last line is the one that matters. The cross-compiler is a native arm64
ELF, not an x86_64 binary being emulated inside an emulated container.

### The Debian cross-compiler is still installed, and is no longer the default

✅ `gcc-powerpc-linux-gnu`, `g++-powerpc-linux-gnu` and
`binutils-powerpc-linux-gnu` 14.2.0 are all plain apt packages on arm64 — that
part of D26 is fine and the packages are still in the image, so the comparison
in D250 can be reproduced without a second image:

```bash
docker run -e BLECK_PPC_GCC=/usr/bin/powerpc-linux-gnu-gcc ...
```

⛔ **It cannot currently produce a REL.** D250 has the measurement: the whole
difference is that devkitPPC's gcc spec injects `-T ogc.ld` into every link and
Debian's injects nothing, so `ld -r` never merges sections. A merging linker
script fixes two of the three failures; the third is a real `pyelf2rel`
limitation (it packs a relocation addend unsigned, and GCC 14.2.0 emits
`addend=-4`). Do not reach for this path expecting it to work.

⚠️ **`bleck` finds the right one on its own.** `platforms/linux.py` searches
`/opt/devkitpro/devkitPPC/bin` for `powerpc-eabi-gcc` before `/usr/bin`, and
`toolchain.detect()` keys its flags off `eabi` versus `linux-gnu` in the name.
The Dockerfile sets `BLECK_PPC_GCC` anyway so the choice is visible rather than
inferred.

## What is in the container and what is not

| | Where it runs | Why |
|---|---|---|
| `bleck` CLI, asset work, disc building | container | pure Python plus `wit` |
| PowerPC compile and link | container | devkitPPC for aarch64 Linux |
| **Dolphin** | **native macOS** | GPU, window server, CoreAudio; and reading emulated memory needs a self-signed re-sign |
| **Dimentio** | **native macOS** | attaches to Dolphin's process |

⛔ **Do not try to containerise either emulator.** They meet the container
through files in `work/`, which is why `work/build` stays on the bind mount.

## `wit`, and `wstrt`

⛔ **Upstream publishes no arm64 Linux `wit`.** The download page lists
`x86_64`, `i386`, `cygwin32/64`, `mac` and nothing else, and carries no source
tarball.

✅ **It builds from the GitHub source on arm64.** `Wiimm/wiimms-iso-tools`,
`make` in `project/`, exit 0, and the result runs:

```
wit: Wiimms ISO Tool v3.05a r8638 linux - Dirk Clemens
```

It needs `zlib1g-dev`, `libssl-dev` and **`libncurses-dev`** — the last is the
one that is easy to miss, and its absence fails the link at `gen-ui` with
`cannot find -lncurses`. The Dockerfile builds it in the same stage it runs in,
so the libraries it linked against are the ones present at run time.

⚠️ **The clone is not pinned to a commit.** Upstream publishes no digest to
cite. `--build-arg WIT_REF=<tag-or-sha>` makes the image reproducible.

✅ **`wstrt` builds too**, from `Wiimm/wiimms-szs-tools`:

```
wstrt: Wiimms StaticR Tool v2.42a r8989 linux - Dirk Clemens
```

It is what embeds the Gecko loader into `main.dol`
(`bleck/backends/gecko.py`), so without it a built disc would carry `mod.rel`
and nothing that runs it.

⚠️ **It additionally wants libpng**, and that is the one that is easy to miss —
without `libpng-dev` the build stops at `lib-image2.c` with
`fatal error: png.h: No such file or directory`. Both tools are built by the
Dockerfile; between them the container needs `zlib1g-dev`, `libssl-dev`,
`libncurses-dev` and `libpng-dev`.

## ⛔ `dolphin-memory-engine` is deliberately not installed

✅ 1.3.1 publishes `macosx_x86_64`, `macosx_arm64`, `manylinux_x86_64` and
`win_amd64` wheels — **no aarch64 Linux wheel**. On arm64 it would build from
the sdist, in order to talk to an emulator that is not in this container and
never will be. So the image installs the rest of the `dev` extra explicitly
rather than `--extra dev` wholesale.

That is also why `scripts/ingame.py` cannot run in here. It runs natively.

---

## ELF → REL: what came out

✅ **All four mods build.** `scripts/container_verify.py` compiles and links a
tiny module first as a control, then builds each mod in scratch and compares
against the `mod.rel` sitting in that mod's overlay:

```
toolchain    devkitPPC
compiler     /opt/devkitpro/devkitPPC/bin/powerpc-eabi-gcc
extra flags  -mgcn
  compiler probe: OK -- EM_PPC, 11 sections

=== nop:        IDENTICAL
=== mr-l:       IDENTICAL
=== goto-map:   DIFFERENT
=== cxx-switch: DIFFERENT
```

⚠️ **`IDENTICAL` here required a control, and the first run did not produce
it.** Straight out of the image, `nop` and `mr-l` came back 44 and 24 bytes
*short*. The cause is neither arm64 nor emulation:

| | container image | this Windows host |
|---|---|---|
| `devkitppc-gcc` | 16.1.0 | 16.1.0 |
| `binutils` | 2.46.0.20260210 | 2.46.0.20260210 |
| `libogc_common.ld` | 2026-01-25 | newer |

The newer `devkitppc-crtls` moved `. = ALIGN(32)` *inside* the `.text`, `.sdata`
and `.bss` output sections. That pads `.text` to a 32-byte multiple, creates a
`.sdata` holding nothing but padding, and rounds `bssSize` up. Copy the two
Windows `.ld` files over the container's and the sha256s match exactly. **The
image is pinned on purpose; the skew is what pinning costs.**

### The four results, read honestly

| mod | container | why |
|---|---|---|
| `nop` | **IDENTICAL** to the reference | — |
| `mr-l` | **IDENTICAL** to the reference | — |
| `goto-map` | DIFFERENT: `.text` 1440 vs 1376, 117 vs 104 relocations | the generated C has drifted since the reference was written |
| `cxx-switch` | DIFFERENT: `.text` 1280 vs 1216, 107 vs 94 relocations | same |

✅ **The drift is proven, not assumed.** Rebuilding all four on this Windows
host with its own devkitPPC at the same commit gives sha256s that match the
container's exactly — including `goto-map` (`1ff077ae…`) and `cxx-switch`
(`f8c053e2…`), which are the two that disagree with the committed reference. So
the disagreement is with the stored artifact, not between the two toolchains.

⚠️ **`example-mods/*/overlay/` is git-ignored** (`.gitignore:41`), so those
`mod.rel` files are build output on one machine, not committed artifacts. A
fresh clone has none, and the script reports `BUILT` rather than failing.

## What the verification script does

```bash
uv run python scripts/container_verify.py
uv run python scripts/container_verify.py nop cxx-switch --out /tmp/v.txt
```

1. Detects the toolchain and prints the exact compile line, so what is being
   passed is visible rather than assumed.
2. **Runs the control** — compiles and links a three-function module. This
   exists so a page of `pyelf2rel` failures is never misread as "there is no
   compiler".
3. For each mod: copies it to scratch **without its `overlay/`**, builds there,
   and compares with the reference. Building in scratch is what keeps the
   reference intact.
4. Byte equality first; where that fails it falls through to structure — REL
   version, module id, section count, per-section size and exec flag, `bssSize`,
   alignments, entry sections, imported module ids, relocation counts and
   relocation *types* per module.
5. Writes the whole report to `work/build/container-verify.txt`.

Default selection: `nop`, `mr-l`, `goto-map`, `cxx-switch`. `cxx-switch` is the
C++ one (D85) and is what exercises `g++`. None of them declares `code.hooks`,
because a hook's guard word is read out of the base `main.dol` at build time and
that needs an extracted disc.

---

## Getting to a verified result

Assumes **Docker Desktop** — it is what the devcontainer tooling in VS Code
targets by default. OrbStack works too and is faster; nothing here depends on
which, and 🔶 neither was tested on macOS.

```bash
git clone <this repo> && cd bleck

# Symbol lists are not vendored. The container reads work/symbols/spm.eu0.lst.
mkdir -p work/symbols work/upstream
git clone --depth 1 https://github.com/SeekyCt/spm-headers \
    work/upstream/spm-headers
cp work/upstream/spm-headers/linker/spm.eu0.lst work/symbols/

# Build the image. On Apple Silicon this is native arm64 -- no --platform flag.
docker build -t bleck-arm64 -f .devcontainer/Dockerfile .

# Prove the arm64 toolchain is real before trusting anything built with it.
docker run --rm -v "$PWD:/repo" -w /repo bleck-arm64 bash -c '
  uname -m
  powerpc-eabi-gcc --version | head -1
  powerpc-eabi-g++ --version | head -1
  wit --version
  wstrt --version'

# Run the verification. Writes work/build/container-verify.txt.
docker run --rm -v "$PWD:/repo" -w /repo \
  -e BLECK_SYMBOLS_DIR=/repo/work/symbols \
  bleck-arm64 python scripts/container_verify.py
```

⚠️ **`bash -lc` breaks these.** A login shell rebuilds `PATH` from the profile
and loses the image's, so `python` is not found. Use `bash -c`.

To use it as a devcontainer instead, open the folder in VS Code and choose
**Reopen in Container**; `.devcontainer/devcontainer.json` does the rest.

## `work/` and mount performance

🔶 **Untested on macOS.** What the layout is designed around:

- **`work/extracted/`** — a named volume (`bleck-extracted` in
  `devcontainer.json`). Thousands of small files that every build walks, and
  pure build output. This is the directory a macOS bind mount would slow down.
- **`work/build/`** — stays on the bind mount. It is the handoff to native
  Dolphin, so macOS has to be able to open it.
- **`work/roms/`** — stays on the bind mount. The user's own disc images.

⛔ **Do not put a volume over `work/` as a whole.** It would hide the built disc
from the emulator that is supposed to boot it.

## The honest summary

| | |
|---|---|
| the image builds on arm64 | ✅ |
| devkitPPC exists for aarch64 Linux and runs natively in it | ✅ |
| `gcc`/`g++`/`ld` run and produce PowerPC objects | ✅ |
| `wit` builds and runs | ✅ |
| **a REL can be produced, at the flags `bleck` uses** | ✅ all four mods |
| **the REL matches a devkitPPC build on another host, byte for byte** | ✅ all four, once the crtls versions match |
| **any REL built this way runs in-game** | ⛔ **never booted** |
| the Debian cross-compiler can produce a REL | ⛔ still no (D250) |
| native Apple Silicon speed, OrbStack, macOS uid mapping | 🔶 not tested |
| `wstrt` builds and runs, so the loader can be embedded | ✅ |
| a disc actually built end to end in the container | 🔶 not tried — needs a ROM |

⛔ **Read the third-from-bottom row before treating any of this as finished.**
The output is bit-identical to what the Windows host produces, so the container
carries no *extra* runtime risk — but "no extra risk" is not "proven", and
D26's warning that structural validity is not runtime correctness has never been
retired for either host.

🔶 **Build cost, emulated:** about 5½ minutes for the apt layer alone on this
x86 host under qemu, plus a few more for `wit` and `wstrt`. ✅ **devkitPPC costs
one image pull, not build time** — `devkitpro/devkitppc` is a 2.49 GB download,
after which the two `COPY --from` steps took 0.7 s and 0.0 s. Native arm64 on
the Mac will be substantially faster; how much is untested.
