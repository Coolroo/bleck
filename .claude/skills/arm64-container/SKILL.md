---
name: arm64-container
description: Use when working on Apple Silicon or any aarch64 Linux host, when a devkitPro package looks unavailable for arm64, or when touching .devcontainer/. Says exactly what has been proven inside the container and what has only been assumed, and why D26's "devkitPPC is unobtainable here" was a false negative for six years.
---

# The arm64 Linux container

`.devcontainer/` — `Dockerfile` and `devcontainer.json`. The full write-up with
every measurement is **[`docs/container.md`](../../../docs/container.md)**; this
is the short form plus the traps.

**Status: the image builds and code mods build through it.** All four mods
`container_verify.py` covers produce a `mod.rel`, and all four match a devkitPPC
build on Windows byte-for-byte once the crtls versions agree.

⛔ **Nothing built in it has ever been booted**, on a Wii or in Dolphin.

⚠️ **The instrument was emulation.** Every ✅ came from `linux/arm64` under qemu
on an x86_64 Windows host, not from a Mac. That proves the packages exist for
arm64, that arm64 binaries run, and what the compiler emits. It proves nothing
about speed, Docker Desktop vs OrbStack, or macOS uid mapping — those stay 🔶.

## ⚠️ devkitPPC **is** published for aarch64 Linux (D249)

And has been since 2020. D26's "devkitPPC is unobtainable here" was wrong for
six years and everything built on it was superseded.

```
https://pkg.devkitpro.org/packages/linux/aarch64/dkp-linux.db.tar.gz
    devkitppc-gcc      16.1.0-1
    devkitppc-binutils 2.46.0-1
```

**Two things hide it, and both produce a convincing false negative:**

1. ⚠️ **Cloudflare answers 403 to a non-browser User-Agent** on
   `pkg.devkitpro.org` and `apt.devkitpro.org`. The body is
   `<title>Attention Required! | Cloudflare</title>` — not a permissions page,
   and D26 read one as an empty package list. devkitPro's own wiki works around
   it with `wget -U "dkp-apt" …`, which is the tell.
2. ⚠️ **Directory listings are off.** `/packages/linux/aarch64/` is a genuine
   404 while every file inside it is a 200. Browsing finds nothing; fetching an
   exact filename finds everything.

**Before writing "upstream does not publish X for this architecture", fetch an
exact filename with a browser UA.** Nothing in D249 says anything about native
macOS arm64 — every `macos`/`darwin` path tried returned 404; see `docs/macos.md`.

The image takes devkitPPC from **`devkitpro/devkitppc`**, upstream's own
multi-arch image, pinned to an index digest — the route upstream asks for
("Please do not use pacman on your CI workflows"). Only `devkitPPC/` and
`licenses/` are copied, 289 MB. ✅ One image pull, not build time: the two
`COPY --from` steps took 0.7 s and 0.0 s.

## ⛔ Debian's cross-compiler cannot produce a REL (D250)

`gcc-powerpc-linux-gnu` 14.2.0 is still installed, so the comparison stays
reproducible, and it is **no longer the default**. Two independent failures:

1. devkitPPC's gcc spec injects `-T ogc.ld` into every link; Debian's injects
   nothing, so `ld -r` never merges sections. A merging linker script fixes two
   of three failures.
2. The third is a real `pyelf2rel` limit — it packs a relocation addend
   **unsigned**, and GCC 14.2.0 emits `addend=-4`.

Do not reach for it as a fallback without reading D250.

⚠️ `bleck` picks correctly on its own: `platforms/linux.py` searches
`/opt/devkitpro/devkitPPC/bin` for `powerpc-eabi-gcc` before `/usr/bin`, and
`toolchain.detect()` keys its flags off `eabi` versus `linux-gnu` in the name.
The Dockerfile sets `BLECK_PPC_GCC` anyway so the choice is visible. Switch back
with `docker run -e BLECK_PPC_GCC=/usr/bin/powerpc-linux-gnu-gcc …`.

## What runs where

| | where | why |
|---|---|---|
| `bleck` CLI, asset work, disc building | container | pure Python plus `wit` |
| PowerPC compile and link | container | devkitPPC for aarch64 Linux |
| **Dolphin** | **native macOS** | GPU, window server, CoreAudio; reading emulated memory needs a self-signed re-sign |
| **Dimentio** | **native macOS** | attaches to Dolphin's process |

⛔ **Do not try to containerise either emulator.** They meet the container
through files in `work/`.

⛔ **`dolphin-memory-engine` is deliberately not installed** — 1.3.1 publishes no
aarch64 Linux wheel, so it would build from an sdist to talk to an emulator that
is not here. That is why `scripts/ingame.py` cannot run inside the container.
The image installs the rest of the `dev` extra explicitly instead of `--extra dev`.

## `wit` and `wstrt` are built from source

⛔ Upstream publishes no arm64 Linux binary for either and no source tarball.
✅ Both build from GitHub (`Wiimm/wiimms-iso-tools`, `Wiimm/wiimms-szs-tools`).

Between them the container needs **`zlib1g-dev`, `libssl-dev`, `libncurses-dev`
and `libpng-dev`**. The last two are the ones that are easy to miss: without
ncurses the `wit` link fails at `gen-ui` with `cannot find -lncurses`; without
libpng the `wstrt` build stops at `lib-image2.c` with `png.h: No such file`.
`wstrt` is what embeds the Gecko loader into `main.dol`, so without it a built
disc carries `mod.rel` and nothing that runs it.

⚠️ Neither clone is pinned. `--build-arg WIT_REF=<tag-or-sha>` /
`SZS_REF` makes the image reproducible.

## Running it

```bash
mkdir -p work/symbols work/upstream
git clone --depth 1 https://github.com/SeekyCt/spm-headers work/upstream/spm-headers
cp work/upstream/spm-headers/linker/spm.eu0.lst work/symbols/

docker build -t bleck-arm64 -f .devcontainer/Dockerfile .

docker run --rm -v "$PWD:/repo" -w /repo bleck-arm64 bash -c '
  uname -m
  powerpc-eabi-gcc --version | head -1
  wit --version
  wstrt --version'

docker run --rm -v "$PWD:/repo" -w /repo \
  -e BLECK_SYMBOLS_DIR=/repo/work/symbols \
  bleck-arm64 python scripts/container_verify.py
```

⚠️ **`bash -lc` breaks these.** A login shell rebuilds `PATH` from the profile
and loses the image's, so `python` is not found. Use `bash -c`.

Or open the folder in VS Code and **Reopen in Container**.

## Traps in the layout

- ⚠️ **The virtualenv is at `/opt/venv`, outside the workspace**, because the
  workspace is a bind mount and a host `.venv` holds interpreters this container
  cannot execute. `UV_NO_SYNC=1` keeps `uv run bleck …` from re-resolving and
  pruning what the image installed deliberately.
- **`work/extracted/` is a named volume** (`bleck-extracted`) — thousands of
  small files every build walks, and pure build output. ⛔ **Do not extend the
  volume to `work/` as a whole**: `work/build` is the handoff to native Dolphin
  and `work/roms` is the user's own images; both must stay visible from macOS.
- **`remoteUser: root`, deliberately.** macOS Docker maps ownership through its
  VM rather than preserving uids; a non-root container user is the usual source
  of "permission denied" on a file the host can write fine.
- ⚠️ **A version skew, not an architecture problem.** Straight out of the image
  `nop` and `mr-l` came back 44 and 24 bytes *short*. Cause: a newer
  `devkitppc-crtls` on the Windows host moved `. = ALIGN(32)` **inside** the
  `.text`/`.sdata`/`.bss` output sections. Copy the two Windows `.ld` files over
  the container's and the sha256s match exactly. **The image is pinned on
  purpose; the skew is what pinning costs.**
- ⚠️ `goto-map` and `cxx-switch` report DIFFERENT against the committed
  reference — and rebuilding them on Windows at the same commit gives the
  container's exact sha256s. **The disagreement is with the stored artifact, not
  between toolchains.** `example-mods/*/overlay/` is git-ignored; those `.rel`s
  are build output on one machine.

## Related

- `linting-and-ci` — `container_verify.py`'s flags and control
- `bleck-cli-workflows` — and the ⛔ `bleck toolchain install` non-command
