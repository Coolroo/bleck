"""Building a REL from generated C, via devkitPPC or a distro cross-compiler
plus `pyelf2rel`.

Two compilers, two flag sets -- a property of which compiler was found, not of
the host OS, so it is a `Toolchain` value rather than a conditional. devkitPPC's
`powerpc-eabi-gcc` targets the game's ABI and accepts `-mgcn`. Debian's
`powerpc-linux-gnu-gcc` targets SysV, rejects `-mgcn`, and requires
`-fno-pic -fno-PIE` or it emits `R_PPC_REL16_HA` relocations `pyelf2rel` cannot
represent (D26).

Which languages exist, and what each needs, is `backends.languages` — this
module drives whatever that table describes. `_check_ctor_walk` then verifies
any language that needs a constructor walk actually got one (D80).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from bleck.backends import languages, symbols
from bleck.backends.disc import DiscError, find_tool
from bleck.backends.languages import Language
from bleck.common import env
from bleck.platforms import ToolKey

#: The symbols the REL entry-points table refers to. They must survive
#: `--gc-sections`, hence the `-u` flags in `link_flags`.
REL_ENTRY_POINTS = ["_prolog", "_epilog", "_unresolved"]

#: The game's own REL is module 1, so a mod takes the next id; two mods sharing
#: one would collide at link time inside the game.
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

    def derive_driver(self, language: Language) -> str:
        """Where this language's compiler would be, beside the located one.

        Same directory, same prefix, `gcc` swapped for the language's driver —
        so both halves always come from one toolchain. Empty when the located
        compiler's name holds no `gcc` to swap.
        """
        if not language.driver_name:
            return self.compiler
        path = Path(self.compiler)
        head, matched, tail = path.stem.rpartition("gcc")
        if not matched:
            return ""
        return str(path.with_name(f"{head}{language.driver_name}{tail}{path.suffix}"))

    def driver(self, language: Language) -> str:
        """This language's compiler, or an error naming where it was sought."""
        found = self.derive_driver(language)
        if found and (Path(found).exists() or shutil.which(found)):
            return found
        where = found or (
            f"(no 'gcc' in {Path(self.compiler).name} to swap for "
            f"{language.driver_name!r})"
        )
        hint = f"\n  {language.install_hint}." if language.install_hint else ""
        raise ToolchainError(
            f"this mod has {language.name} sources, but no {language.name} "
            f"compiler is installed at\n"
            f"  {where}\n"
            f"  bleck derives it from the C compiler it found "
            f"({self.compiler}) so both come from one toolchain.\n"
            f"  Install that toolchain's {language.name} half:  "
            f"bleck toolchain install{hint}"
        )

    def compile_flags(self, language: Language = languages.C) -> list[str]:
        return [*_COMMON_FLAGS, *self.extra_flags, *language.extra_flags]

    def link_flags(self) -> list[str]:
        # `-r` produces the relocatable object `pyelf2rel` consumes. The `-u`
        # flags keep the entry points alive through `--gc-sections`, which
        # would strip all three since nothing in the module calls them.
        flags = ["-r", "-e", "_prolog", "-nostdlib", "-Wl,--gc-sections"]
        for symbol in REL_ENTRY_POINTS:
            flags += ["-u", symbol]
        return flags + self.extra_flags


def detect(compiler: str | None = None) -> Toolchain:
    """Find a PowerPC cross-compiler and work out how to drive it."""
    found = compiler or find_tool(ToolKey.PPC_GCC)
    stem = Path(found).stem.lower()

    if "eabi" in stem:
        # `-mgcn` selects devkitPPC's GameCube/Wii multilib.
        return Toolchain(found, "devkitPPC", ["-mgcn"])

    if "linux-gnu" in stem:
        return Toolchain(found, "distro cross-compiler", ["-fno-pic", "-fno-PIE"])

    # An unrecognised name is more likely a working compiler we have not seen
    # than a broken one, so try the conservative flags rather than refusing.
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

    Not shipped with `bleck` — they come from `spm-headers`, and are pointed at
    rather than vendored to keep redistribution out of the build path.
    See `docs/scripting.md`.
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
    """Everything one REL build needs."""

    source: str
    """Generated scaffolding -- the entry points and any compiled script."""

    workdir: Path

    target: str = "eu0"
    module_id: int = DEFAULT_MODULE_ID

    extra_sources: list[Path] = field(default_factory=list)
    """The mod author's own translation units, linked into the same module."""

    include_dirs: list[Path] = field(default_factory=list)
    toolchain: Toolchain | None = None


def link_symbols(target: str, workdir: Path) -> Path:
    """The symbol list the link should actually use.

    `elf2rel` reads a *file*, so when `BLECK_DECOMP` points at a clone the lst
    and the decomp's table are merged into the work directory. 94 of the game's
    443 documented builtins are in the decomp but not the lst (D61); without
    the merge they pass the compiler's check and then fail to link.

    Falls back to the plain lst when no clone is configured.
    """
    lst = symbols_file(target)
    found = symbols.decomp_path(target, env.path(env.DECOMP_DIR))
    if found is None:
        return lst

    merged = symbols.merge(symbols.read(lst), symbols.read(found))
    out = workdir / f"spm.{target}.merged.lst"
    out.parent.mkdir(parents=True, exist_ok=True)
    symbols.write_lst(merged, out, note=f"{lst.name} + {found}")
    return out


def build_rel(request: BuildRequest) -> BuildResult:
    """Compile C into a REL module.

    `request.workdir` keeps its intermediates: the compiler's line numbers only
    mean something next to the generated file they refer to.
    """
    chain = request.toolchain or detect()
    lst = link_symbols(request.target, request.workdir)

    workdir = request.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    csource = workdir / "mod.c"
    elf = workdir / "mod.elf"
    # newline="" so the generated C is byte-identical on every platform;
    # otherwise Windows writes CRLF and Linux LF from the same script.
    csource.write_text(request.source, encoding="ascii", newline="")

    includes = [f"-I{path}" for path in request.include_dirs]
    units = [csource, *request.extra_sources]
    used = languages.used_by(units)
    # Every driver is resolved before any compile runs, so a missing one is
    # reported instead of surfacing after half the module has been built.
    drivers = {language: chain.driver(language) for language in used}

    objects: list[Path] = []
    for index, unit in enumerate(units):
        # Index-prefixed so two sources named `main.c` in different directories
        # cannot overwrite each other's object file.
        output = workdir / f"{index:02d}-{unit.stem}.o"
        language = languages.for_source(unit)
        _run(
            [
                drivers[language],
                *chain.compile_flags(language),
                *includes,
                "-c",
                str(unit),
                "-o",
                str(output),
            ],
            f"compiling {unit.name}",
        )
        objects.append(output)

    # The highest `link_priority` present drives the link: g++ for a module
    # holding any C++, and `-nostdlib` keeps it from adding libraries.
    lead = max(used, key=lambda language: language.link_priority)
    _run(
        [
            drivers[lead],
            *chain.link_flags(),
            *[str(path) for path in objects],
            "-o",
            str(elf),
        ],
        "linking the module",
    )

    if any(language.needs_ctor_walk for language in used):
        _check_ctor_walk(elf)

    rel = _to_rel(elf, lst, request.module_id)
    return BuildResult(
        rel=rel, toolchain=chain.name, module_id=request.module_id, symbols_file=lst
    )


#: The markers `runtime_c.CTOR_BLOCK` puts at either end of `.ctors`.
CTOR_MARKERS = ("bleck_ctors_start", "bleck_ctors_end")

#: What to say when the walk cannot be trusted. Silent unconstructed globals are
#: the failure being avoided, so this refuses the build rather than warning.
_CTOR_ADVICE = (
    "  Global C++ objects would be left unconstructed, which fails silently "
    "in-game.\n"
    "  See docs/code-mods.md, 'C++ static constructors'."
)


def _check_ctor_walk(elf: Path) -> None:
    """Verify `_prolog`'s markers bracket every `.ctors` entry.

    The bracketing depends on the linker script's `.ctors` ordering, so it is
    measured on the linked ELF rather than assumed (see `runtime_c.CTOR_BLOCK`).
    """
    # Imported here for the same reason as pyelf2rel, which supplies it.
    from elftools.elf.elffile import ELFFile  # pylint: disable=import-outside-toplevel

    with elf.open("rb") as handle:
        image = ELFFile(handle)
        tables = [
            index
            for index, section in enumerate(image.iter_sections())
            if section.name.startswith(".ctors")
        ]
        section = image.get_section_by_name(".ctors")
        if section is None:
            return
        index = tables[0] if len(tables) == 1 else -1
        # A partially-linked object numbers symbols from their section's start,
        # so these are offsets into `.ctors`, not addresses.
        marks = {
            symbol.name: symbol["st_value"]
            for symbol in image.get_section_by_name(".symtab").iter_symbols()
            if symbol.name in CTOR_MARKERS and symbol["st_shndx"] == index
        }
        size = section["sh_size"]

    missing = [name for name in CTOR_MARKERS if name not in marks]
    if len(tables) > 1:
        raise ToolchainError(
            f"the linker kept {len(tables)} constructor tables rather than one, "
            f"so the walk would skip some.\n" + _CTOR_ADVICE
        )
    if missing:
        raise ToolchainError(
            f"the module has a .ctors table but no constructor walk over it "
            f"(missing {', '.join(missing)}).\n" + _CTOR_ADVICE
        )

    start, end = (marks[name] for name in CTOR_MARKERS)
    if start != 0 or end != size - 4:
        raise ToolchainError(
            f"the constructor walk does not bracket .ctors: markers at "
            f"+0x{start:X} and +0x{end:X} in a {size}-byte table.\n" + _CTOR_ADVICE
        )


def _to_rel(elf: Path, lst: Path, module_id: int) -> bytes:
    """Convert a relocatable ELF to a REL, resolving game symbols by name."""
    # Imported here so `bleck` still starts when pyelf2rel is absent.
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
