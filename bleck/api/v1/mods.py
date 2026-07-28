"""A whole mod, as JSON.

`placements.py` exposes one editing surface; this exposes the mod that holds
it — identity, dependencies, the `code` block and the placements together, so a
tool can read a mod, change anything in it, and write it back in one exchange.

⚠️ **Overlay files are not here, and that is deliberate.** A mod's overlay holds
extracted game assets — textures, archives, a compiled module — which are
binary, large, and already on disk. Putting them in a JSON document would make
every read of a mod's name drag megabytes with it. An editor lists them from the
filesystem; this describes what a mod *declares*.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bleck.api.v1.documents import Document
from bleck.api.v1.placements import PlacementEdit
from bleck.mods import manifest as mod_manifest
from bleck.mods.manifest import codespec
from bleck.mods.manifest import placements as manifest_placements


class Dependency(BaseModel):
    """Another mod that must apply before this one."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = Field(
        default="",
        description="Constraint such as '>=1.2.0'. Empty means any version.",
    )

    @classmethod
    def of(cls, requirement: mod_manifest.Requirement) -> Dependency:
        if requirement.version is None:
            return cls(name=requirement.name)
        return cls(
            name=requirement.name,
            version=f"{requirement.operator}{requirement.version}",
        )

    def to_manifest(self) -> mod_manifest.Requirement:
        return mod_manifest.Requirement.parse(self.name, self.version)


class Banner(BaseModel):
    """The `mod_loaded:` label drawn on screen."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    text: str = Field(
        default="", description="Overrides the label. Empty means `mod_loaded: <name>`."
    )
    sequences: list[str] = Field(
        default_factory=lambda: list(codespec.emit.DEFAULT_BANNER_SEQUENCES),
        description=(
            "Which game sequences draw it: logo, title, game, mapchange, gameover, load."
        ),
    )

    @classmethod
    def of(cls, spec: codespec.BannerSpec) -> Banner:
        return cls(enabled=spec.enabled, text=spec.text, sequences=list(spec.sequences))

    def to_manifest(self) -> codespec.BannerSpec:
        return codespec.BannerSpec(
            enabled=self.enabled, text=self.text, sequences=list(self.sequences)
        )


class Code(BaseModel):
    """A mod's compiled half: what it builds and what the module then does."""

    model_config = ConfigDict(extra="forbid")

    script: str = Field(default="", description="Script source, relative to the mod.")
    sources: list[str] = Field(
        default_factory=list, description="Native C files or directories."
    )
    target: str = Field(
        default="eu0",
        description=(
            "Game version whose symbol list resolves calls. ⚠️ Addresses differ "
            "per version; the wrong one links calls to unrelated code."
        ),
    )
    module_id: int = Field(
        default=2, ge=2, description="REL module id. 0 is the DOL, 1 the game's own."
    )
    maps: dict[str, str] = Field(
        default_factory=dict, description="Map name to the script run on arrival."
    )
    combos: dict[str, str] = Field(
        default_factory=dict,
        description="Combination name (from bleck.yml) to the script it starts.",
    )
    boot: str = Field(
        default="",
        description="A map to start the game at instead of the attract demo.",
    )
    banner: Banner = Field(default_factory=Banner)

    @classmethod
    def of(cls, spec: codespec.CodeSpec) -> Code:
        return cls(
            script=spec.script,
            sources=list(spec.sources),
            target=spec.target,
            module_id=spec.module_id,
            maps={hook.map_name: hook.script for hook in spec.maps},
            combos={binding.combo: binding.script for binding in spec.combos},
            boot=spec.boot_map,
            banner=Banner.of(spec.banner),
        )

    def to_manifest(self) -> codespec.CodeSpec:
        return codespec.CodeSpec(
            script=self.script,
            sources=list(self.sources),
            target=self.target,
            module_id=self.module_id,
            maps=[
                codespec.MapHook(map_name=name, script=script)
                for name, script in self.maps.items()
            ],
            combos=[
                codespec.ComboBinding(combo=name, script=script)
                for name, script in self.combos.items()
            ],
            boot_map=self.boot,
            banner=self.banner.to_manifest(),
        )


class ModDocument(Document):
    """Everything a mod declares. What an editor opens and saves."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    base: str = Field(
        default="", description="Which extracted build this targets, e.g. eu0."
    )
    created: str = ""
    dependencies: list[Dependency] = Field(default_factory=list)
    exclusive: list[str] = Field(
        default_factory=list, description="Paths this mod claims outright."
    )
    remove: list[str] = Field(default_factory=list, description="Base files to delete.")
    code: Code | None = Field(
        default=None, description="Absent for a mod that ships only assets."
    )
    setup: dict[str, list[PlacementEdit]] = Field(
        default_factory=dict, description="Declared enemy placement changes."
    )

    @model_validator(mode="after")
    def _name_is_present(self) -> ModDocument:
        if not self.name.strip():
            raise ValueError("a mod document needs a name")
        return self

    @classmethod
    def of(cls, manifest: mod_manifest.Manifest) -> ModDocument:
        return cls(
            name=manifest.name,
            version=str(manifest.version),
            description=manifest.description,
            author=manifest.author,
            base=manifest.base,
            created=manifest.created,
            dependencies=[Dependency.of(r) for r in manifest.dependencies],
            exclusive=list(manifest.exclusive),
            remove=list(manifest.remove),
            code=Code.of(manifest.code) if manifest.code else None,
            setup={
                placement.map_name: [PlacementEdit.of(edit) for edit in placement.edits]
                for placement in manifest.setup
            },
        )

    def to_manifest(self) -> mod_manifest.Manifest:
        return mod_manifest.Manifest(
            name=self.name,
            version=mod_manifest.Version.parse(self.version),
            description=self.description,
            author=self.author,
            base=self.base,
            created=self.created,
            dependencies=[d.to_manifest() for d in self.dependencies],
            exclusive=list(self.exclusive),
            remove=list(self.remove),
            code=self.code.to_manifest() if self.code else None,
            setup=[
                manifest_placements.MapPlacements(
                    map_name=name, edits=[edit.to_manifest() for edit in edits]
                )
                for name, edits in self.setup.items()
            ],
        )
