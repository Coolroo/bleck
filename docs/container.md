# The arm64 Linux container

**Status: the image builds and the cross-compiler works. Producing a `mod.rel`
through it does not** — three specific things break after the compiler has
finished, and they are named below with evidence.

This is for an Apple Silicon Mac. `.devcontainer/` holds it; everything here was
measured by building the image and running commands inside it.

⚠️ **The instrument was emulation.** Every ✅ below came from `linux/arm64` under
qemu on an x86_64 Windows host, not from a Mac. That proves the packages exist
for arm64, that arm64 binaries run, and what the compiler emits. It proves
nothing about speed, about Docker Desktop versus OrbStack, or about how macOS
maps file ownership — those stay 🔶.

---

## Why arm64, and not x86 under emulation

⛔ **devkitPPC is not an option on this machine.** Its macOS binaries are
x86_64-only, and D26 already recorded `apt.devkitpro.org` returning 403 with
empty arm64 package lists.

✅ **Debian's cross-compiler is a plain apt package on arm64.** Queried against
Debian's own `madison` API, and then installed in the image:

| Package | Debian stable (trixie) | arm64 listed |
|---|---|---|
| `gcc-powerpc-linux-gnu` | `4:14.2.0-1` | ✅ |
| `g++-powerpc-linux-gnu` | `4:14.2.0-1` | ✅ |
| `binutils-powerpc-linux-gnu` | `2.44-3` | ✅ |

Source: `https://api.ftp-master.debian.org/madison?package=<name>&table=all`.

✅ **Observed inside the built image:**

```
uname -m                        aarch64
python3 --version               Python 3.13.5
powerpc-linux-gnu-gcc           (Debian 14.2.0-19) 14.2.0
powerpc-linux-gnu-g++           (Debian 14.2.0-19) 14.2.0
powerpc-linux-gnu-ld            GNU ld (GNU Binutils for Debian) 2.44
```

14.2.0 is the version D26 measured, and trixie is the oldest Debian release that
also ships a Python satisfying `requires-python >= 3.13`. That is why the base
image is pinned to `debian:trixie-slim` by digest rather than to `stable`.

## ⚠️ The ABI caveat, stated plainly

**Debian targets `powerpc-linux-gnu` (SysV). devkitPPC targets `powerpc-eabi`.**
D26 flagged this and it has never been retired: `-meabi` asks for EABI
conventions, but small-data register use and struct passing can still differ, so
code can build cleanly and misbehave when run.

⚠️ **D149 records Windows + devkitPPC as the lower-risk host for code mods.**
Nothing here changes that. A Mac user working in this container is on the SysV
path deliberately, and should know it.

## What is in the container and what is not

| | Where it runs | Why |
|---|---|---|
| `bleck` CLI, asset work, disc building | container | pure Python plus `wit` |
| PowerPC compile and link | container | the apt cross-compiler |
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

## ⛔ What does not work yet: ELF → REL

✅ **The compiler is fine.** `scripts/container_verify.py` compiles and links a
tiny module before it tries anything else, precisely so that a page of failures
is not misread as "there is no toolchain". That control passes. Measured inside
the image:

```
toolchain    distro cross-compiler
compiler     /usr/bin/powerpc-linux-gnu-gcc
extra flags  -fno-pic -fno-PIE
  compiler probe: OK -- EM_PPC, 13 sections

=== nop:        ERROR  converting the module to a REL failed: pop from empty list
=== mr-l:       ERROR  converting the module to a REL failed: pop from empty list
=== goto-map:   ERROR  'I' format requires 0 <= number <= 4294967295
=== cxx-switch: ERROR  the linker kept 2 constructor tables rather than one
```

⚠️ **The `-fno-pic -fno-PIE` that D26 called the one non-obvious requirement is
being passed** — `bleck/backends/toolchain.py` keys it off `linux-gnu` in the
compiler's name — and `-mgcn` correctly is not. Those are not the problem.

✅ **And a REL did come out, once** — `goto-map` at `-O0` produced a valid
5,824-byte REL v3, 70 sections, `bssSize=4`, 117 relocations. So the path is not
categorically broken; three specific things sit in it.

### 1. ⛔ No `.bss`, so `pyelf2rel` raises `IndexError`

`pyelf2rel` 1.0.9 (the newest release; there is no 1.1) does:

```python
baked_bss = sorted(bss_sections, key=lambda sec: sec.header["sh_size"])
real_bss = baked_bss.pop(-1)          # IndexError when the list is empty
```

Debian's `ld -r` **does** create an empty `.bss`, and `--gc-sections` then
collects it. Measured directly, same object file both ways:

| link | `NOBITS` sections in the output |
|---|---|
| `-r` | `.bss` (size 0), `.bss.zeroGlobal` |
| `-r --gc-sections` | **none** |

devkitPPC does not hit this: its link keeps a `.bss`, which is why the reference
`nop` REL records `bssSize=0` rather than failing.

### 2. ⛔ Negative relocation addends, which the REL encoder packs unsigned

The blocking one. GCC 14.2.0 at `-O1`/`-O2` emits references to *four bytes
before* an object, and `pyelf2rel` packs the addend as unsigned:

```python
return pack(">HBBI", relative_offset, t, section, addend)
struct.error: 'I' format requires 0 <= number <= 4294967295
```

The four offenders in `nop`, read out of the ELF:

```
.rela.text._prolog  off=0x0006 type=6 addend=-4 -> .data.bleck_real_main
.rela.text._prolog  off=0x000A type=6 addend=-4 -> .rodata.bleck_hooks
.rela.text._prolog  off=0x0012 type=4 addend=-4 -> .data.bleck_real_main
.rela.text._prolog  off=0x0016 type=4 addend=-4 -> .rodata.bleck_hooks
```

Types 4 and 6 are `R_PPC_ADDR16_LO` and `R_PPC_ADDR16_HA`. This is the
loop-strength-reduction idiom `base = array - 1`.

🔶 **The value is probably representable.** A REL relocation's addend is added to
the section base at load time, so `0xFFFFFFFC` would wrap to `base - 4`
correctly in 32-bit arithmetic — the encoder simply refuses to write it. That
reading is untested and the fix would be upstream's, not `bleck`'s.

⛔ **Merging sections does not avoid it.** An explicit `-r` linker script that
merged `.text*`/`.data*`/`.rodata*`/`.bss*` was tried; all four mods still failed
here. The addend is codegen, not layout.

⛔ **Nor does `-Os`.** It links in libgcc's `_restgpr_30_x` / `_restfpr_30_x`
register-save helpers, which cannot be in a symbol list of the game's functions
and cannot resolve under `-nostdlib`.

### 3. ⛔ Two `.ctors` tables, so C++ is refused

`toolchain._check_ctor_walk` requires exactly one `.ctors` output section with
`bleck_ctors_start`/`bleck_ctors_end` at its ends. Debian's `ld -r` does not
apply the `KEEP(*(.ctors)) KEEP(*(SORT_BY_NAME(.ctors.*)))` merge that
devkitPPC's linker script supplies, so the build stops with:

    the linker kept 2 constructor tables rather than one, so the walk would
    skip some.

✅ That check is doing its job. Global C++ objects left unconstructed fail
silently in-game, which is exactly what it exists to prevent.

### What this means

⚠️ **This is not an arm64 problem, and probably not new.** Nothing above depends
on the host architecture — it is Debian's toolchain versus devkitPPC's, plus
`pyelf2rel`. The same three would be expected on the project's own aarch64 Pi
dev host with today's generated module. **D26 built a hand-written minimal
`main.c`; the generated `_prolog` has grown hook tables and a constructor walk
since, and those are what trip.** 🔶 Not confirmed on the Pi.

## What the verification script does

```bash
uv run python scripts/container_verify.py
uv run python scripts/container_verify.py nop cxx-switch --out /tmp/v.txt
```

1. Detects the toolchain and prints the exact compile line, so the D26 flags are
   visible rather than assumed. Debian's chain gets `-fno-pic -fno-PIE`;
   `-mgcn` is devkitPPC-only and is not passed.
2. **Runs the control** — compiles and links a three-function module.
3. For each mod: copies it to scratch **without its `overlay/`**, builds there,
   and compares the result with the `mod.rel` already sitting in that mod's
   overlay. Building in scratch is what keeps the reference intact.
4. Byte equality first; where that fails it falls through to structure — REL
   version, module id, section count, per-section size and exec flag, `bssSize`,
   alignments, entry sections, imported module ids, relocation counts and
   relocation *types* per module.
5. Writes the whole report to `work/build/container-verify.txt`.

Default selection: `nop`, `mr-l`, `goto-map`, `cxx-switch`. `cxx-switch` is the
C++ one (D85) and is what exercises `g++`. None of them declares `code.hooks`,
because a hook's guard word is read out of the base `main.dol` at build time and
that needs an extracted disc.

⚠️ **`example-mods/*/overlay/` is git-ignored** (`.gitignore:41`), so those
`mod.rel` files are build output on one machine, not committed artifacts. A
fresh clone has none, and the script reports `BUILT` rather than failing.

✅ **The references on the machine this was written on came from devkitPPC
16.1.0**, read out of the ELF's `.comment`:
`GCC: (devkitPPC) 16.1.0`. So any byte difference has two causes mixed
together — the toolchain, and drift in the generated C since those files were
written. Running the script under devkitPPC gives the control that separates
them: `nop` and `mr-l` came back **IDENTICAL**, `goto-map` and `cxx-switch`
**DIFFERENT**, on the same commit.

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
docker run --rm -v "$PWD:/repo" -w /repo bleck-arm64 bash -lc '
  uname -m
  powerpc-linux-gnu-gcc --version | head -1
  powerpc-linux-gnu-g++ --version | head -1
  wit --version
  wstrt --version'

# Run the verification. Writes work/build/container-verify.txt.
docker run --rm -v "$PWD:/repo" -w /repo \
  -e BLECK_SYMBOLS_DIR=/repo/work/symbols \
  bleck-arm64 python scripts/container_verify.py
```

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
| every apt package exists for arm64 | ✅ |
| `gcc`/`g++`/`ld` run and produce PowerPC objects | ✅ |
| `wit` builds and runs | ✅ |
| a REL can be produced | ✅ once, at `-O0`, for one mod |
| a REL can be produced at the flags `bleck` uses | ⛔ three blockers above |
| any REL built this way runs in-game | 🔶 never booted |
| native Apple Silicon speed, OrbStack, macOS uid mapping | 🔶 not tested |
| `wstrt` builds and runs, so the loader can be embedded | ✅ |
| a disc actually built end to end in the container | 🔶 not tried — needs a ROM |

🔶 **Build cost, emulated:** about 5½ minutes for the apt layer alone on this
x86 host under qemu, plus a few more for `wit` and `wstrt`. Native arm64 on the
Mac will be substantially faster; how much is untested.
