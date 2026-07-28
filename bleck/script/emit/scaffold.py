"""What a generated module is wired up to do, as values.

A banner, hooks attached to maps and button combinations, and which mod owns
which namespace. `generate` turns these into C.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bleck.script.errors import Position, ScriptError

#: The script the loader starts, chosen by name so reordering a file cannot
#: change which script runs.
ENTRY_SCRIPT = "main"

#: The game's sequences, in order (spm/seqdrv.h). A name's index is both the
#: value the game puts in `seqWork.seq` and the row it uses in `seq_data[]`.
SEQUENCE_NAMES = ("logo", "title", "game", "mapchange", "gameover", "load")

#: Where the banner is drawn unless a mod says otherwise.
DEFAULT_BANNER_SEQUENCES = ("title",)

#: The script a `code.boot` declaration is desugared into.
BOOT_SCRIPT = "bleck_boot"

#: How long the boot script waits before asking for the map change. ✅ Measured
#: (D72): without it the map loader stops at stage 11 and never resumes.
BOOT_DELAY_FRAMES = 120


#: Namespace for everything this module generates. Per-program identifiers take
#: a per-mod suffix on top; see `prefix_for` and `docs/plan-merging.md`.
_PREFIX = "bleck_"

#: One bit per map hook in `bleck_map_pending`, so a hard ceiling.
#: ⚠️ `1 << i` past bit 31 is undefined behaviour, and the symptom would be
#: hooks corrupting each other rather than a failure. Reachable once mods merge.
MAX_MAP_HOOKS = 32

#: Characters allowed in a mod's generated namespace.
_SLUG_ILLEGAL = re.compile(r"[^a-z0-9_]+")


def mod_slug(name: str) -> str:
    """A mod name reduced to something usable inside a C identifier.

    Readable rather than hashed so build logs and linker errors still name the
    mod: `hard-mode` becomes `hard_mode`, not `a3f19c`.
    """
    slug = _SLUG_ILLEGAL.sub("_", name.strip().lower()).strip("_")
    # A leading digit is not legal at the start of an identifier.
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
    """An on-screen label naming the mod that is loaded."""

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

    The mask arrives already resolved from `bleck.yml`; `name` is carried only
    so the generated C can label the table row.
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
class ScriptPatch:
    """One instruction of a vanilla script replaced by a call into the module.

    Everything is already resolved: the manifest's selector has become a kind
    and a name the generated C can look up, and `expect` a header word.
    """

    kind: str
    """Which family of script `target` names: `map` or `item`."""

    target: str
    at: int
    expect: int
    """The header word the guard compares against before writing anything.

    Its top half is the argument count, which the replacement `USER_FUNC`
    reuses -- so the patch is the same size as what it overwrites.
    """

    call: str
    """A C function in the mod's own sources, with evt's user-func signature."""

    item_id: int = -1
    """The item `target` names, for `item` patches. -1 otherwise."""

    @property
    def comment(self) -> str:
        argc = self.expect >> 16
        return f"/* {self.kind}:{self.target} +{self.at} -> {self.call}, argc {argc} */"


@dataclass(frozen=True)
class FunctionHook:
    """A game function whose first instruction becomes a branch into the mod.

    Everything is resolved: the manifest's symbol name has become an address,
    and the guard word has been read out of the base disc's `main.dol`.

    ⚠️ `replace` destroys the original for the session. `before` and `after`
    keep it, at the cost of two cache flushes per call.
    """

    call: str
    """The C function in the mod's sources that runs."""

    address: int
    """Where the branch is written. -1 when the symbol is left to the linker."""

    symbol: str = ""
    """The game symbol, when the manifest named one. Empty for a raw address."""

    expect: int = 0
    """The instruction word `main.dol` actually has there."""

    guarded: bool = False
    """Whether `expect` was derived. ⚠️ Never set for a guard that was guessed.

    False means the address is not in the DOL -- a REL address, say -- so the
    build could not read what is there. The hook then installs unguarded.
    """

    mode: str = "replace"
    """`replace`, `before` or `after`.

    Anything but `replace` needs a wrapper, and needs `guarded`: the detour
    restores `expect` to reach the original, so a hook with no derived guard
    cannot intercept. `parts.function_hooks_for` refuses that combination.
    """

    @property
    def intercepts(self) -> bool:
        """Whether the original still runs, and so whether a wrapper is needed."""
        return self.mode != "replace"

    @property
    def named(self) -> str:
        return self.symbol or f"0x{self.address:08X}"

    @property
    def comment(self) -> str:
        guard = f"expect {self.expect:08X}" if self.guarded else "UNGUARDED"
        return f"/* {self.named} -> {self.call}, {self.mode}, {guard} */"


@dataclass(frozen=True)
class Scaffolding:
    """Everything the generated module does besides run its entry script.

    Each field adds a line to the same per-frame sequence hook.
    """

    map_hooks: list[MapHook] = field(default_factory=list)
    """Scripts started on arrival at a named map."""

    banner: Banner | None = None
    """The on-screen label naming the mod."""

    boot_script: str = ""
    """A script started once, on the first frame of gameplay."""

    combos: list[ComboHook] = field(default_factory=list)
    """Button combinations that start scripts."""

    patches: list[ScriptPatch] = field(default_factory=list)
    """Instructions replaced in the game's own scripts, applied at `_prolog`."""

    function_hooks: list[FunctionHook] = field(default_factory=list)
    """Game functions branch-replaced by the mod's own, installed at `_prolog`."""

    prefix: str = _PREFIX
    """Namespace for per-program identifiers, so merged mods do not collide.

    The shared runtime (`_prolog`, `bleck_after_seq`, the hook tables) is
    one-per-disc and keeps fixed names. See `docs/plan-merging.md`.
    """

    require_entry: bool = True
    """Whether a script called `main` must exist. Off for `bleck script check`."""

    run_cxx_ctors: bool = False
    """Whether `_prolog` walks `.ctors`. Set when the mod has C++ sources."""

    @property
    def needs_entry_script(self) -> bool:
        """A mod needs `main` only when nothing else can start a script."""
        return (
            self.require_entry
            and not self.map_hooks
            and not self.boot_script
            and not self.combos
            and not self.patches
            and not self.function_hooks
        )
