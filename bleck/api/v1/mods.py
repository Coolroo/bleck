"""A whole mod, as JSON: identity, dependencies, `code` and placements together.

⚠️ Overlay files are deliberately absent — they are large binary assets already
on disk. This describes what a mod *declares*; an editor lists overlay files
from the filesystem.
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
    # `list[str]`, not `list[Sequence]`, on purpose: `Sequence` is an `IntEnum`,
    # so a pydantic field typed with it would serialize to NUMBERS and silently
    # change what `code.banner.sequences` looks like on the wire.
    sequences: list[str] = Field(
        default_factory=lambda: list(codespec.emit.DEFAULT_BANNER_SEQUENCES),
        description=(
            f"Which game sequences draw it: {', '.join(codespec.emit.SEQUENCE_NAMES)}."
        ),
    )

    @classmethod
    def of(cls, spec: codespec.BannerSpec) -> Banner:
        return cls(enabled=spec.enabled, text=spec.text, sequences=list(spec.sequences))

    def to_manifest(self) -> codespec.BannerSpec:
        return codespec.BannerSpec(
            enabled=self.enabled, text=self.text, sequences=list(self.sequences)
        )


class Patch(BaseModel):
    """One instruction of a vanilla evt script replaced by a call into the mod."""

    model_config = ConfigDict(extra="forbid")

    script: str = Field(
        description=(
            "Which script: `map:<name>` for a map's init script, `item:<id>` "
            "for an item's use script. ⚠️ Item ids share scripts -- 22 distinct "
            "scripts across 33 table entries -- so patching one id can change "
            "several. `bleck_patch_shared[]` reports how many at run time."
        )
    )
    at: int = Field(ge=0, description="Word offset where the instruction begins.")
    expect: str = Field(
        description=(
            "The opcode expected there: a name ('DEBUG_PUT_MSG'), a name with "
            "its argument count for a variadic opcode ('USER_FUNC 4'), or a raw "
            "header word ('0x00010072'). ⚠️ The guard: nothing is written on a "
            "mismatch. The replacement is a USER_FUNC declaring the same "
            "argument count, so it is the same size; a one-word instruction is "
            "refused since the function pointer would not fit."
        )
    )
    call: str = Field(
        description="A function in the mod's sources: `s32 f(EvtEntry *, bool)`."
    )

    @classmethod
    def of(cls, patch: codespec.ScriptPatch) -> Patch:
        return cls(
            script=patch.selector, at=patch.at, expect=patch.expect, call=patch.call
        )

    def to_manifest(self) -> codespec.ScriptPatch:
        return codespec.build_patch(
            self.script, self.at, self.expect, self.call, "code.patches[]"
        )


class Hook(BaseModel):
    """A game function branch-replaced by one of the mod's own."""

    model_config = ConfigDict(extra="forbid")

    function: str = Field(
        description=(
            "The game function to replace: a symbol name ('npcDispMain'), "
            "resolved against the target's symbol list at build time, or a raw "
            "address ('0x801adef0'). An unknown name fails the build."
        )
    )
    call: str = Field(
        description=(
            "A function in the mod's sources. It must take the same arguments "
            "as the function it hooks, in every mode; nothing can check this, "
            "because a symbol list carries addresses and not signatures."
        )
    )
    mode: codespec.HookMode = Field(
        default=codespec.HookMode.REPLACE,
        description=(
            "Which side of the original the mod's function runs on. 'replace' "
            "means the original NEVER RUNS and the mod's function does the "
            "whole job. 'before' runs the mod's function then the original; "
            "'after' runs the original then the mod's function. Under both, "
            "the caller receives the ORIGINAL's return value."
        ),
    )

    @classmethod
    def of(cls, hook: codespec.FunctionHook) -> Hook:
        return cls(function=hook.function, call=hook.call, mode=hook.mode)

    def to_manifest(self) -> codespec.FunctionHook:
        return codespec.build_hook(self.function, self.call, self.mode, "code.hooks[]")


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
    patches: list[Patch] = Field(
        default_factory=list,
        description="In-place replacements in the game's own evt scripts.",
    )
    hooks: list[Hook] = Field(
        default_factory=list,
        description="Game functions replaced by functions in this mod.",
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
            patches=[Patch.of(patch) for patch in spec.patches],
            hooks=[Hook.of(hook) for hook in spec.hooks],
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
            patches=[patch.to_manifest() for patch in self.patches],
            hooks=[hook.to_manifest() for hook in self.hooks],
            boot_map=self.boot,
            banner=self.banner.to_manifest(),
        )


class Table(BaseModel):
    """A CSV table of placements, as a program exchanges it.

    ⚠️ Always the object form, and always inside a list, where `mod.json` also
    accepts a bare path string and a lone table. The manifest is hand-edited and
    a shorthand earns its keep there; a wire format with two shapes for one
    thing is a bug generator.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Relative to the mod root, posix-style.")
    map: str = Field(
        default="",
        description=(
            "The map every row belongs to. Empty means each row names its own "
            "in a `map` column -- and a bound table may not have that column."
        ),
    )

    @classmethod
    def of(cls, ref: manifest_placements.TableRef) -> Table:
        return cls(path=ref.path, map=ref.map_name)

    def to_manifest(
        self, kind: manifest_placements.TableKind
    ) -> manifest_placements.TableRef:
        return manifest_placements.TableRef(kind=kind, path=self.path, map_name=self.map)


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
    tables: dict[manifest_placements.TableKind, list[Table]] = Field(
        default_factory=dict,
        description=(
            "CSV tables, keyed by what their rows describe. The declarations "
            "only -- the rows live in the files, which an editor reads from "
            "disk like any other mod file. Always a list, even for one table: "
            "a consumer that has to branch on the shape will get it wrong."
        ),
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
            tables={
                kind: [Table.of(ref) for ref in manifest.tables_of(kind)]
                for kind in manifest_placements.TableKind
                if manifest.tables_of(kind)
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
            tables=[
                table.to_manifest(kind)
                for kind, found in self.tables.items()
                for table in found
            ],
        )
