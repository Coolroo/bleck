"""Building a REL from generated C.

This is the last stage of the script pipeline and the only one that needs an
external program. Everything up to here is pure Python; from here it is
devkitPPC (or a distro cross-compiler) plus `pyelf2rel`.

Two compilers, two flag sets
----------------------------
devkitPPC's `powerpc-eabi-gcc` targets the same ABI the game was built with, and
accepts `-mgcn`. Debian's `powerpc-linux-gnu-gcc` targets SysV, rejects `-mgcn`,
and **requires `-fno-pic -fno-PIE`** -- without them it emits `R_PPC_REL16_HA`
relocations that `pyelf2rel` cannot represent (D26). That is a property of which
compiler was found, not of the host OS, so it is modelled as a `Toolchain` value
rather than a conditional.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from bleck import platforms
from bleck.backends.disc import DiscError, find_tool
from bleck.common import env

PPC_GCC = platforms.PPC_GCC

#: The three symbols the REL format entry-points table refers to. They must
#: survive `--gc-sections`, which is what the `-u` flags below are for.
REL_ENTRY_POINTS = ["_prolog", "_epilog", "_unresolved"]

#: The game's own REL is module 1, so a mod takes the next id. Two code mods
#: sharing an id would collide at link time inside the game.
DEFAULT_MODULE_ID = 2

_COMMON_FLAGS = [
    "-nostdlib",
    "-ffreestanding",
    "-ffunction-sections",
    "-fdata-sections",
    "-mno-sdata",
    "-DGEKKO",
    "-mcpu=750",
    "-meabi",
    "-mhard-float",
    "-O2",
    "-Wall",
]


class ToolchainError(DiscError):
    """The compiler is missing, or it rejected the generated code."""


@dataclass(frozen=True)
class Toolchain:
    """A located cross-compiler and the flags it needs."""

    compiler: str
    name: str
    extra_flags: list[str] = field(default_factory=list)

    @property
    def is_devkitppc(self) -> bool:
        return self.name == "devkitPPC"

    def compile_flags(self) -> list[str]:
        return [*_COMMON_FLAGS, *self.extra_flags]

    def link_flags(self) -> list[str]:
        # `-r` produces a relocatable object rather than an executable; that is
        # what `pyelf2rel` consumes. The `-u` flags keep the entry points alive
        # through `--gc-sections`, which would otherwise strip all three because
        # nothing in the module calls them.
        flags = ["-r", "-e", "_prolog", "-nostdlib", "-Wl,--gc-sections"]
        for symbol in REL_ENTRY_POINTS:
            flags += ["-u", symbol]
        return flags + self.extra_flags


def detect(compiler: str | None = None) -> Toolchain:
    """Find a PowerPC cross-compiler and work out how to drive it."""
    found = compiler or find_tool(PPC_GCC)
    stem = Path(found).stem.lower()

    if "eabi" in stem:
        # `-mgcn` selects devkitPPC's GameCube/Wii multilib. Debian's compiler
        # has no such multilib and rejects the flag outright.
        return Toolchain(found, "devkitPPC", ["-mgcn"])

    if "linux-gnu" in stem:
        return Toolchain(found, "distro cross-compiler", ["-fno-pic", "-fno-PIE"])

    # An unrecognised compiler is more likely to be a working one under a name
    # we have not seen than a broken one, so try it with the conservative flag
    # set rather than refusing outright.
    return Toolchain(found, "unknown", ["-fno-pic", "-fno-PIE"])


@dataclass(frozen=True)
class BuildResult:
    """A REL built from source, and what it took."""

    rel: bytes
    toolchain: str
    module_id: int
    symbols_file: Path

    @property
    def size(self) -> int:
        return len(self.rel)


def _run(args: list[str], what: str) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout).strip()
    raise ToolchainError(f"{what} failed:\n{detail}")


def symbols_file(target: str, directory: Path | None = None) -> Path:
    """Locate the symbol list for a game version.

    The lists are not shipped with `bleck`. They come from the `spm-headers`
    project, and pointing at them rather than vendoring them is deliberate:
    it keeps a redistribution decision out of the build path. See
    `docs/scripting.md`.
    """
    root = directory or env.path(env.SYMBOLS_DIR) or Path("symbols")
    candidate = root / f"spm.{target}.lst"
    if candidate.exists():
        return candidate
    raise ToolchainError(
        f"no symbol list for {target!r} at {candidate}\n"
        f"  Symbol lists come from https://github.com/SeekyCt/spm-headers\n"
        f"  (linker/spm.{target}.lst). Put it at {candidate}, or set "
        f"{env.SYMBOLS_DIR.name} to the directory holding it"
    )


@dataclass(frozen=True)
class BuildRequest:
    """Everything one REL build needs.

    Bundled rather than passed as seven positionals, following the same
    reasoning as `BuildContext` in the mod builder: these always travel
    together, and a call site reading `build_rel(a, b, c, d, e, f, g)` says
    nothing about what any of them are.
    """

    source: str
    """Generated scaffolding -- the entry points and any compiled script."""

    workdir: Path

    target: str = "eu0"
    module_id: int = DEFAULT_MODULE_ID

    extra_sources: list[Path] = field(default_factory=list)
    """The mod author's own translation units, linked into the same module."""

    include_dirs: list[Path] = field(default_factory=list)
    toolchain: Toolchain | None = None


def build_rel(request: BuildRequest) -> BuildResult:
    """Compile C into a REL module.

    `request.workdir` keeps its intermediates rather than cleaning them up:
    when generated code fails to compile, the only way to understand the
    compiler's line numbers is to read the file it was complaining about.
    """
    chain = request.toolchain or detect()
    lst = symbols_file(request.target)

    workdir = request.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    csource = workdir / "mod.c"
    elf = workdir / "mod.elf"
    # newline="" suppresses translation, so the generated C is byte-identical on
    # every platform. Without it Windows writes CRLF and Linux writes LF, and two
    # machines building the same script produce different intermediates — which
    # makes "is this REL the same one?" needlessly hard to answer.
    csource.write_text(request.source, encoding="ascii", newline="")

    includes = [f"-I{path}" for path in request.include_dirs]
    objects: list[Path] = []
    for index, unit in enumerate([csource, *request.extra_sources]):
        # Names are prefixed so two sources called `main.c` in different
        # directories cannot overwrite each other's object file.
        output = workdir / f"{index:02d}-{unit.stem}.o"
        _run(
            [
                chain.compiler,
                *chain.compile_flags(),
                *includes,
                "-c",
                str(unit),
                "-o",
                str(output),
            ],
            f"compiling {unit.name}",
        )
        objects.append(output)

    _run(
        [
            chain.compiler,
            *chain.link_flags(),
            *[str(path) for path in objects],
            "-o",
            str(elf),
        ],
        "linking the module",
    )

    rel = _to_rel(elf, lst, request.module_id)
    return BuildResult(
        rel=rel, toolchain=chain.name, module_id=request.module_id, symbols_file=lst
    )


def _to_rel(elf: Path, lst: Path, module_id: int) -> bytes:
    """Convert a relocatable ELF to a REL, resolving game symbols by name."""
    # Imported here rather than at module scope so that `bleck` still starts
    # when pyelf2rel is absent; only code mods need it.
    try:
        from pyelf2rel import elf2rel  # pylint: disable=import-outside-toplevel
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ToolchainError(
            "pyelf2rel is required to build code mods:  uv add pyelf2rel"
        ) from exc

    try:
        with elf.open("rb") as elf_handle, lst.open("r", encoding="utf-8") as lst_handle:
            return elf2rel.elf_to_rel(module_id, elf_handle, lst_handle)
    except Exception as exc:
        raise ToolchainError(_explain_rel_failure(exc, lst)) from exc


def _explain_rel_failure(exc: Exception, lst: Path) -> str:
    """Turn a pyelf2rel exception into something a mod author can act on."""
    kind = type(exc).__name__
    detail = str(exc).strip() or kind

    if kind == "MissingSymbolsError":
        return (
            f"the script calls game functions that {lst.name} does not list:\n"
            f"  {detail}\n"
            "  Check the spelling, or use a symbol list that covers them -- "
            "coverage varies a lot by game version (eu0 has by far the most)."
        )
    if kind == "UnsupportedRelocationError":
        return (
            f"the compiler emitted a relocation the REL format cannot hold:\n"
            f"  {detail}\n"
            "  This usually means position-independent code; a distro "
            "cross-compiler needs -fno-pic -fno-PIE (see D26)."
        )
    return f"converting the module to a REL failed:\n  {detail}"
