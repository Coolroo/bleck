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


#: Selector kinds `code.patches[].script` accepts. `map:<name>` resolves through
#: `mapDataPtr` (D88); `item:<id>` walks `itemEventDataTable` (D91).
PATCH_KINDS = ("map", "item")

#: Kinds known to exist that have no mechanism yet, and why. Named separately so
#: asking for one gets the reason rather than "unsupported".
#: Rendered into every "that selector is not a thing" error.
_SUPPORTED_SELECTORS = "map:<name>, item:<id>"

DEFERRED_PATCH_KINDS = {
    "door": (
        "a door script cannot be looked up by name: `DoorDesc` carries the "
        "scripts, but the descriptor array is registered per map by "
        "`evt_door_set_door_descs`, and `evtDoorGetActiveDoorDesc` returns only "
        "the door currently in use. Reaching one needs interception, not a "
        "lookup (D91)."
    ),
}


@dataclass(frozen=True)
class _Selector:
    """A `code.patches[].script` value split into its two halves."""

    kind: str
    target: str


@dataclass(frozen=True)
class ScriptPatch:
    """One instruction of a vanilla `evt` script replaced by a call into the mod.

    Same-size replacement only: the replacement is a `USER_FUNC` carrying the
    **same argument count** as the instruction it overwrites, so any instruction
    of two words or more is patchable and no label moves — `jumptable[]` is
    cached per `EvtEntry` (D87, D91).
    """

    kind: str
    """Which family of script `target` names: `map` or `item`."""

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

    @property
    def selector(self) -> str:
        return f"{self.kind}:{self.target}"

    @property
    def argument_count(self) -> int:
        """Argument words the replaced instruction declares. The replacement
        carries the same count, so both are `argument_count + 1` words."""
        return self.expect_word >> 16

    @property
    def item_id(self) -> int:
        """The item id `target` names, or -1 when this is not an `item:` patch."""
        return int(self.target, 0) if self.kind == "item" else -1


#: What `code.hooks[].mode` accepts. `replace` takes the function over; the
#: other two keep it, by restoring its first instruction around the call rather
#: than relocating it into a trampoline (D96).
HOOK_MODES = ("replace", "before", "after")

#: What each mode does, quoted back when one is misspelled.
HOOK_MODE_MEANS = {
    "replace": "the mod's function instead of the original, which never runs",
    "before": "the mod's function first, then the original",
    "after": "the original first, then the mod's function",
}

#: Modes that keep the original running, and so need a wrapper and a guard word.
INTERCEPT_MODES = ("before", "after")


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

    mode: str = "replace"
    """How the mod's function relates to the original: replace, before, after."""

    @property
    def intercepts(self) -> bool:
        """Whether the original still runs. Needs a guard word to be derivable."""
        return self.mode in INTERCEPT_MODES

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
    hooks = _parse_hooks(raw.get("hooks"), source)

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
        hooks=hooks,
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

#: The replacement is `USER_FUNC` with the replaced instruction's own argument
#: count: `EVT_HELPER_CMD(n, 92)`, the pointer to `call`, then the original's
#: words 2..n unchanged. So `n` must leave room for the pointer.
MIN_ARGUMENT_COUNT = 1

#: Why the size is fixed, said once and quoted by the errors.
_SAME_SIZE_ONLY = (
    "  bleck replaces an instruction with a USER_FUNC declaring the same "
    "number of arguments, so the patch is exactly the same size: a shorter or "
    "longer instruction moves every label after it, and each running script "
    "caches its jump table when it starts (D87)."
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
    """Split `map:he1_01` or `item:0x41` into its kind and its target."""
    kind, _, target = raw.partition(":")
    if kind in DEFERRED_PATCH_KINDS:
        raise ManifestError(
            f"{where}: 'script' is {raw!r}, and bleck has no mechanism for "
            f"{kind!r} scripts.\n  {DEFERRED_PATCH_KINDS[kind]}\n"
            f"  Supported selectors: {_SUPPORTED_SELECTORS}."
        )
    if kind not in PATCH_KINDS or not target:
        raise ManifestError(
            f"{where}: 'script' is {raw!r}, which names no script bleck can "
            f"reach.\n  Supported selectors: {_SUPPORTED_SELECTORS}.\n"
            f"  'map:he1_01' patches that map's init script; 'item:0x41' "
            f"patches that item's use script."
        )
    if kind == "item":
        return _Selector(kind=kind, target=_parse_item_id(target, where))
    if not _MAP_NAME_RE.match(target):
        raise ManifestError(
            f"{where}: {target!r} is not a map name. They look like 'he1_01' -- "
            f"lowercase letters, digits and underscores.\n"
            f"  `bleck maps` lists all 383 of them."
        )
    return _Selector(kind=kind, target=target)


def _parse_item_id(raw: str, where: str) -> str:
    """Check an `item:` target is a whole number, and hand it back as written.

    ⚠️ Membership is not checked here: `itemEventDataTable` lives in the game's
    data, so "is there such an item" is a run-time question. The generated code
    answers it with a NOT_FOUND status rather than patching a fallback.
    """
    try:
        value = int(raw, 0)
    except ValueError:
        raise ManifestError(
            f"{where}: {raw!r} is not an item id. Write a number, decimal or "
            f"hexadecimal -- 'item:65' or 'item:0x41'.\n"
            f"  `mods/item-probe` reports the ids itemEventDataTable holds."
        ) from None
    if value < 0:
        raise ManifestError(f"{where}: item id {raw!r} cannot be negative")
    return raw


def _parse_expect(raw: str, where: str) -> int:
    """Resolve `expect` -- a header word, or an opcode name and argument count.

    `DEBUG_PUT_MSG` takes its count from the arity table. A variadic opcode has
    no entry there, so `USER_FUNC 4` says the count outright.
    """
    text = raw.strip()
    if text.lower().startswith("0x"):
        return _parse_expect_word(text, raw, where)

    parts = text.split()
    opcode = evt.opcode_named(parts[0]) if parts else None
    if opcode is None or len(parts) > 2:
        raise ManifestError(_unknown_opcode(text, raw, where))
    declared = _parse_declared_count(parts[1], raw, where) if len(parts) == 2 else None

    argc = evt.argument_count(opcode)
    if argc is None:
        if declared is None:
            raise ManifestError(
                f"{where}: 'expect' is {opcode.name}, which is variadic -- it "
                f"declares its own argument count, so bleck cannot infer the "
                f"instruction's size.\n"
                f'  Say how many: "expect": "{opcode.name} 4".\n'
                f"  Counting: USER_FUNC's first argument is the function "
                f"pointer, so `USER_FUNC f, a, b, c` declares 4."
            )
        argc = declared
    elif declared is not None and declared != argc:
        raise ManifestError(
            f"{where}: 'expect' is {raw!r}, but {opcode.name} always takes "
            f"{argc} argument(s), not {declared}.\n"
            f"  Drop the count, or give the header word directly."
        )
    _check_room_for_pointer(argc, raw, where)
    return evt.instruction_header(opcode, argc)


def _parse_expect_word(text: str, raw: str, where: str) -> int:
    try:
        word = int(text, 16)
    except ValueError:
        raise ManifestError(
            f"{where}: 'expect' is {raw!r}, which is neither an opcode name "
            f"nor a hexadecimal header word like '0x00010072'"
        ) from None
    if not 0 <= word <= 0xFFFFFFFF:
        raise ManifestError(f"{where}: 'expect' {raw!r} is not a 32-bit word")
    _check_room_for_pointer(word >> 16, raw, where)
    return word


def _parse_declared_count(text: str, raw: str, where: str) -> int:
    try:
        return int(text, 0)
    except ValueError:
        raise ManifestError(
            f"{where}: 'expect' is {raw!r}; the part after the opcode name is "
            f'its argument count, e.g. "USER_FUNC 4"'
        ) from None


def _unknown_opcode(name: str, raw: str, where: str) -> str:
    names = [op.name for op in evt.Opcode]
    close = difflib.get_close_matches(name.upper(), names, n=1, cutoff=0.6)
    hint = (
        f"\n  Did you mean {close[0]!r}?"
        if close
        else "\n  Names come from spm/evtmgr_cmd.h, such as 'DEBUG_PUT_MSG'."
    )
    return (
        f"{where}: 'expect' is {raw!r}, which names no evt opcode.{hint}\n"
        f'  Write an opcode name, optionally with its argument count ("USER_FUNC '
        f'4"), or the header word directly ("0x00010072").'
    )


def _parse_hooks(raw: object, source: str) -> list[FunctionHook]:
    """Read `code.hooks`, a list of functions replaced by the mod's own."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError(
            f"{source}: 'code.hooks' must be a list of hook objects, e.g. "
            f'[{{"function": "npcDispMain", "call": "count_npcs", '
            f'"mode": "replace"}}]'
        )
    return [
        _parse_hook(entry, f"{source}: 'code.hooks[{i}]'") for i, entry in enumerate(raw)
    ]


def _parse_hook(raw: object, where: str) -> FunctionHook:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    unknown = sorted(set(raw) - {"function", "call", "mode"})
    if unknown:
        raise ManifestError(
            f"{where} has unknown field(s): {', '.join(unknown)}\n"
            f"  A hook takes 'function', 'call' and 'mode'."
        )
    for name in ("function", "call"):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ManifestError(f"{where} needs a non-empty {name!r} string")
    mode = raw.get("mode", "replace")
    if not isinstance(mode, str):
        raise ManifestError(f"{where}: 'mode' must be a string")
    return build_hook(str(raw["function"]), str(raw["call"]), mode, where)


def build_hook(function: str, call: str, mode: str, where: str) -> FunctionHook:
    """Validate one hook's three fields. Shared with the JSON API.

    The symbol is *not* resolved here: that needs the target's list, which the
    build loads. This checks only what is decidable from the manifest alone.
    """
    _check_hook_mode(mode, where)
    hook = FunctionHook(function=function.strip(), call=call, mode=mode)
    if not _C_NAME_RE.match(call):
        raise ManifestError(
            f"{where}: 'call' is {call!r}, which is not a C function name.\n"
            f"  It names a function in this mod's own sources, e.g. 'count_npcs'."
        )
    if hook.is_address:
        _check_hook_address(hook.function, where)
    elif not _C_NAME_RE.match(hook.function):
        raise ManifestError(
            f"{where}: 'function' is {function!r}, which is neither a symbol "
            f"name nor an address.\n"
            f"  Write the game function's name -- 'npcDispMain' -- so bleck "
            f"resolves it against the target's symbol list, or an address like "
            f"'0x801adef0' when it has no name.\n"
            f"  `bleck symbols search <text>` lists what the list holds."
        )
    return hook


def _check_hook_mode(mode: str, where: str) -> None:
    if mode in HOOK_MODES:
        return
    hint = "".join(f"\n    {name}: runs {why}" for name, why in HOOK_MODE_MEANS.items())
    raise ManifestError(f"{where}: 'mode' is {mode!r}, which is not a hook mode.{hint}")


def _check_hook_address(text: str, where: str) -> None:
    try:
        value = int(text, 16)
    except ValueError:
        raise ManifestError(
            f"{where}: 'function' is {text!r}, which starts like an address but "
            f"is not hexadecimal. Write it as '0x801adef0'."
        ) from None
    if not 0x80000000 <= value <= 0x8FFFFFFF:
        raise ManifestError(
            f"{where}: 'function' is {text!r}, which is not a game address.\n"
            f"  The Wii's cached MEM1 window is 0x80000000..0x817FFFFF; code "
            f"lives there."
        )
    if value % 4:
        raise ManifestError(
            f"{where}: 'function' is {text!r}, which is not 4-byte aligned, so "
            f"no instruction begins there."
        )


def _check_room_for_pointer(argc: int, raw: str, where: str) -> None:
    """Refuse a one-word instruction: the pointer to `call` has nowhere to go."""
    if argc >= MIN_ARGUMENT_COUNT:
        return
    raise ManifestError(
        f"{where}: 'expect' is {raw!r}, which declares no arguments and so is "
        f"one word. The replacement is a USER_FUNC header plus the pointer to "
        f"'call', which needs two words at least -- there is no room for the "
        f"pointer.\n{_SAME_SIZE_ONLY}\n"
        f"  Pick an instruction of two words or more."
    )
