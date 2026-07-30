"""Which overlay files a build wrote, so the next build can take them back.

A mod's `overlay/` holds two kinds of file that look identical once written:
what the author put there, and what `bleck` generated from a declaration. When
a declaration goes away the generated file does not, and the next disc ships
the previous answer.

⛔ **That is not hypothetical.** D156 removed a boss's CSV row, rebuilt, and the
boss was still there — `overlay/files/setup/an1_02.dat` had been generated two
minutes earlier and the rebuild left it. The control *passed while being wrong*,
which is the dangerous direction, and two plausible-sounding readings were
written down before anyone checked the file's timestamp.

So a build records exactly what it wrote, and the next one removes what it no
longer produces.

⚠️ **The ledger is taken from build results, never re-derived from patterns.**
Re-deriving would be a second implementation of "where does a placement land",
and the two would drift; worse, a pattern that guessed wrong would delete
somebody's hand-written overlay. Only a path this tool recorded writing is a
path this tool will remove.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from bleck.mods import registry as mod_registry
from bleck.mods.registry import Mod

#: Under the build directory, not the mod: it is regenerable state, and a file
#: inside the mod would need excluding from both the disc plan and `mod pack`.
LEDGER_DIR = ".generated"

SCHEMA = 1


@dataclass(frozen=True)
class Sweep:
    """What clearing one mod's previous output removed."""

    mod: str
    removed: list[str] = field(default_factory=list)
    unowned: list[str] = field(default_factory=list)
    """Files that look generated but were not recorded. Reported, never removed
    -- see `suspicious`."""

    @property
    def notes(self) -> list[str]:  # pylint: disable=container-return
        if not self.unowned:
            return []
        listed = "\n    ".join(self.unowned)
        return [
            f"{self.mod}: {len(self.unowned)} build output(s) in the overlay "
            f"that this build did not write:\n    {listed}\n"
            f"  Left alone rather than deleted, but a disc ships whatever is "
            f"there. Delete them if they are from an older build."
        ]


def ledger_path(mod: Mod, root: Path | None = None) -> Path:
    build_root = root or mod_registry.build_root()
    return build_root / LEDGER_DIR / f"{mod.name}.json"


def read(mod: Mod, root: Path | None = None) -> list[str]:  # pylint: disable=container-return
    """Overlay paths the previous build recorded writing.

    A missing or unreadable ledger reads as empty: it means "nothing is known
    to be owned", which makes the sweep do nothing rather than guess.
    """
    path = ledger_path(mod, root)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return []
    written = raw.get("written", [])
    if not isinstance(written, list):
        return []
    return [entry for entry in written if isinstance(entry, str)]


def record(mod: Mod, written: list[Path], root: Path | None = None) -> None:
    """Note what this build put in `mod`'s overlay.

    Paths outside the overlay are dropped rather than refused: a build result
    may name intermediates, and only overlay content can go stale on a disc.
    """
    inside = sorted(
        {
            relative
            for path in written
            if (relative := _within_overlay(mod, path)) is not None
        }
    )
    path = ledger_path(mod, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA, "mod": mod.name, "written": inside}, indent=2),
        encoding="utf-8",
    )


def _within_overlay(mod: Mod, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(mod.overlay.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def sweep(mod: Mod, root: Path | None = None) -> Sweep:
    """Remove what the previous build wrote, before this one writes again.

    ⚠️ Runs *before* compiling and placement, not after. The disc plan comes
    from walking `overlay/`, so a file removed later would already be in it.
    """
    removed: list[str] = []
    for relative in read(mod, root):
        target = mod.overlay / relative
        if not target.is_file():
            continue
        target.unlink()
        removed.append(relative)
        _prune_empty(mod.overlay, target.parent)
    return Sweep(mod=mod.name, removed=removed, unowned=suspicious(mod, root))


def _prune_empty(stop: Path, directory: Path) -> None:
    """Drop directories a removal emptied, up to but never including `stop`.

    An empty `files/map/an1_02.bin/` left behind is an archive with no members,
    which the plan would carry as an edit to nothing.
    """
    current = directory
    while current != stop and stop in current.parents:
        try:
            next(current.iterdir())
            return
        except StopIteration:
            current.rmdir()
        except OSError:
            return
        current = current.parent


#: Overlay paths nobody writes by hand. Used to *report* an unowned file, never
#: to remove one.
#:
#: ⛔ `files/setup/` is deliberately **not** here, though a build does generate
#: those. Vendoring and editing a setup file by hand is supported -- it is what
#: the D62 duplicate warning is about -- so listing it would nag on every build
#: of a mod that had done nothing wrong. A warning that fires when nothing is
#: wrong teaches people to skip the one that matters (D122).
GENERATED_SHAPES = ("files/mod/mod.rel",)


def suspicious(mod: Mod, root: Path | None = None) -> list[str]:  # pylint: disable=container-return
    """Overlay files that look generated but are not in the ledger.

    Catches the case the ledger cannot: `work/` wiped while `overlay/` survived,
    or a file written by a `bleck` old enough to have kept no ledger.
    """
    owned = set(read(mod, root))
    return [
        relative
        for relative in mod.overlay_paths()
        if relative not in owned and relative.startswith(GENERATED_SHAPES)
    ]
