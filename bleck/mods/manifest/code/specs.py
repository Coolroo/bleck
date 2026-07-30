"""The shapes a mod's `code` block parses into.

Data only -- every parser lives beside this file, so a reader chasing what a
field *means* is never walking through validation to find it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bleck.mods.errors import ManifestError
from bleck.mods.manifest.replacements import ScriptReplacement
from bleck.script import emit

#: Where a compiled code mod lands. Fixed: the Gecko loader opens this exact
#: path. One path, not one mod — several mods merge into it at compile time
#: (D78).
REL_DISC_PATH = "files/mod/mod.rel"


@dataclass(frozen=True)
class BannerSpec:
    """The on-screen label naming the loaded mod.

    On by default, since a modded disc otherwise looks stock. Opt out with
    `"banner": false`.
    """

    enabled: bool = True

    text: str = ""
    """Overrides the label. Empty means `<mod name>-<version>`."""

    sequences: list[str] = field(
        default_factory=lambda: list(emit.DEFAULT_BANNER_SEQUENCES)
    )
    """Which game sequences draw it, by name from `SEQUENCE_NAMES`."""

    def label(self, mod_name: str, version: str = "") -> str:
        """`tex-koopa-0.1.0`, or whatever `text` overrides it with.

        ⚠️ The version is what tells two builds of one mod apart, which is the
        whole point of a label on discs that are otherwise identical. Taken as
        a string rather than a `Version` because that type lives a layer up,
        and importing it here would be a cycle.
        """
        if self.text:
            return self.text
        return f"{mod_name}-{version}" if version else mod_name

    @property
    def is_default(self) -> bool:
        return (
            self.enabled
            and not self.text
            and tuple(self.sequences) == emit.DEFAULT_BANNER_SEQUENCES
        )

    def to_json(self) -> object:
        if not self.enabled:
            return False
        body: dict[str, object] = {}
        if self.text:
            body["text"] = self.text
        if tuple(self.sequences) != emit.DEFAULT_BANNER_SEQUENCES:
            body["sequences"] = list(self.sequences)
        return body


@dataclass(frozen=True)
class ComboBinding:
    """A script bound to a button combination declared in `bleck.yml`.

    The manifest names a combination, never the buttons; `bleck.yml` says which.
    """

    combo: str
    """Name of a combination in `bleck.yml`."""

    script: str
    """Name of a script in this mod's source, not a C identifier."""


@dataclass(frozen=True)
class MapHook:
    """A script attached to a map's `MapData.initScript`, so it runs on load."""

    map_name: str
    """The map's internal name, e.g. `aa4_01`. Resolved by `mapDataPtr`."""

    script: str
    """Which script in the mod's source runs when the map loads."""


#: Re-exported so a manifest reader need not know the enum lives in the emitter.
#: `map:<name>` resolves through `mapDataPtr` (D88); `item:<id>` walks
#: `itemEventDataTable` (D91), and its target may be written as a **name** --
#: `item:fire_burst` -- which `bleck/formats/items.py` turns into an id while
#: the manifest is read (D114).
PatchKind = emit.PatchKind


@dataclass(frozen=True)
class ScriptPatch:
    """One instruction of a vanilla `evt` script replaced by a call into the mod.

    Same-size replacement only: the replacement is a `USER_FUNC` carrying the
    **same argument count** as the instruction it overwrites, so any instruction
    of two words or more is patchable and no label moves — `jumptable[]` is
    cached per `EvtEntry` (D87, D91).
    """

    kind: PatchKind
    """Which family of the game's own scripts `target` names."""

    target: str
    """The script's name in that family: a map like `he1_01`, or an item id."""

    at: int
    """Word offset into the script where the replaced instruction begins."""

    expect: str
    """The opcode expected there, as written: a name or a raw header word."""

    expect_word: int
    """`expect` resolved to the header word the guard compares against."""

    call: str
    """A function in this mod's own sources, with evt's user-func signature."""

    item_id: int = -1
    """The id an `item:` target resolved to, -1 for every other kind.

    Carried rather than re-derived, because `target` keeps whatever the manifest
    said -- `fire_burst` as readily as `0x41` -- and a name is not a number.
    """

    def __post_init__(self) -> None:
        # A silent -1 here would patch item id -1 and report NOT_FOUND, which
        # reads as "the game has no such item" rather than "bleck built this
        # wrong". Every path into an item patch goes through `build_patch`.
        if self.kind is PatchKind.ITEM and self.item_id < 0:
            raise ManifestError(
                f"item patch {self.target!r} was built without a resolved id"
            )

    @property
    def selector(self) -> str:
        return f"{self.kind}:{self.target}"

    @property
    def argument_count(self) -> int:
        """Argument words the replaced instruction declares. The replacement
        carries the same count, so both are `argument_count + 1` words."""
        return self.expect_word >> 16

    @property
    def index(self) -> int:
        """What `target` alone does not say: an item id, or a door index.

        -1 for `map:`, which needs neither.
        """
        if self.kind is PatchKind.ITEM:
            return self.item_id
        if self.kind is PatchKind.DOOR:
            return int(self.target.split(":")[1], 0)
        if self.kind is PatchKind.NPC:
            return int(self.target.split(":")[0], 0)
        return -1

    @property
    def field_offset(self) -> int:
        """Byte offset of the script field within its record, -1 where unused.

        A door selector may name which of its three scripts it means, and
        omitting it means `interact`. A `npcdrv:` selector must name one --
        none of an enemy's four is the obvious default.
        """
        parts = self.target.split(":")
        if self.kind is PatchKind.DOOR:
            named = parts[2] if len(parts) == 3 else emit.DoorScript.INTERACT.value
            found = emit.DoorScript.parse(named)
        elif self.kind is PatchKind.NPC:
            found = emit.NpcScript.parse(parts[1])
        else:
            return -1
        if found is None:  # pragma: no cover -- the parsers reject these
            raise ManifestError(f"script name in {self.target!r} was never validated")
        return found.offset

    @property
    def emit_target(self) -> str:
        """The name the generated C looks up.

        For `door:` that is the MAP, not the whole selector -- the index and the
        script offset travel separately, because the runtime needs them apart.
        """
        if self.kind in (PatchKind.DOOR, PatchKind.NPC):
            return self.target.split(":")[0]
        return self.target


#: Re-exported so a manifest reader does not have to know the enum lives in the
#: emitter. `replace` takes the function over; the other two keep it, by
#: restoring its first instruction around the call rather than relocating it
#: into a trampoline (D96, D97).
HookMode = emit.HookMode


@dataclass(frozen=True)
class FunctionHook:
    """A game function whose first instruction becomes a branch into the mod.

    ⚠️ Under `replace` the original body is destroyed for the session, so the
    mod's function is the whole implementation. `before` and `after` keep it.
    """

    function: str
    """A symbol name resolved against the target's symbol list, or `0x...`.

    Resolved at **build time**, so a rename or the wrong `target` fails the
    build rather than branching into unrelated code.
    """

    call: str
    """A function in this mod's own sources, matching what it replaces."""

    mode: HookMode = HookMode.REPLACE
    """Which side of the original the mod's function runs on."""

    @property
    def intercepts(self) -> bool:
        """Whether the original still runs. Needs a guard word to be derivable."""
        return self.mode.intercepts

    @property
    def is_address(self) -> bool:
        return self.function.lower().startswith("0x")

    @property
    def address(self) -> int:
        """The address `function` names outright, or -1 when it is a symbol."""
        return int(self.function, 16) if self.is_address else -1


@dataclass(frozen=True)
class CodeSpec:
    """A mod's compiled-code half: a script, native C/C++ sources, or both.

    Scripts cover event logic; native sources reach what a script cannot, such
    as calling ordinary game functions. Both compile into one `mod.rel`.
    """

    script: str = ""
    """Path to the script source, relative to the mod directory."""

    sources: list[str] = field(default_factory=list)
    """Native sources, relative to the mod directory. Files or directories.

    `.c` compiles with gcc; `.cpp`, `.cc` and `.cxx` with the matching g++.
    """

    target: str = "eu0"
    """Game version whose symbol list resolves the functions this script calls.

    Addresses differ per version; the wrong list produces a REL that jumps into
    unrelated code.
    """

    module_id: int = 2
    """REL module id. The game's own REL is 1, so mods start at 2."""

    maps: list[MapHook] = field(default_factory=list)
    """Scripts attached to maps, so they run on arrival rather than looping."""

    combos: list[ComboBinding] = field(default_factory=list)
    """Scripts bound to button combinations named in `bleck.yml`."""

    patches: list[ScriptPatch] = field(default_factory=list)
    """Instructions replaced in the game's own scripts, in place."""

    hooks: list[FunctionHook] = field(default_factory=list)
    """Game functions branch-replaced by functions in this mod."""

    replacements: list[ScriptReplacement] = field(default_factory=list)
    """Vanilla scripts repointed at this mod's own, whole (D146).

    ⚠️ Distinct from `patches`, which rewrites one instruction in place. A
    swap is unbounded in size because nothing moves; a patch is same-size
    because a moved label would invalidate a cached jump table.
    """

    banner: BannerSpec = field(default_factory=BannerSpec)
    """The on-screen label naming this mod."""

    boot_map: str = ""
    """A map to start the game at, instead of the attract demo.

    Without one the disc only ever reaches `aa4_01` then `ls4_12` unattended.
    """

    @property
    def is_inert(self) -> bool:
        """Nothing here would put anything into a module.

        ⚠️ Reached by `"banner": false` on a mod that declares no code, which
        since D176 is how a disc asks to carry no `mod.rel` at all. It has to be
        answered before the toolchain runs: an empty module has no sections, and
        `elf2rel` fails on one with `max() iterable argument is empty` rather
        than anything a reader could act on.
        """
        return not (
            self.script
            or self.sources
            or self.boot_map
            or self.patches
            or self.hooks
            or self.replacements
            or self.maps
            or self.combos
            or self.banner.enabled
        )

    @property
    def has_boot_map(self) -> bool:
        return bool(self.boot_map)

    @property
    def has_combos(self) -> bool:
        return bool(self.combos)

    @property
    def has_hooks(self) -> bool:
        return bool(self.hooks)

    @property
    def has_patches(self) -> bool:
        return bool(self.patches)

    @property
    def has_maps(self) -> bool:
        return bool(self.maps)

    @property
    def has_script(self) -> bool:
        return bool(self.script)

    @property
    def has_sources(self) -> bool:
        return bool(self.sources)

    def to_json(self) -> dict[str, object]:  # pylint: disable=container-return
        body: dict[str, object] = {}
        if self.script:
            body["script"] = self.script
        if self.sources:
            body["sources"] = list(self.sources)
        body["target"] = self.target
        body["module_id"] = self.module_id
        if self.maps:
            body["maps"] = {hook.map_name: hook.script for hook in self.maps}
        if self.combos:
            body["combos"] = {b.combo: b.script for b in self.combos}
        if self.patches:
            body["patches"] = [
                {
                    "script": patch.selector,
                    "at": patch.at,
                    "expect": patch.expect,
                    "call": patch.call,
                }
                for patch in self.patches
            ]
        if self.hooks:
            body["hooks"] = [
                {"function": hook.function, "call": hook.call, "mode": hook.mode}
                for hook in self.hooks
            ]
        if self.boot_map:
            body["boot"] = self.boot_map
        # Written only when it differs from the default.
        if not self.banner.is_default:
            body["banner"] = self.banner.to_json()
        return body
