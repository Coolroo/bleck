"""A mod's `code` block: scripts, native sources, map hooks, combos, boot map
and banner.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from bleck.mods.errors import ManifestError
from bleck.script import emit, evt

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
    """Overrides the label. Empty means `mod_loaded: <mod name>`."""

    sequences: list[str] = field(
        default_factory=lambda: list(emit.DEFAULT_BANNER_SEQUENCES)
    )
    """Which game sequences draw it, by name from `SEQUENCE_NAMES`."""

    def label(self, mod_name: str) -> str:
        return self.text or f"mod_loaded: {mod_name}"

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


#: Selector kinds `code.patches[].script` accepts. Only `map` is implemented;
#: `item:` and `door:` scripts are reachable by other means and untested (D89).
PATCH_KINDS = ("map",)


@dataclass(frozen=True)
class _Selector:
    """A `code.patches[].script` value split into its two halves."""

    kind: str
    target: str


@dataclass(frozen=True)
class ScriptPatch:
    """One instruction of a vanilla `evt` script replaced by a call into the mod.

    Same-size replacement only: `USER_FUNC f` with no arguments is two words, so
    the instruction it overwrites must be two words too. Anything else moves
    labels, and `jumptable[]` is cached per `EvtEntry` (D87).
    """

    kind: str
    """Which family of script `target` names. Only `map` today."""

    target: str
    """The script's name in that family, e.g. the map `he1_01`."""

    at: int
    """Word offset into the script where the replaced instruction begins."""

    expect: str
    """The opcode expected there, as written: a name or a raw header word."""

    expect_word: int
    """`expect` resolved to the header word the guard compares against."""

    call: str
    """A function in this mod's own sources, with evt's user-func signature."""

    @property
    def selector(self) -> str:
        return f"{self.kind}:{self.target}"


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

    banner: BannerSpec = field(default_factory=BannerSpec)
    """The on-screen label naming this mod."""

    boot_map: str = ""
    """A map to start the game at, instead of the attract demo.

    Without one the disc only ever reaches `aa4_01` then `ls4_12` unattended.
    """

    @property
    def has_boot_map(self) -> bool:
        return bool(self.boot_map)

    @property
    def has_combos(self) -> bool:
        return bool(self.combos)

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
        if self.boot_map:
            body["boot"] = self.boot_map
        # Written only when it differs from the default.
        if not self.banner.is_default:
            body["banner"] = self.banner.to_json()
        return body


def _parse_code(raw: object, source: str) -> CodeSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: 'code' must be an object")

    script = raw.get("script", "")
    if not isinstance(script, str):
        raise ManifestError(f"{source}: 'code.script' must be a path")

    sources = raw.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise ManifestError(f"{source}: 'code.sources' must be a list of paths")

    boot = _parse_boot(raw.get("boot"), source)
    combos = _parse_combos(raw.get("combos"), source)
    patches = _parse_patches(raw.get("patches"), source)

    if not script and not sources and not boot:
        raise ManifestError(
            f"{source}: 'code' needs a 'script', 'sources', 'boot', or a "
            f"combination -- otherwise there is nothing to compile"
        )

    module_id = raw.get("module_id", 2)
    if not isinstance(module_id, int) or isinstance(module_id, bool):
        raise ManifestError(f"{source}: 'code.module_id' must be a whole number")
    # Module 0 is the DOL and 1 is the game's own REL; either would collide.
    if module_id < 2:
        raise ManifestError(
            f"{source}: 'code.module_id' must be 2 or more "
            f"(0 is the game binary, 1 is its own REL)"
        )

    return CodeSpec(
        script=script,
        sources=list(sources),
        target=str(raw.get("target", "eu0")),
        module_id=module_id,
        maps=_parse_maps(raw.get("maps"), source),
        combos=combos,
        patches=patches,
        banner=_parse_banner(raw.get("banner"), source),
        boot_map=boot,
    )


#: A map's name as the disc spells it: `he1_01`, `aa4_01`. Enforced because it
#: is interpolated into generated script source.
_MAP_NAME_RE = re.compile(r"^[a-z0-9_]{1,16}$")


def _parse_boot(raw: object, source: str) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ManifestError(
            f"{source}: 'code.boot' must be a map name like 'he1_01', not "
            f"{type(raw).__name__}"
        )
    name = raw.strip()
    if not name:
        return ""
    if not _MAP_NAME_RE.match(name):
        raise ManifestError(
            f"{source}: {raw!r} is not a map name. They look like 'he1_01' -- "
            f"lowercase letters, digits and underscores.\n"
            f"  `bleck maps` lists all 383 of them."
        )
    return name


def _parse_banner(raw: object, source: str) -> BannerSpec:
    """Read `code.banner`: absent, a boolean, or an object."""
    if raw is None or raw is True:
        return BannerSpec()
    if raw is False:
        return BannerSpec(enabled=False)
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'code.banner' must be an object or false, not "
            f"{type(raw).__name__}"
        )

    text = raw.get("text", "")
    if not isinstance(text, str):
        raise ManifestError(f"{source}: 'code.banner.text' must be a string")

    sequences = raw.get("sequences", list(emit.DEFAULT_BANNER_SEQUENCES))
    if not isinstance(sequences, list) or not all(isinstance(s, str) for s in sequences):
        raise ManifestError(
            f"{source}: 'code.banner.sequences' must be a list of sequence names"
        )
    for name in sequences:
        if name not in emit.SEQUENCE_NAMES:
            known = ", ".join(emit.SEQUENCE_NAMES)
            raise ManifestError(
                f"{source}: unknown sequence {name!r} in "
                f"'code.banner.sequences'\n  known sequences are: {known}"
            )
    if not sequences:
        raise ManifestError(
            f"{source}: 'code.banner.sequences' is empty, so the banner would "
            f'never draw -- use "banner": false to turn it off'
        )

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ManifestError(f"{source}: 'code.banner.enabled' must be true or false")

    return BannerSpec(enabled=enabled, text=text, sequences=list(sequences))


def _parse_maps(raw: object, source: str) -> list[MapHook]:
    """Read `code.maps`, an object of map name -> script name.

    An object, not a list: a map has one init script, so a duplicate entry
    should be inexpressible rather than validated.
    """
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'code.maps' must be an object of "
            f'map name -> script name, e.g. {{"aa4_01": "on_arrive"}}'
        )

    hooks: list[MapHook] = []
    for map_name, script in raw.items():
        if not isinstance(script, str) or not script:
            raise ManifestError(
                f"{source}: 'code.maps.{map_name}' must name a script in this mod"
            )
        hooks.append(MapHook(map_name=map_name, script=script))
    return hooks


def _parse_combos(raw: object, source: str) -> list[ComboBinding]:
    """Read `code.combos`, an object of combination name -> script name.

    Combination names are not validated here: `bleck.yml` defines them, so the
    check lives where the config is loaded and can list what is defined.
    """
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'code.combos' must be an object of "
            f'combo name -> script name, e.g. {{"start_map": "warp_home"}}'
        )

    bindings: list[ComboBinding] = []
    for combo, script in raw.items():
        if not isinstance(script, str) or not script:
            raise ManifestError(
                f"{source}: 'code.combos.{combo}' must name a script in this mod"
            )
        bindings.append(ComboBinding(combo=str(combo), script=script))
    return bindings


#: A C identifier, since `call` is emitted into generated C verbatim.
_C_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: The replacement is always `USER_FUNC f` with no extra arguments: the header
#: `EVT_HELPER_CMD(1, 92)` and the pointer. Two words, so the instruction it
#: overwrites must declare exactly one argument too.
PATCH_ARGUMENT_COUNT = 1

#: Why a different size is not offered, said once and quoted by the errors.
_SAME_SIZE_ONLY = (
    "  Only same-size replacement is supported: a shorter or longer "
    "instruction moves every label after it, and each running script caches "
    "its jump table when it starts (D87)."
)


def _parse_patches(raw: object, source: str) -> list[ScriptPatch]:
    """Read `code.patches`, a list of in-place bytecode replacements."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError(
            f"{source}: 'code.patches' must be a list of patch objects, e.g. "
            f'[{{"script": "map:he1_01", "at": 0, "expect": "DEBUG_PUT_MSG", '
            f'"call": "on_map_init"}}]'
        )
    return [
        _parse_patch(entry, f"{source}: 'code.patches[{i}]'")
        for i, entry in enumerate(raw)
    ]


def _parse_patch(raw: object, where: str) -> ScriptPatch:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    unknown = sorted(set(raw) - {"script", "at", "expect", "call"})
    if unknown:
        raise ManifestError(
            f"{where} has unknown field(s): {', '.join(unknown)}\n"
            f"  A patch takes 'script', 'at', 'expect' and 'call'."
        )
    for name in ("script", "expect", "call"):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ManifestError(f"{where} needs a non-empty {name!r} string")
    at = raw.get("at")
    if not isinstance(at, int) or isinstance(at, bool):
        raise ManifestError(
            f"{where}: 'at' must be a whole number of words from the start of "
            f"the script, not {type(at).__name__}"
        )
    return build_patch(
        str(raw["script"]), at, str(raw["expect"]), str(raw["call"]), where
    )


def build_patch(script: str, at: int, expect: str, call: str, where: str) -> ScriptPatch:
    """Validate one patch's four fields and resolve `expect` to a header word.

    Shared with the JSON API so both surfaces reject the same things.
    """
    selector = _parse_selector(script, where)
    if at < 0:
        raise ManifestError(
            f"{where}: 'at' is {at}, but a word offset cannot be negative"
        )
    if not _C_NAME_RE.match(call):
        raise ManifestError(
            f"{where}: 'call' is {call!r}, which is not a C function name.\n"
            f"  It names a function in this mod's own sources, e.g. 'on_map_init'."
        )
    return ScriptPatch(
        kind=selector.kind,
        target=selector.target,
        at=at,
        expect=expect,
        expect_word=_parse_expect(expect, where),
        call=call,
    )


def _parse_selector(raw: str, where: str) -> _Selector:
    """Split `map:he1_01` into its kind and its target.

    The prefix is what leaves room for `item:` and `door:` scripts later, which
    are known to exist but are untested (D89).
    """
    kind, _, target = raw.partition(":")
    supported = ", ".join(f"{name}:<name>" for name in PATCH_KINDS)
    if kind not in PATCH_KINDS or not target:
        raise ManifestError(
            f"{where}: 'script' is {raw!r}, which names no script bleck can "
            f"reach.\n  Supported selectors: {supported}.\n"
            f"  'map:he1_01' patches that map's init script."
        )
    if not _MAP_NAME_RE.match(target):
        raise ManifestError(
            f"{where}: {target!r} is not a map name. They look like 'he1_01' -- "
            f"lowercase letters, digits and underscores.\n"
            f"  `bleck maps` lists all 383 of them."
        )
    return _Selector(kind=kind, target=target)


def _parse_expect(raw: str, where: str) -> int:
    """Resolve `expect` -- an opcode name or a raw header word -- to a word."""
    text = raw.strip()
    if text.lower().startswith("0x"):
        try:
            word = int(text, 16)
        except ValueError:
            raise ManifestError(
                f"{where}: 'expect' is {raw!r}, which is neither an opcode name "
                f"nor a hexadecimal header word like '0x00010072'"
            ) from None
        if not 0 <= word <= 0xFFFFFFFF:
            raise ManifestError(f"{where}: 'expect' {raw!r} is not a 32-bit word")
        if (word >> 16) != PATCH_ARGUMENT_COUNT:
            raise ManifestError(
                f"{where}: 'expect' is {raw!r}, which declares {word >> 16} "
                f"argument(s) and so is {(word >> 16) + 1} words, but the "
                f"USER_FUNC that replaces it is always 2.\n{_SAME_SIZE_ONLY}"
            )
        return word

    opcode = evt.opcode_named(text)
    if opcode is None:
        names = [op.name for op in evt.Opcode]
        close = difflib.get_close_matches(text.upper(), names, n=1, cutoff=0.6)
        hint = (
            f"\n  Did you mean {close[0]!r}?"
            if close
            else "\n  Names come from spm/evtmgr_cmd.h, such as 'DEBUG_PUT_MSG'."
        )
        raise ManifestError(
            f"{where}: 'expect' is {raw!r}, which names no evt opcode.{hint}\n"
            f'  Or give the header word directly, e.g. "0x00010072".'
        )

    argc = evt.argument_count(opcode)
    if argc is not None and argc != PATCH_ARGUMENT_COUNT:
        raise ManifestError(
            f"{where}: 'expect' is {opcode.name}, which takes {argc} argument(s) "
            f"and so is {argc + 1} words, but the USER_FUNC that replaces it is "
            f"always 2.\n{_SAME_SIZE_ONLY}\n"
            f"  Pick an instruction that takes exactly one argument."
        )
    return evt.instruction_header(opcode, PATCH_ARGUMENT_COUNT)
