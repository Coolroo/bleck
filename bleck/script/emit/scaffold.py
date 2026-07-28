"""What a generated module is wired up to do, as values.

A banner, hooks attached to maps and button combinations, and which mod owns
which namespace. `generate` turns these into C.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from bleck.script.errors import Position, ScriptError


# Defined here rather than in `bleck.mods.manifest` because both layers need it
# and this is the lower one -- `codespec` already imports `bleck.script.emit`, so
# it costs no new import edge.
#
# ⚠️ The docstring below is PUBLISHED: pydantic copies it into `bleck mod
# schema` output as the enum's description. Keep it about what the values mean
# to someone writing a mod.json, not about where the class lives.
#
# `StrEnum` rather than `str, Enum`: the latter still inherits `Enum.__str__`,
# so every error message and every generated C comment would read
# `HookMode.REPLACE`. `StrEnum.__str__` is `str.__str__` (D99).
class HookMode(StrEnum):
    """Which side of the original a hooked mod function runs on.

    `replace` takes the function over and the original never runs. `before` runs
    the mod's function and then the original; `after` reverses that. Under both,
    the caller receives the original's return value.

    ⚠️ The value is the wire format -- `code.hooks[].mode` in `mod.json`.
    Renaming a member is free; changing a *value* breaks every manifest already
    written.
    """

    REPLACE = "replace"
    BEFORE = "before"
    AFTER = "after"

    @property
    def intercepts(self) -> bool:
        """Whether the original still runs.

        One definition, deliberately. This gates two separate things -- whether
        a wrapper is generated, and whether a derived guard word is required --
        and they were briefly written as two expressions that agreed only
        because there happened to be three modes. A fourth mode added to one
        list and not the other would emit a wrapper for a hook with nothing to
        restore, which is the recursion `_check_interception_possible` exists to
        prevent.
        """
        return self is not HookMode.REPLACE

    @property
    def means(self) -> str:
        """What this mode does, quoted back when one is misspelled."""
        return _HOOK_MODE_MEANS[self]

    @classmethod
    def parse(cls, raw: str) -> HookMode | None:
        """The mode `raw` names, or None. The one place the wire is decoded."""
        return next((mode for mode in cls if mode.value == raw), None)


#: Kept beside the enum rather than as a `means` body, so all three read as one
#: table. A dict on the class would trip `container-return` as a property.
_HOOK_MODE_MEANS = {
    HookMode.REPLACE: "the mod's function instead of the original, which never runs",
    HookMode.BEFORE: "the mod's function first, then the original",
    HookMode.AFTER: "the original first, then the mod's function",
}


# ⚠️ Unlike `HookMode`, a value here is only *part* of a wire string: it is
# what precedes the colon in `code.patches[].script`, as in `map:he1_01`. The
# whole selector is reassembled by `ScriptPatch.selector`, so that property and
# `_parse_selector` are the only two places the wire is written or read.
class PatchKind(StrEnum):
    """Which family of the game's own `evt` scripts a patch selector names.

    `map:<name>` resolves through `mapDataPtr`; `item:<id>` walks
    `itemEventDataTable`; `door:<map>:<index>` walks that map's init script for
    the descriptor array and follows `interactScript`.

    ⚠️ The value is half of a wire format. Renaming a member is free; changing a
    *value* breaks every `mod.json` that patches a script.
    """

    MAP = "map"
    ITEM = "item"
    DOOR = "door"

    @property
    def example(self) -> str:
        """How this kind is written, for an error listing what is reachable."""
        return _PATCH_KIND_EXAMPLES[self]

    @classmethod
    def parse(cls, raw: str) -> PatchKind | None:
        """The kind `raw` names, or None. The one place the wire is decoded."""
        return next((kind for kind in cls if kind.value == raw), None)


#: What each kind's target looks like. Separate from the members for the same
#: reason as `_HOOK_MODE_MEANS`: a dict in an `Enum` body reads as a member.
_PATCH_KIND_EXAMPLES = {
    PatchKind.MAP: "map:<name>",
    PatchKind.ITEM: "item:<id>",
    PatchKind.DOOR: "door:<map>:<index>",
}

#: Derived, not written out. The prose list this replaces sat two lines below
#: the tuple it was meant to describe, with nothing keeping the two in step.
SUPPORTED_SELECTORS = ", ".join(kind.example for kind in PatchKind)

#: The script the loader starts, chosen by name so reordering a file cannot
#: change which script runs.
ENTRY_SCRIPT = "main"


# ⚠️ THE ODD ONE OUT: an `IntEnum`, and the only enum here whose value is *not*
# the wire format. Two representations of one thing, and both are load-bearing:
#
#   the VALUE   is game truth -- what the game puts in `seqWork.seq`, and the
#               row it reads from `seq_data[]`. Generated C uses it.
#   the NAME    lowercased, is what `code.banner.sequences` holds in mod.json.
#
# So `json.dumps` on a member emits a NUMBER, which is not what a manifest
# wants. Serialization must go through `manifest_name`; never hand a member to
# a JSON encoder. `BannerSpec.to_json` is the one place that matters.
class Sequence(IntEnum):
    """A top-level game sequence (`spm/seqdrv.h`).

    ⚠️ Do not reorder. The values are the game's own, not bleck's.
    """

    LOGO = 0
    TITLE = 1
    GAME = 2
    MAPCHANGE = 3
    GAMEOVER = 4
    LOAD = 5

    @property
    def manifest_name(self) -> str:
        """How this sequence is written in `code.banner.sequences`."""
        return self.name.lower()

    @classmethod
    def parse(cls, raw: str) -> Sequence | None:
        """The sequence `raw` names, or None. The one place the wire is decoded."""
        return next((seq for seq in cls if seq.manifest_name == raw), None)


#: Every sequence name, for an error listing what is accepted. Derived, so a new
#: member cannot leave it stale.
SEQUENCE_NAMES = tuple(seq.manifest_name for seq in Sequence)

#: Where the banner is drawn unless a mod says otherwise. The title screen is
#: where someone looks to see which disc they put in.
DEFAULT_BANNER_SEQUENCES = (Sequence.TITLE.manifest_name,)

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
    sequences: tuple[Sequence, ...] = (Sequence.TITLE,)
    """Which sequences draw it. Already resolved from the manifest's names."""

    @property
    def flags(self) -> str:
        """The `sequences` set rendered as a C initialiser, one flag per row.

        One column per member, in value order, because the generated table is
        indexed by the sequence the game reports.
        """
        on = set(self.sequences)
        return ", ".join("1" if seq in on else "0" for seq in Sequence)


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

    kind: PatchKind
    """Which family of the game's own scripts `target` names."""

    target: str
    """The script's name in its family. For `door:` this is the MAP whose init
    script registers the descriptors, not the door itself."""

    at: int
    expect: int
    """The header word the guard compares against before writing anything.

    Its top half is the argument count, which the replacement `USER_FUNC`
    reuses -- so the patch is the same size as what it overwrites.
    """

    call: str
    """A C function in the mod's own sources, with evt's user-func signature."""

    index: int = -1
    """What `target` alone does not say.

    An item id for `item:`, a door index for `door:`, -1 for `map:`. One field
    rather than one per kind, because the generated C carries one column.
    """

    @property
    def selector(self) -> str:
        """How this patch was written in the manifest, for a comment."""
        if self.kind is PatchKind.DOOR:
            return f"{self.kind}:{self.target}:{self.index}"
        if self.kind is PatchKind.ITEM:
            return f"{self.kind}:{self.index}"
        return f"{self.kind}:{self.target}"

    @property
    def comment(self) -> str:
        argc = self.expect >> 16
        return f"/* {self.selector} +{self.at} -> {self.call}, argc {argc} */"


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

    mode: HookMode = HookMode.REPLACE
    """Which side of the original the mod's function runs on.

    Anything but `replace` needs a wrapper, and needs `guarded`: the detour
    restores `expect` to reach the original, so a hook with no derived guard
    cannot intercept. `parts.function_hooks_for` refuses that combination.
    """

    @property
    def intercepts(self) -> bool:
        """Whether the original still runs, and so whether a wrapper is needed."""
        return self.mode.intercepts

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
