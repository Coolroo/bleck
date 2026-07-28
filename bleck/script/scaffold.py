"""What a generated module is wired up to do, as values.

Split from `emit.py`, which was doing two jobs: deciding what a module contains,
and writing it out. These are the *what* — a banner, hooks attached to maps and
button combinations, which mod owns which namespace. `emit.py` turns them into C.

The split also fixes a dependency: several of these are constructed by
`bleck/mods/`, which had to import the whole code generator to name a `MapHook`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bleck.script.errors import Position, ScriptError

#: The script the loader starts. Chosen by name rather than by position so that
#: reordering a file cannot silently change which script runs.
ENTRY_SCRIPT = "main"

#: The game's sequences, in order (spm/seqdrv.h). A name's index is both the
#: value the game puts in `seqWork.seq` and the row it uses in `seq_data[]`.
SEQUENCE_NAMES = ("logo", "title", "game", "mapchange", "gameover", "load")

#: Where the banner is drawn unless a mod says otherwise. The title screen is
#: where someone checks which disc they are running.
DEFAULT_BANNER_SEQUENCES = ("title",)

#: The script a `code.boot` declaration is desugared into.
BOOT_SCRIPT = "bleck_boot"

#: How long the boot script waits before asking for the map change.
#:
#: Two seconds, and ✅ **measured, not superstition** (D72): without it the map
#: loader stops at stage 11 and never resumes.
BOOT_DELAY_FRAMES = 120


#: Namespace for everything this module generates.
#:
#: A *program's* identifiers take a per-mod suffix on top of this, so two mods
#: that each declare `script main` do not both emit `bleck_script_main`. See
#: `prefix_for` and `docs/plan-merging.md`.
_PREFIX = "bleck_"

#: One bit per map hook in `bleck_map_pending`, so this is a hard ceiling.
#:
#: ⚠️ Exceeding it used to be silent: `1 << i` past bit 31 is undefined
#: behaviour, and the symptom would be hooks corrupting each other rather than
#: anything failing. Unreachable while a disc holds one mod; **plausible the
#: moment several merge**, which is why it is checked now rather than then.
MAX_MAP_HOOKS = 32

#: Characters allowed in a mod's generated namespace.
_SLUG_ILLEGAL = re.compile(r"[^a-z0-9_]+")


def mod_slug(name: str) -> str:
    """A mod name reduced to something usable inside a C identifier.

    Readable rather than hashed, deliberately: a build log, a disassembly and a
    linker error should all still say which mod a symbol came from. `hard-mode`
    becomes `hard_mode`, not `a3f19c`.
    """
    slug = _SLUG_ILLEGAL.sub("_", name.strip().lower()).strip("_")
    # A leading digit is legal in the middle of an identifier but not at the
    # start of one, and mod names are otherwise unrestricted.
    if slug and slug[0].isdigit():
        slug = f"m{slug}"
    return slug


def prefix_for(name: str) -> str:
    """The identifier namespace for one mod's generated code."""
    slug = mod_slug(name)
    if not slug:
        raise ScriptError(
            f"mod name {name!r} has no characters usable in an identifier, so "
            f"its generated symbols cannot be named.",
            Position(),
        )
    return f"{_PREFIX}{slug}_"


@dataclass(frozen=True)
class Banner:
    """An on-screen label naming the mod that is loaded.

    A disc looks identical to a stock one until something visibly differs, so a
    player juggling several builds has no way to tell which is in the drive.
    This draws the answer on the screen.
    """

    text: str
    sequences: tuple[int, ...] = (1,)
    """Sequence indices to draw on. Defaults to the title screen."""

    @property
    def flags(self) -> str:
        """The `sequences` set rendered as a C initialiser, one flag per row."""
        on = set(self.sequences)
        return ", ".join(
            "1" if index in on else "0" for index in range(len(SEQUENCE_NAMES))
        )


@dataclass(frozen=True)
class MapHook:
    """A compiled script attached to one map's init script."""

    map_name: str
    script: str
    """Name of a script in the same program, not a C identifier."""


@dataclass(frozen=True)
class ComboHook:
    """A button combination that starts a script.

    The mask arrives already resolved: the manifest names a combination and
    `bleck.yml` says which buttons it is, so by the time the emitter sees it
    there is nothing left to look up. `name` is carried only so the generated C
    can say which combination a table row is.
    """

    name: str
    mask: int
    script: str

    @property
    def comment(self) -> str:
        return f"/* {self.name} */"


#: One bit per combination in `bleck_combo_down`, so this is a hard ceiling.
#: Shared with map hooks, which have the same shape of bitmask.
MAX_COMBOS = 32


@dataclass(frozen=True)
class Scaffolding:
    """Everything the generated module does besides run its entry script.

    Grouped rather than passed as four parallel arguments because they are one
    idea — what this module is wired up to do — and because they kept arriving
    together at every call site anyway. Each one adds a line to the same
    per-frame sequence hook.
    """

    map_hooks: list[MapHook] = field(default_factory=list)
    """Scripts started on arrival at a named map."""

    banner: Banner | None = None
    """The on-screen label naming the mod."""

    boot_script: str = ""
    """A script started once, on the first frame of gameplay."""

    combos: list[ComboHook] = field(default_factory=list)
    """Button combinations that start scripts."""

    prefix: str = _PREFIX
    """Namespace for this program's identifiers.

    Default reproduces what a single-mod build has always emitted, byte for
    byte. `prefix_for("hard-mode")` gives `bleck_hard_mode_`, which is what
    merging several mods into one translation unit needs (plan-merging.md).

    Only *per-program* names take it -- scripts, strings, map-name literals.
    The shared runtime is one-per-disc and keeps its fixed names: `_prolog`,
    `mod_prolog`, `bleck_after_seq`, `bleck_seq0..5`, and the hook tables. Those
    are installed once however many mods contribute, so namespacing them would
    be wrong rather than merely unnecessary.
    """

    require_entry: bool = True
    """Whether a script called `main` must exist.

    Off for `bleck script check`, where insisting on an entry point would be a
    rule about mods imposed on someone checking a file's syntax.
    """

    @property
    def needs_entry_script(self) -> bool:
        """A mod needs `main` only when nothing else can start a script.

        Map hooks, boot maps and button combinations each bring their own way
        in, so requiring `main` alongside any of them would be ceremony.
        """
        return (
            self.require_entry
            and not self.map_hooks
            and not self.boot_script
            and not self.combos
        )
