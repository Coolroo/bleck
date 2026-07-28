"""A mod's `code` block: what it compiles, and what the module then does.

Split from `manifest.py`, which was doing three unrelated jobs. This one is
about behaviour — scripts, native sources, map hooks, button combinations, the
boot map and the on-screen banner. `manifest.py` keeps identity and
dependencies; `placements.py` keeps enemy edits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bleck.mods.errors import ManifestError
from bleck.script import emit

#: Where a compiled code mod lands on the disc. The Gecko loader opens exactly
#: this path, so it is fixed rather than configurable.
#:
#: ⚠️ It is one path, not one *mod*: several mods are merged into this single
#: module at compile time (D78). The loader's limit is on RELs, not on authors.
REL_DISC_PATH = "files/mod/mod.rel"


@dataclass(frozen=True)
class BannerSpec:
    """The on-screen label naming the loaded mod.

    On by default, because the problem it solves is invisible until it bites:
    a modded disc looks exactly like a stock one, so someone holding several
    builds cannot tell which is running without playing far enough to spot a
    difference. Opt out with `"banner": false`.
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

    The manifest names a combination; it does not say which buttons. That split
    is the point — a mod says `start_map`, the project says once what
    `start_map` is, and changing the buttons does not touch any mod.
    """

    combo: str
    """Name of a combination in `bleck.yml`."""

    script: str
    """Name of a script in this mod's source, not a C identifier."""


@dataclass(frozen=True)
class MapHook:
    """A script attached to a map, so it runs when that map loads.

    This is how the game itself uses `evt`: a map's `MapData.initScript` is an
    ordinary pointer to bytecode, and doors, NPCs and items work the same way.
    Attaching to one is the difference between a mod that loops and a mod that
    reacts.
    """

    map_name: str
    """The map's internal name, e.g. `aa4_01`. Resolved by `mapDataPtr`."""

    script: str
    """Which script in the mod's source runs when the map loads."""


@dataclass(frozen=True)
class CodeSpec:
    """A mod's compiled-code half.

    Present only for mods that ship behaviour rather than only assets. A mod
    may supply a script, native C sources, or both -- they compile into one
    `mod.rel`.

    Scripts cover event logic and are far easier to write. Native sources exist
    for what a script cannot reach: calling ordinary game functions, and
    attaching scripts to maps, doors, items and NPCs by name.
    """

    script: str = ""
    """Path to the script source, relative to the mod directory."""

    sources: list[str] = field(default_factory=list)
    """Native C sources, relative to the mod directory. Files or directories."""

    target: str = "eu0"
    """Game version whose symbol list resolves the functions this script calls.

    Addresses differ per version, so this is not cosmetic: building against the
    wrong list produces a REL that jumps into unrelated code.
    """

    module_id: int = 2
    """REL module id. The game's own REL is 1, so mods start at 2."""

    maps: list[MapHook] = field(default_factory=list)
    """Scripts attached to maps, so they run on arrival rather than looping."""

    combos: list[ComboBinding] = field(default_factory=list)
    """Scripts bound to button combinations named in `bleck.yml`."""

    banner: BannerSpec = field(default_factory=BannerSpec)
    """The on-screen label naming this mod."""

    boot_map: str = ""
    """A map to start the game at, instead of the attract demo.

    The game boots into `aa4_01` and then `ls4_12` and nowhere else without a
    controller, so testing anything elsewhere used to mean a human holding a
    Wii remote. Naming a map here makes the disc go there on its own.
    """

    @property
    def has_boot_map(self) -> bool:
        return bool(self.boot_map)

    @property
    def has_combos(self) -> bool:
        return bool(self.combos)

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
        if self.boot_map:
            body["boot"] = self.boot_map
        # Written only when it says something a default would not, so the
        # common manifest stays as short as it was before banners existed.
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

    if not script and not sources and not boot:
        raise ManifestError(
            f"{source}: 'code' needs a 'script', 'sources', 'boot', or a "
            f"combination -- otherwise there is nothing to compile"
        )

    module_id = raw.get("module_id", 2)
    if not isinstance(module_id, int) or isinstance(module_id, bool):
        raise ManifestError(f"{source}: 'code.module_id' must be a whole number")
    # Module 0 is the DOL and 1 is the game's own REL; claiming either would
    # collide with something already linked when the mod loads.
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
        banner=_parse_banner(raw.get("banner"), source),
        boot_map=boot,
    )


#: A map's name as the disc spells it: `he1_01`, `aa4_01`, `mac_01`.
#:
#: Enforced rather than passed through because the name is interpolated into
#: generated script source. Restricting it to the shape every real map already
#: has means there is no escaping question to get wrong later.
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
    """Read `code.banner`, which may be absent, a boolean, or an object.

    A bare `false` is accepted because turning the label off is much the most
    likely reason to mention it at all, and `"banner": false` reads better than
    `"banner": {"enabled": false}`.
    """
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

    Written as an object rather than a list because a map can only have one
    init script: the shape should make a second entry for the same map
    impossible to express, rather than something to validate.
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

    An object for the same reason `code.maps` is one: a combination fires one
    script, so a second entry for the same combination should be impossible to
    write rather than something to detect.

    The names are not checked here. `bleck.yml` is what defines them, it is not
    a manifest concern, and the check belongs where the config is loaded so the
    error can list what *is* defined.
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
