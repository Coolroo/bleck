"""What each source language needs from the cross-compiler, as data.

One `Language` value per language `bleck` compiles. `toolchain.build_rel` asks
`used_by` which are in play and then treats every unit the same way, so adding a
language means adding a value here rather than a branch there — the same shape
as `platforms/`.

Drivers are *derived* from whichever `gcc` was located, never looked up
separately, so two installed toolchains cannot be mixed (`ToolKey.PPC_GCC`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Language:
    """One source language, and how the toolchain has to be driven for it."""

    name: str

    suffixes: tuple[str, ...]
    """File extensions this language owns, lowercase."""

    driver_name: str = ""
    """What replaces `gcc` in the located compiler's filename.

    Empty means "the compiler that was located", which is how C avoids
    depending on that name containing `gcc` at all.
    """

    extra_flags: tuple[str, ...] = ()
    """Flags this language needs on top of the shared machine flags."""

    link_priority: int = 0
    """Whose driver links a module holding several languages. Highest wins."""

    needs_ctor_walk: bool = False
    """Whether the module must walk `.ctors` before handing off to the mod.

    See `script.emit.runtime_c.CTOR_BLOCK`: nothing else calls a global
    object's constructor in a freestanding REL.
    """

    install_hint: str = ""
    """What to install when this language's driver is missing."""


C = Language(name="C", suffixes=(".c",))

CXX = Language(
    name="C++",
    suffixes=(".cpp", ".cc", ".cxx"),
    driver_name="g++",
    # A REL links `-nostdlib`, so there is no unwinder and no type-info support
    # to call into. `gnu++17` rather than `c++17` because spm-headers'
    # `mod/evt_cmd.h` uses `##__VA_ARGS__`; these are the three flags that
    # repository's own `configure.py` compiles with.
    extra_flags=("-fno-exceptions", "-fno-rtti", "-std=gnu++17"),
    link_priority=1,
    needs_ctor_walk=True,
    install_hint=(
        "devkitPPC ships it as powerpc-eabi-g++; Debian's is g++-powerpc-linux-gnu"
    ),
)

#: Every language, in the order a module's build reports them.
ALL = [C, CXX]

#: Every suffix `code.sources` collects, for globbing and error messages.
SOURCE_SUFFIXES = [suffix for language in ALL for suffix in language.suffixes]


def for_source(source: Path) -> Language:
    """Which language compiles one translation unit.

    Unknown suffixes fall back to C, so a hand-written `.S` still reaches the
    driver that has always handled it.
    """
    suffix = source.suffix.lower()
    for language in ALL:
        if suffix in language.suffixes:
            return language
    return C


def used_by(sources: list[Path]) -> list[Language]:
    """The languages a set of sources needs, in `ALL` order."""
    needed = {for_source(source) for source in sources}
    return [language for language in ALL if language in needed]
