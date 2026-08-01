# syntax=docker/dockerfile:1

# An arm64 Linux image that runs `bleck` and cross-compiles PowerPC code mods.
#
# devkitPro publishes devkitPPC for aarch64 Linux, so an Apple Silicon host gets
# the game's own `powerpc-eabi` ABI natively -- no Rosetta, no qemu, and none of
# the SysV differences docs/container.md used to be about (D249).
#
# Dolphin and Dimentio are not here on purpose -- they need a GPU, a window
# server and, on macOS, a self-signed re-sign to read emulated memory. They stay
# native and meet this container through files in `work/`.

# devkitPro's own multi-arch image, which is the route upstream asks automated
# builds to take: "Please do not use pacman on your CI workflows. We provide
# docker images for this purpose." Pinned to the index digest, so the stage
# resolves to whichever of its linux/amd64 and linux/arm64 manifests matches
# what is being built.
FROM devkitpro/devkitppc@sha256:44cb1a920e1ec3ec7c06767493c3b85f8d643d6137cc4661f0201895ac6e4967 AS devkitppc

# trixie is Debian 13 (stable). It is the oldest release carrying both a
# Python that satisfies requires-python >=3.13 and the 14.2.0 cross-compiler
# D26 measured, which is why the tag is not `stable` or `latest`.
FROM debian:trixie-slim@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd

# `uv` as a binary rather than a curl|sh, so the version is pinned by digest and
# the build makes no network request that a proxy has to be told about.
COPY --from=ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded /uv /uvx /usr/local/bin/

ENV DEBIAN_FRONTEND=noninteractive

# One layer, because each apt run under an emulated arm64 build is expensive.
#
#   gcc/g++/binutils-powerpc-linux-gnu  the fallback cross toolchain (D26, D85).
#                                       Kept beside devkitPPC so the comparison
#                                       in D249 stays reproducible in one image
#   python3 + venv                      trixie ships 3.13; pyproject wants >=3.13
#   build-essential                     a host compiler, so a Python sdist with
#                                       no aarch64 wheel still installs
#   git, curl, ca-certificates          fetching spm-headers and symbol lists
#   file, xz-utils, less                reading what the build produced
#   zlib/ssl/ncurses/png -dev           what wit and wstrt link against, below
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      gcc-powerpc-linux-gnu \
      g++-powerpc-linux-gnu \
      binutils-powerpc-linux-gnu \
      python3 \
      python3-venv \
      build-essential \
      git \
      curl \
      ca-certificates \
      file \
      xz-utils \
      less \
      zlib1g-dev \
      libssl-dev \
      libncurses-dev \
      libpng-dev \
 && rm -rf /var/lib/apt/lists/*

# `wit` has no arm64 Linux build: upstream ships x86_64, i386, cygwin and mac
# only, and the download page carries no source tarball. It does build from the
# GitHub source, which is what this does.
#
# ⚠️ Built in this stage rather than copied out of a builder stage, so the
# libraries it linked against are the ones present at run time. The four -dev
# packages above are here for that reason.
#
# ⚠️ Not pinned to a commit -- upstream publishes no digest anyone can cite.
# Override WIT_REF with a tag or SHA to make the image reproducible.
ARG WIT_REF=master
RUN git clone --depth 1 --branch "${WIT_REF}" \
      https://github.com/Wiimm/wiimms-iso-tools.git /tmp/wit-src \
 && make -C /tmp/wit-src/project -j"$(nproc)" \
 && install -m 0755 /tmp/wit-src/project/bin/wit /tmp/wit-src/project/bin/wwt \
      /tmp/wit-src/project/bin/wdf /usr/local/bin/ \
 && rm -rf /tmp/wit-src \
 && wit --version

# `wstrt` embeds the Gecko loader into `main.dol` (bleck/backends/gecko.py), so
# without it a built disc carries `mod.rel` and nothing that runs it. Same story
# as wit: no arm64 binary upstream, builds from source. It additionally wants
# libpng, which is the dependency that is easy to miss.
ARG SZS_REF=master
RUN git clone --depth 1 --branch "${SZS_REF}" \
      https://github.com/Wiimm/wiimms-szs-tools.git /tmp/szs-src \
 && make -C /tmp/szs-src/project -j"$(nproc)" \
 && install -m 0755 /tmp/szs-src/project/bin/wstrt /usr/local/bin/ \
 && rm -rf /tmp/szs-src \
 && wstrt --version

# ⚠️ The virtualenv lives outside the workspace on purpose. The workspace is a
# bind mount from the host, and a macOS or Windows `.venv` sitting in it holds
# interpreters this container cannot execute. Pointing uv at /opt/venv means the
# two never collide.
#
# UV_NO_SYNC keeps `uv run bleck ...` -- the form every doc uses -- from
# re-resolving against the lock on each invocation and pruning what the image
# installed deliberately.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-system \
    UV_NO_SYNC=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# devkitPPC itself, from the stage above. Only `devkitPPC/` is taken: the source
# image also carries devkitARM, portlibs and wut, none of which build anything
# for the Wii. `licenses/` comes with it because these are redistributable GPL
# binaries and the notices travel with them.
COPY --from=devkitppc /opt/devkitpro/devkitPPC /opt/devkitpro/devkitPPC
COPY --from=devkitppc /opt/devkitpro/licenses /opt/devkitpro/licenses

ENV DEVKITPRO=/opt/devkitpro \
    DEVKITPPC=/opt/devkitpro/devkitPPC \
    PATH=/opt/devkitpro/devkitPPC/bin:$PATH

# Which cross-compiler to use, so nothing has to guess or be told per command.
# `bleck` would find this one anyway -- `platforms/linux.py` searches
# `/opt/devkitpro/devkitPPC/bin` for `powerpc-eabi-gcc` before Debian's -- but
# naming it makes the choice visible, and one override switches back:
#   docker run -e BLECK_PPC_GCC=/usr/bin/powerpc-linux-gnu-gcc ...
ENV BLECK_PPC_GCC=/opt/devkitpro/devkitPPC/bin/powerpc-eabi-gcc

# Relative to the working directory, which is the checkout. `work/` is where
# spm-headers' `linker/spm.<version>.lst` is put; see docs/container.md.
ENV BLECK_SYMBOLS_DIR=work/symbols

# Dependencies are resolved from the lock at image build time, so opening the
# container does not pay for it. `--no-install-project` because the checkout is
# not here yet -- it arrives as a mount.
WORKDIR /tmp/bleck-deps
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

# ⛔ The `dev` extra is deliberately not installed whole. `dolphin-memory-engine`
# publishes no aarch64 Linux wheel (1.3.1 ships macOS x86_64/arm64, manylinux
# x86_64 and win_amd64 only), so it would be built from an sdist here -- to talk
# to an emulator that is not in this container and never will be. The rest of
# the extra is what the test suite and the linters need.
RUN uv pip install --python /opt/venv \
      pytest ruff pylint pylint-pydantic pyelf2rel libWiiPy

WORKDIR /workspaces/bleck

# A shell that starts in the checkout and finds `bleck` on PATH.
CMD ["bash"]
