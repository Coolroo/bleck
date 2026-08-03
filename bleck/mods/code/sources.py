"""Finding a mod's C and C++ files, and reading what they define.

Split from `parts` because everything here answers a question about *text on
disk* — which files, which functions, does one of them define `mod_prolog` —
and none of it needs a manifest, a symbol table or the emitter. `patches` and
`hooks` both check a declared name against `defined_functions`, and both would
otherwise have to reach into the module that assembles a build.

⚠️ **The scan is a regex over comment-stripped source, not a parse.** A
definition produced by a macro will not match, and the cost of that is a build
error naming what *was* found rather than a silent miss — which is the trade
worth making, because the alternative failure is `elf2rel` reporting the mod's
own function as a missing *game* symbol.
"""

from __future__ import annotations

import re
from pathlib import Path

from bleck.backends import languages
from bleck.mods.code.errors import CodeError
from bleck.mods.manifest import CodeSpec
from bleck.mods.registry import Mod

#: Where `bleck.h` lives, always on a mod's include path so a source can
#: `#include <bleck.h>` and use the tag macros.
BLECK_INCLUDE = Path(__file__).resolve().parent / "include"

#: What `code.sources` accepts, as a phrase for error messages.
_SUFFIX_LIST = ", ".join(languages.SOURCE_SUFFIXES)

#: Comments, stripped first: mods quote "define `mod_prolog`" from the docs in
#: a comment, and matching that prose reports a false collision.
_C_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)

#: A *definition*, not a declaration: the body brace is what makes it one.
#: `extern void mod_prolog(void);` collides with nothing.
_MOD_PROLOG_DEFINITION = re.compile(r"\bvoid\s+mod_prolog\s*\([^)]*\)\s*\{")

#: A function *definition*: same shape as `_MOD_PROLOG_DEFINITION`, but for any
#: name, so a typo can be matched against what the sources actually define.
#: One level of nesting, so a function-pointer parameter still matches. A
#: definition produced by a macro will not -- that costs a build error naming
#: what was found, not a silent miss.
_ANY_DEFINITION = re.compile(r"\b([A-Za-z_]\w*)\s*\((?:[^()]|\([^()]*\))*\)\s*\{")

#: `if (x) {` matches the pattern above and is not a function.
_NOT_A_FUNCTION = frozenset({"if", "for", "while", "switch", "catch", "return"})


def collect_sources(mod: Mod, spec: CodeSpec) -> list[Path]:
    """Resolve `code.sources` to actual C and C++ files.

    A directory entry contributes every source beneath it, sorted, so a build
    does not depend on filesystem ordering.
    """
    # pylint: disable=container-return
    found: list[Path] = []
    for entry in spec.sources:
        path = mod.root / entry
        if path.is_dir():
            # A set first: Windows globs case-insensitively, so `*.c` and `*.cc`
            # can both match the same file.
            seen = {
                match
                for suffix in languages.SOURCE_SUFFIXES
                for match in path.rglob(f"*{suffix}")
            }
            if not seen:
                raise CodeError(f"{mod.name}: no {_SUFFIX_LIST} files under {path}")
            found += sorted(seen)
        elif path.exists():
            found.append(path)
        else:
            raise CodeError(
                f"{mod.name}: no source at {path}\n"
                f"  mod.json lists {entry!r} in 'code.sources'"
            )
    _check_cxx_prolog(mod, found)
    return found


def needs_ctor_walk(sources: list[Path]) -> bool:
    """Whether these sources oblige `_prolog` to walk `.ctors`."""
    return any(language.needs_ctor_walk for language in languages.used_by(sources))


def defines_mod_prolog(source: Path) -> bool:
    """Whether a source file supplies its own `mod_prolog`.

    `bleck` emits a *weak* one (see `runtime_c.MOD_HOOK`), so one mod may
    override it; two is a duplicate symbol.
    """
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_MOD_PROLOG_DEFINITION.search(_C_COMMENT.sub(" ", text)))


def _check_cxx_prolog(mod: Mod, sources: list[Path]) -> None:
    """A C++ `mod_prolog` must have C linkage, or it is never called.

    `bleck`'s weak definition has C linkage, so a mangled `mod_prolog` does not
    override it: the module links, loads, and silently runs nothing.
    """
    for source in sources:
        if languages.for_source(source) is not languages.CXX:
            continue
        if not defines_mod_prolog(source):
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        if 'extern "C"' in _C_COMMENT.sub(" ", text):
            continue
        raise CodeError(
            f"{mod.name}: {source} defines `mod_prolog` with C++ linkage, so "
            f"its name is mangled and bleck's own definition wins.\n"
            f'  Write `extern "C" void mod_prolog(void)` instead -- otherwise '
            f"the module loads and does nothing."
        )


def defined_functions(sources: list[Path]) -> list[str]:
    """Every function these sources define, in order, comments stripped."""
    # pylint: disable=container-return
    names: list[str] = []
    for source in sources:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _ANY_DEFINITION.finditer(_C_COMMENT.sub(" ", text)):
            if match[1] not in names and match[1] not in _NOT_A_FUNCTION:
                names.append(match[1])
    return names
