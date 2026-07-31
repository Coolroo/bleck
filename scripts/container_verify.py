#!/usr/bin/env python3
"""Rebuild example mods with whatever cross-compiler is installed, and compare
each `mod.rel` against the one already sitting in that mod's overlay.

    uv run python scripts/container_verify.py
    uv run python scripts/container_verify.py nop cxx-switch --out /tmp/v.txt

This exists for the arm64 container (`docs/container.md`), where the compiler is
Debian's `powerpc-linux-gnu-gcc` rather than devkitPPC's `powerpc-eabi-gcc`. The
two target different ABIs, so a byte difference is an expected result and not a
failure -- which is why a mismatch falls through to a structural comparison
instead of stopping.

⚠️ **The reference is never overwritten.** `mods.code.build_mod` writes into the
mod's own `overlay/`, so each mod is copied to a scratch directory first and
built there. `example-mods/*/overlay/` is git-ignored, so a clobbered reference
could not be restored from git.

⚠️ **A missing reference is not an error.** A fresh checkout has no
`example-mods/*/overlay/` at all; those artifacts are build output. Such a mod is
still built and still parsed, and reports `BUILT` -- the compiler was exercised,
there was simply nothing to compare with.

Only mods that need no extracted disc are in the default selection: a
`code.hooks` guard word is read out of the base `main.dol` at build time, so a
mod declaring one cannot build without `work/extracted/`.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pylint: disable=wrong-import-position
from bleck.backends import toolchain
from bleck.backends.disc import DiscError
from bleck.common import env
from bleck.common.errors import BleckError
from bleck.mods import code as modcode
from bleck.mods.registry import Mod, read

REPO = Path(__file__).resolve().parent.parent

#: Mods whose build needs only a symbol list. `cxx-switch` is the C++ one (D85)
#: and is what exercises `g++`; the rest cover script-only and C-with-script.
DEFAULT_MODS = ["nop", "mr-l", "goto-map", "cxx-switch"]

REL_PATH = Path("overlay/files/mod/mod.rel")

#: REL v3 header. Offsets from the module format; `sectionInfoOffset` is 0x4C
#: for every version, which is what `formats/detect.py` keys on.
HEADER_SIZE = 0x4C


@dataclass(frozen=True)
class RelSection:
    index: int
    offset: int
    size: int
    is_executable: bool

    def describe(self) -> str:
        kind = "exec" if self.is_executable else "data"
        return f"[{self.index}] {kind} off=0x{self.offset:X} size={self.size}"


@dataclass(frozen=True)
class RelocKind:
    type_id: int
    count: int


@dataclass(frozen=True)
class RelImport:
    module_id: int
    relocations: int
    kinds: list[RelocKind] = field(default_factory=list)

    def describe(self) -> str:
        spread = " ".join(f"t{k.type_id}x{k.count}" for k in self.kinds)
        return f"module {self.module_id}: {self.relocations} relocs  {spread}"


@dataclass(frozen=True)
class RelFile:
    """A parsed REL, reduced to the parts worth comparing between toolchains."""

    size: int
    digest: str
    version: int
    module_id: int
    bss_size: int
    align: int
    bss_align: int
    prolog_section: int
    epilog_section: int
    unresolved_section: int
    sections: list[RelSection] = field(default_factory=list)
    imports: list[RelImport] = field(default_factory=list)

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def relocation_total(self) -> int:
        return sum(entry.relocations for entry in self.imports)

    def lines(self) -> list[str]:
        out = [
            f"REL v{self.version}, module {self.module_id}, {self.size} bytes",
            f"  sha256 {self.digest}",
            f"  {self.section_count} sections, bss {self.bss_size} "
            f"(align {self.align}/{self.bss_align})",
            f"  entry sections: prolog {self.prolog_section}, "
            f"epilog {self.epilog_section}, unresolved {self.unresolved_section}",
        ]
        out += [f"  {section.describe()}" for section in self.sections if section.size]
        out += [f"  {entry.describe()}" for entry in self.imports]
        return out


def parse_rel(data: bytes) -> RelFile:
    """Read a REL header, its section table and its relocation tables.

    A REL carries no symbol table -- names are resolved at conversion time
    against the `.lst` -- so the closest comparable thing is the relocation
    tables, grouped by the module each one binds against.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"too short to be a REL: {len(data)} bytes")

    module_id = struct.unpack_from(">I", data, 0x00)[0]
    num_sections, section_offset = struct.unpack_from(">2I", data, 0x0C)
    version = struct.unpack_from(">I", data, 0x1C)[0]
    bss_size = struct.unpack_from(">I", data, 0x20)[0]
    imp_offset, imp_size = struct.unpack_from(">2I", data, 0x28)
    prolog_section, epilog_section, unresolved_section = struct.unpack_from(
        ">3B", data, 0x30
    )
    align, bss_align = struct.unpack_from(">2I", data, 0x40)

    sections = []
    for index in range(num_sections):
        raw_offset, size = struct.unpack_from(">2I", data, section_offset + index * 8)
        sections.append(RelSection(index, raw_offset & ~1, size, bool(raw_offset & 1)))

    imports = [
        _read_import(data, imp_offset + index * 8) for index in range(imp_size // 8)
    ]
    return RelFile(
        size=len(data),
        digest=hashlib.sha256(data).hexdigest(),
        version=version,
        module_id=module_id,
        bss_size=bss_size,
        align=align,
        bss_align=bss_align,
        prolog_section=prolog_section,
        epilog_section=epilog_section,
        unresolved_section=unresolved_section,
        sections=sections,
        imports=imports,
    )


#: R_RVL_STOP. The relocation stream for one module ends here.
RELOC_STOP = 203


def _read_import(data: bytes, at: int) -> RelImport:
    module_id, offset = struct.unpack_from(">2I", data, at)
    counts: Counter[int] = Counter()
    total = 0
    cursor = offset
    while cursor + 8 <= len(data):
        type_id = data[cursor + 2]
        if type_id == RELOC_STOP:
            break
        counts[type_id] += 1
        total += 1
        cursor += 8
    kinds = [RelocKind(type_id, counts[type_id]) for type_id in sorted(counts)]
    return RelImport(module_id, total, kinds)


@dataclass(frozen=True)
class ModResult:
    """One mod's outcome, in the form the report prints."""

    name: str
    status: str
    built: RelFile | None = None
    reference: RelFile | None = None
    differences: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def is_failure(self) -> bool:
        return self.status in {"ERROR", "MALFORMED"}


def compare(built: RelFile, reference: RelFile) -> list[str]:
    """Every structural disagreement between two RELs, as readable lines."""
    found: list[str] = []

    def check(what: str, left: object, right: object) -> None:
        if left != right:
            found.append(f"{what}: built {left}, reference {right}")

    check("REL version", built.version, reference.version)
    check("module id", built.module_id, reference.module_id)
    check("section count", built.section_count, reference.section_count)
    check("bss size", built.bss_size, reference.bss_size)
    check("alignment", built.align, reference.align)
    check("bss alignment", built.bss_align, reference.bss_align)
    check("prolog section", built.prolog_section, reference.prolog_section)
    check("epilog section", built.epilog_section, reference.epilog_section)
    check("unresolved section", built.unresolved_section, reference.unresolved_section)
    check("total relocations", built.relocation_total, reference.relocation_total)
    check(
        "imported modules",
        [entry.module_id for entry in built.imports],
        [entry.module_id for entry in reference.imports],
    )

    for index in range(min(built.section_count, reference.section_count)):
        left, right = built.sections[index], reference.sections[index]
        check(f"section {index} size", left.size, right.size)
        check(f"section {index} executable", left.is_executable, right.is_executable)

    for left, right in zip(built.imports, reference.imports, strict=False):
        kinds_left = sorted(k.type_id for k in left.kinds)
        kinds_right = sorted(k.type_id for k in right.kinds)
        check(f"module {left.module_id} relocation types", kinds_left, kinds_right)

    return found


def build_one(name: str, mods_dir: Path, scratch: Path) -> ModResult:
    """Copy a mod out of the way, build it, and read back what came out."""
    source = mods_dir / name
    if not (source / "mod.json").exists():
        return ModResult(name, "ERROR", error=f"no mod named {name!r} in {mods_dir}")

    staged = scratch / "mods" / name
    # ⚠️ `overlay/` is dropped so the reference cannot be read back as if the
    # compiler had just produced it.
    shutil.copytree(source, staged, ignore=shutil.ignore_patterns("overlay"))

    try:
        mod = Mod(read(staged), staged)
        modcode.build_mod(mod, scratch / "build")
    except (BleckError, DiscError, OSError) as exc:
        # ⚠️ `ToolchainError` derives from `DiscError`, which is a plain
        # `Exception` rather than a `BleckError` -- catching only the latter
        # lets a compiler failure abort the whole sweep.
        return ModResult(name, "ERROR", error=str(exc))

    produced = staged / REL_PATH
    if not produced.exists():
        return ModResult(name, "ERROR", error=f"the build wrote no {REL_PATH.name}")

    try:
        built = parse_rel(produced.read_bytes())
    except (ValueError, struct.error) as exc:
        return ModResult(name, "MALFORMED", error=f"the REL did not parse: {exc}")

    committed = source / REL_PATH
    if not committed.exists():
        return ModResult(name, "BUILT", built=built)

    reference = parse_rel(committed.read_bytes())
    if built.digest == reference.digest:
        return ModResult(name, "IDENTICAL", built=built, reference=reference)

    differences = compare(built, reference)
    status = "STRUCTURAL" if not differences else "DIFFERENT"
    return ModResult(
        name, status, built=built, reference=reference, differences=differences
    )


#: A translation unit small enough that only the toolchain can fail it. It
#: defines the three REL entry points so the link line needs no changes.
PROBE_SOURCE = """\
int bleckProbeGlobal;
void _prolog(void) { bleckProbeGlobal = 1; }
void _epilog(void) {}
void _unresolved(void) {}
"""


@dataclass(frozen=True)
class ToolchainProbe:
    """Did the cross-compiler itself work, independently of ELF-to-REL?"""

    compiled: bool
    machine: str = ""
    sections: int = 0
    error: str = ""

    def lines(self) -> list[str]:
        if not self.compiled:
            return ["  compiler probe: FAILED", f"    {self.error}"]
        return [
            f"  compiler probe: OK -- {self.machine}, {self.sections} sections",
        ]


def probe_toolchain(chain: toolchain.Toolchain, scratch: Path) -> ToolchainProbe:
    """Compile and link one tiny module, and read the ELF back.

    ⚠️ **This is the control.** Everything below it can fail inside `pyelf2rel`,
    which runs after the compiler has already done its job -- and a report
    consisting only of failures reads as "the toolchain is not there". This says
    whether it is, so a REL failure is not misread as a missing compiler.
    """
    from elftools.elf.elffile import ELFFile  # pylint: disable=import-outside-toplevel

    work = scratch / "probe"
    work.mkdir(parents=True, exist_ok=True)
    source = work / "probe.c"
    source.write_text(PROBE_SOURCE, encoding="ascii")
    obj, elf = work / "probe.o", work / "probe.elf"

    steps = [
        [chain.compiler, *chain.compile_flags(), "-c", str(source), "-o", str(obj)],
        [chain.compiler, *chain.link_flags(), str(obj), "-o", str(elf)],
    ]
    for args in steps:
        try:
            done = subprocess.run(args, capture_output=True, text=True, check=False)
        except OSError as exc:
            return ToolchainProbe(False, error=f"{args[0]}: {exc}")
        if done.returncode != 0:
            detail = (done.stderr or done.stdout).strip().splitlines()
            return ToolchainProbe(False, error=detail[0] if detail else "no output")

    with elf.open("rb") as handle:
        image = ELFFile(handle)
        machine = image.header["e_machine"]
        sections = image.num_sections()
    return ToolchainProbe(True, machine=str(machine), sections=sections)


LEGEND = [
    "IDENTICAL   byte-for-byte equal to the reference",
    "STRUCTURAL  bytes differ; every structural field compared here agrees",
    "DIFFERENT   bytes and structure both differ; the fields are listed",
    "BUILT       compiled and parsed, but this checkout has no reference",
    "ERROR       the build failed",
    "MALFORMED   something was produced and it is not a REL",
]


def report(
    results: list[ModResult], chain: toolchain.Toolchain, probe: ToolchainProbe
) -> list[str]:
    lines = [
        "container_verify -- example mods rebuilt and compared",
        "",
        f"toolchain    {chain.name}",
        f"compiler     {chain.compiler}",
        f"extra flags  {' '.join(chain.extra_flags) or '(none)'}",
        f"compile line {' '.join(chain.compile_flags())}",
        *probe.lines(),
        "",
    ]
    for result in results:
        lines.append(f"=== {result.name}: {result.status}")
        if result.error:
            lines += [f"  {line}" for line in result.error.splitlines()]
        if result.built:
            lines.append("  built:")
            lines += [f"  {line}" for line in result.built.lines()]
        if result.reference:
            lines.append("  reference:")
            lines += [f"  {line}" for line in result.reference.lines()]
        if result.differences:
            lines.append("  differences:")
            lines += [f"    {line}" for line in result.differences]
        lines.append("")

    tally = Counter(result.status for result in results)
    lines.append("summary: " + ", ".join(f"{n} {s}" for s, n in sorted(tally.items())))
    lines.append("")
    lines += LEGEND
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mods", nargs="*", help=f"default: {' '.join(DEFAULT_MODS)}")
    parser.add_argument(
        "--mods-dir",
        default=str(REPO / "example-mods"),
        help="where the mods and their reference overlays live",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="directory holding spm.<version>.lst, overriding BLECK_SYMBOLS_DIR",
    )
    parser.add_argument(
        "--out",
        default=str(REPO / "work" / "build" / "container-verify.txt"),
        help="where the full report is written",
    )
    args = parser.parse_args(argv)

    if args.symbols:
        env.override(env.SYMBOLS_DIR, args.symbols)

    try:
        chain = toolchain.detect()
    except BleckError as exc:
        print(f"no PowerPC cross-compiler: {exc}", file=sys.stderr)
        return 2

    mods_dir = Path(args.mods_dir)
    names = args.mods or DEFAULT_MODS
    results = []
    with tempfile.TemporaryDirectory(prefix="bleck-verify-") as raw:
        scratch = Path(raw)
        probe = probe_toolchain(chain, scratch)
        for name in names:
            print(f"building {name} ...", flush=True)
            results.append(build_one(name, mods_dir, scratch))

    lines = report(results, chain, probe)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {out}")

    failed = not probe.compiled or any(result.is_failure for result in results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
