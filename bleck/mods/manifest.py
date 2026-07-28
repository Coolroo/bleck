"""Mod manifests: `mod.json`.

A manifest declares identity, which base build it targets, what it depends on,
and which paths it claims exclusively.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bleck.common.errors import BleckError
from bleck.formats import setup
from bleck.script import emit

MANIFEST_NAME = "mod.json"
# Named `overlay`, not `files`: the disc's own data partition is `files/`,
# so `overlay/files/...` reads correctly where `files/files/...` would not.
OVERLAY_DIR = "overlay"
SCHEMA_VERSION = 1

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_REQUIREMENT_RE = re.compile(r"^(>=|<=|==)?\s*(\d+\.\d+\.\d+)$")


class ManifestError(BleckError):
    """A manifest is missing, malformed, or self-inconsistent."""


@dataclass(frozen=True, order=True)
class Version:
    """A semantic version. Ordered, so requirements compare directly."""

    major: int = 0
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, text: str) -> Version:
        match = _VERSION_RE.match(text.strip())
        if not match:
            raise ManifestError(f"bad version {text!r}, expected MAJOR.MINOR.PATCH")
        return cls(int(match[1]), int(match[2]), int(match[3]))


@dataclass(frozen=True)
class Requirement:
    """A dependency on another mod, optionally version-constrained."""

    name: str
    operator: str = ""
    version: Version | None = None

    def __str__(self) -> str:
        if self.version is None:
            return self.name
        return f"{self.name} {self.operator}{self.version}"

    def is_satisfied_by(self, candidate: Version) -> bool:
        if self.version is None:
            return True
        if self.operator == ">=":
            return candidate >= self.version
        if self.operator == "<=":
            return candidate <= self.version
        return candidate == self.version

    @classmethod
    def parse(cls, name: str, spec: str) -> Requirement:
        if not spec:
            return cls(name)
        match = _REQUIREMENT_RE.match(spec.strip())
        if not match:
            raise ManifestError(
                f"bad version requirement {spec!r} for {name!r}; "
                "expected e.g. '>=1.2.0', '==1.0.0'"
            )
        return cls(name, match[1] or "==", Version.parse(match[2]))


#: Where a compiled code mod lands on the disc. The Gecko loader opens exactly
#: this path, so it is fixed rather than configurable — and it is why two code
#: mods cannot currently coexist (see `conflicts.py`).
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
class PlacementEdit:
    """One change to one enemy slot, as declared rather than as bytes.

    Declared so the change stays reviewable, undoable and re-appliable — see
    `docs/vision.md`. `bleck` derives the file at build time.
    """

    slot: int
    template: int | None = None
    position: setup.Position | None = None
    clear: bool = False
    """Empty the slot. Mutually exclusive with the others."""

    def describe(self) -> str:
        if self.clear:
            return f"slot {self.slot}: cleared"
        parts = []
        if self.template is not None:
            parts.append(f"template {self.template}")
        if self.position is not None:
            parts.append(f"at {self.position.describe()}")
        return f"slot {self.slot}: {', '.join(parts)}"

    def to_json(self) -> dict[str, object]:  # pylint: disable=container-return
        body: dict[str, object] = {"slot": self.slot}
        if self.clear:
            body["clear"] = True
        if self.template is not None:
            body["template"] = self.template
        if self.position is not None:
            body["position"] = list(self.position.as_tuple())
        return body


@dataclass(frozen=True)
class MapPlacements:
    """Every declared change to one map's placements."""

    map_name: str
    edits: list[PlacementEdit]


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

    banner: BannerSpec = field(default_factory=BannerSpec)
    """The on-screen label naming this mod."""

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
        # Written only when it says something a default would not, so the
        # common manifest stays as short as it was before banners existed.
        if not self.banner.is_default:
            body["banner"] = self.banner.to_json()
        return body


@dataclass(frozen=True)
class Manifest:
    """A mod's declared identity and relationships."""

    name: str
    version: Version = field(default_factory=Version)
    description: str = ""
    author: str = ""
    base: str = ""
    created: str = ""
    dependencies: list[Requirement] = field(default_factory=list)
    exclusive: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    code: CodeSpec | None = None
    setup: list[MapPlacements] = field(default_factory=list)
    """Declared changes to enemy placement, applied at build time."""

    @property
    def has_placements(self) -> bool:
        return bool(self.setup)

    @property
    def has_code(self) -> bool:
        return self.code is not None

    def to_json(self) -> str:
        body = {
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "version": str(self.version),
            "description": self.description,
            "author": self.author,
            "base": self.base,
            "created": self.created,
            "dependencies": [
                {"name": r.name, "version": f"{r.operator}{r.version}"}
                if r.version
                else {"name": r.name}
                for r in self.dependencies
            ],
            "exclusive": self.exclusive,
            "remove": self.remove,
        }
        if self.setup:
            body["setup"] = {
                placement.map_name: [edit.to_json() for edit in placement.edits]
                for placement in self.setup
            }
        # Omitted rather than written as null: most mods ship no code, and an
        # always-present empty block invites people to fill it in.
        if self.code is not None:
            body["code"] = self.code.to_json()
        return json.dumps(body, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str, source: str = MANIFEST_NAME) -> Manifest:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{source}: invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ManifestError(f"{source}: expected a JSON object")

        schema = raw.get("schema", SCHEMA_VERSION)
        if schema != SCHEMA_VERSION:
            raise ManifestError(
                f"{source}: unsupported schema {schema!r} "
                f"(this build understands {SCHEMA_VERSION})"
            )

        name = raw.get("name", "")
        if not name:
            raise ManifestError(f"{source}: 'name' is required")

        return cls(
            name=name,
            version=Version.parse(raw.get("version", "0.0.0")),
            description=raw.get("description", ""),
            author=raw.get("author", ""),
            base=raw.get("base", ""),
            created=raw.get("created", ""),
            dependencies=_parse_dependencies(raw.get("dependencies", []), source),
            exclusive=list(raw.get("exclusive", [])),
            remove=list(raw.get("remove", [])),
            code=_parse_code(raw.get("code"), source),
            setup=_parse_setup(raw.get("setup"), source),
        )


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

    if not script and not sources:
        raise ManifestError(
            f"{source}: 'code' needs a 'script', 'sources', or both -- "
            f"otherwise there is nothing to compile"
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
        banner=_parse_banner(raw.get("banner"), source),
    )


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


def _parse_setup(raw: object, source: str) -> list[MapPlacements]:
    """Read the `setup` block: map name -> a list of slot edits."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'setup' must be an object of map name -> list of edits"
        )

    placements = []
    for map_name, edits in raw.items():
        if not isinstance(edits, list):
            raise ManifestError(f"{source}: 'setup.{map_name}' must be a list of edits")
        placements.append(
            MapPlacements(
                map_name=map_name,
                edits=[_parse_edit(e, f"{source}: setup.{map_name}") for e in edits],
            )
        )
    return placements


def _parse_edit(raw: object, where: str) -> PlacementEdit:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: each edit must be an object")

    slot = raw.get("slot")
    if not isinstance(slot, int) or isinstance(slot, bool):
        raise ManifestError(f"{where}: every edit needs a numeric 'slot'")
    if not 0 <= slot < setup.ENEMY_SLOTS:
        raise ManifestError(
            f"{where}: slot {slot} is out of range "
            f"(a setup file has exactly {setup.ENEMY_SLOTS} slots, 0-"
            f"{setup.ENEMY_SLOTS - 1})"
        )

    clear = raw.get("clear", False)
    if not isinstance(clear, bool):
        raise ManifestError(f"{where}: 'clear' must be true or false")

    template = raw.get("template")
    if template is not None and (
        not isinstance(template, int) or isinstance(template, bool)
    ):
        raise ManifestError(f"{where}: 'template' must be a whole number")

    position = _parse_position(raw.get("position"), where)

    if clear and (template is not None or position is not None):
        raise ManifestError(
            f"{where}: slot {slot} both clears and sets something. "
            f"Clearing empties the slot, so the rest would be discarded"
        )
    if not clear and template is None and position is None:
        raise ManifestError(
            f"{where}: slot {slot} changes nothing. "
            f"Give 'template', 'position', or 'clear'"
        )
    return PlacementEdit(slot=slot, template=template, position=position, clear=clear)


def _parse_position(raw: object, where: str) -> setup.Position | None:
    if raw is None:
        return None
    numbers = isinstance(raw, list) and len(raw) == 3
    if not numbers or not all(isinstance(v, (int, float)) for v in raw):
        raise ManifestError(
            f"{where}: 'position' must be three numbers, e.g. [100, 0, -50]"
        )
    return setup.Position(float(raw[0]), float(raw[1]), float(raw[2]))


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


def _parse_dependencies(raw: object, source: str) -> list[Requirement]:
    if not isinstance(raw, list):
        raise ManifestError(f"{source}: 'dependencies' must be a list")
    out: list[Requirement] = []
    for item in raw:
        if isinstance(item, str):
            out.append(Requirement(item))
            continue
        if not isinstance(item, dict) or "name" not in item:
            raise ManifestError(
                f"{source}: each dependency needs a 'name' (got {item!r})"
            )
        out.append(Requirement.parse(item["name"], item.get("version", "")))
    return out


def read(directory: Path) -> Manifest:
    path = directory / MANIFEST_NAME
    if not path.exists():
        raise ManifestError(f"no {MANIFEST_NAME} in {directory}")
    return Manifest.from_json(path.read_text(), source=str(path))


def write(directory: Path, manifest: Manifest) -> None:
    (directory / MANIFEST_NAME).write_text(manifest.to_json())
