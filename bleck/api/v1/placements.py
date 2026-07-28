"""Enemy placement, as JSON.

This is the first editing surface `bleck` exposes as an API rather than a
command, because it is the one format that is *fully decoded* — all 227 setup
files on the disc parse with no exceptions (D42) — so a tool built on it can be
real rather than speculative.

Two directions, deliberately different shapes:

- `MapPlacements` is what a map **currently holds**: every slot, with the enemy
  name resolved from the catalog. What an editor reads to populate a view.
- `SetupEdits` is what someone **wants changed**: a sparse list of slots. What
  an editor sends back, and what a manifest stores.

A read is not an edit turned around. Sending back a whole map as edits would
rewrite a hundred slots to change one, and lose the distinction between "left
alone" and "explicitly set to what it already was".
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bleck.api.v1.documents import Document
from bleck.formats import setup
from bleck.mods.manifest import placements as manifest_placements


class Position(BaseModel):
    """A placement in world space.

    ⚠️ Super Paper Mario is 2D with a 3D flip axis, so `z` is not decoration:
    the same `x`/`y` at a different `z` is a different place in the flipped
    world. Editors should surface all three.
    """

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    z: float

    @classmethod
    def of(cls, position: setup.Position) -> Position:
        return cls(x=position.x, y=position.y, z=position.z)

    def to_setup(self) -> setup.Position:
        return setup.Position(self.x, self.y, self.z)


class EnemyPlacement(BaseModel):
    """One slot as it currently stands."""

    model_config = ConfigDict(extra="forbid")

    slot: int = Field(ge=0, description="Index into the map's 100 fixed slots.")
    empty: bool = Field(description="Whether anything is placed here at all.")
    template: int | None = Field(
        default=None,
        description=(
            "Index into the game's `npcEnemyTemplates`. NOT an `NPC_*` "
            "constant -- those are tribe ids, and there are 535 tribes to 435 "
            "templates."
        ),
    )
    name: str = Field(
        default="",
        description="Human name from the committed catalog, empty if unknown.",
    )
    position: Position | None = None

    @classmethod
    def of(cls, slot: int, enemy: setup.Enemy, name: str = "") -> EnemyPlacement:
        if enemy.is_empty:
            return cls(slot=slot, empty=True)
        return cls(
            slot=slot,
            empty=False,
            template=enemy.template,
            name=name,
            position=Position.of(enemy.position),
        )


class MapPlacements(Document):
    """Everything one map places. What an editor reads."""

    map: str
    version: int = Field(description="Setup file version; the entry stride follows it.")
    documented: bool = Field(
        description=(
            "Whether this version's entry fields are understood. False means "
            "only the container was read, so `template` and `position` are "
            "absent rather than wrong."
        )
    )
    enemies: list[EnemyPlacement]

    @property
    def used(self) -> list[EnemyPlacement]:
        return [enemy for enemy in self.enemies if not enemy.empty]


class PlacementEdit(BaseModel):
    """One change to one slot. What an editor sends back."""

    model_config = ConfigDict(extra="forbid")

    slot: int = Field(ge=0)
    template: int | None = None
    position: Position | None = None
    clear: bool = Field(
        default=False,
        description=(
            "Empty the slot. ⚠️ The game stops reading entries at the first "
            "empty one, so clearing a slot with used slots after it orphans "
            "them -- `bleck` refuses that at build time (D79)."
        ),
    )

    @model_validator(mode="after")
    def _clear_is_exclusive(self) -> PlacementEdit:
        if self.clear and (self.template is not None or self.position is not None):
            raise ValueError(
                "an edit that clears a slot cannot also set a template or "
                "position; those describe an enemy that would not be there"
            )
        if not self.clear and self.template is None and self.position is None:
            raise ValueError(
                "an edit must change something: set `template`, `position`, or `clear`"
            )
        return self

    @classmethod
    def of(cls, edit: manifest_placements.PlacementEdit) -> PlacementEdit:
        return cls(
            slot=edit.slot,
            template=edit.template,
            position=Position.of(edit.position) if edit.position else None,
            clear=edit.clear,
        )

    def to_manifest(self) -> manifest_placements.PlacementEdit:
        return manifest_placements.PlacementEdit(
            slot=self.slot,
            template=self.template,
            position=self.position.to_setup() if self.position else None,
            clear=self.clear,
        )


class SetupEdits(Document):
    """Declared changes to one or more maps, as a mod stores them."""

    setup: dict[str, list[PlacementEdit]] = Field(
        default_factory=dict,
        description="Map name to the slots changed in it.",
    )

    @classmethod
    def of(cls, declared: list[manifest_placements.MapPlacements]) -> SetupEdits:
        return cls(
            setup={
                placement.map_name: [PlacementEdit.of(edit) for edit in placement.edits]
                for placement in declared
            }
        )

    def to_manifest(self) -> list[manifest_placements.MapPlacements]:
        return [
            manifest_placements.MapPlacements(
                map_name=name, edits=[edit.to_manifest() for edit in edits]
            )
            for name, edits in self.setup.items()
        ]
