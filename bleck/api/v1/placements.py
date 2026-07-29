"""Enemy placement, as JSON.

Two directions, deliberately different shapes: `MapPlacements` is every slot a
map currently holds (what an editor reads); `SetupEdits` is a sparse list of
changes (what an editor sends back, and what a manifest stores).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bleck.api.v1.documents import Document
from bleck.formats import setup
from bleck.mods.manifest import placements as manifest_placements


class Position(BaseModel):
    """A placement in world space.

    ⚠️ `z` is not decoration: the same `x`/`y` at a different `z` is a different
    place in the flipped world. Editors should surface all three.
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
    copy_from: int | None = Field(
        default=None,
        ge=0,
        description=(
            "A slot whose whole entry is copied in before `template` and "
            "`position` are applied. An edit otherwise builds on what the slot "
            "holds, and an unused slot holds zeros -- where a shipped enemy "
            "carries three undocumented values that reach the live NPC (D123)."
        ),
    )
    clear: bool = Field(
        default=False,
        description=(
            "Empty the slot. ⚠️ The game stops reading entries at the first "
            "empty one, so clearing a slot with used slots after it orphans "
            "them -- `bleck` refuses that at build time (D79)."
        ),
    )

    @property
    def _sets_anything(self) -> bool:
        return (
            self.template is not None
            or self.position is not None
            or self.copy_from is not None
        )

    @model_validator(mode="after")
    def _clear_is_exclusive(self) -> PlacementEdit:
        if self.clear and self._sets_anything:
            raise ValueError(
                "an edit that clears a slot cannot also set a template, "
                "position or source; those describe an enemy that would not be there"
            )
        if not self.clear and not self._sets_anything:
            raise ValueError(
                "an edit must change something: set `template`, `position`, "
                "`copy_from`, or `clear`"
            )
        if self.copy_from == self.slot:
            raise ValueError(
                "`copy_from` names the slot being edited, so it copies nothing"
            )
        return self

    @classmethod
    def of(cls, edit: manifest_placements.PlacementEdit) -> PlacementEdit:
        return cls(
            slot=edit.slot,
            template=edit.template,
            position=Position.of(edit.position) if edit.position else None,
            clear=edit.clear,
            copy_from=edit.copy_from,
        )

    def to_manifest(self) -> manifest_placements.PlacementEdit:
        return manifest_placements.PlacementEdit(
            slot=self.slot,
            template=self.template,
            position=self.position.to_setup() if self.position else None,
            clear=self.clear,
            copy_from=self.copy_from,
        )


class ItemEdit(BaseModel):
    """One change to one placed item. What an editor sends back.

    ⚠️ **`index` is optional and absent means add.** Items are a counted list,
    not fixed slots, so there is no empty item to fill -- which is why this is
    not an `EnemyPlacement` with a different field name.
    """

    model_config = ConfigDict(extra="forbid")

    index: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Which of the map's existing items, or absent to add one. "
            "213 of the game's 227 maps place none at all, so adding is the "
            "common case."
        ),
    )
    position: Position | None = None
    type: int | None = Field(
        default=None,
        description=(
            "⚠️ Only 0 -- a coin -- exists. `setupItemTemplates` holds exactly "
            "one entry, so any other value indexes past the end of it."
        ),
    )
    flags: int | None = Field(
        default=None,
        ge=0,
        le=0xFFFF,
        description="0x10 and 0x1 are required to spawn; every shipped item is 0x11.",
    )
    clear: bool = Field(default=False, description="Remove the item. Needs an `index`.")

    @property
    def _sets_anything(self) -> bool:
        return (
            self.position is not None or self.type is not None or self.flags is not None
        )

    @model_validator(mode="after")
    def _says_something(self) -> ItemEdit:
        if self.type is not None and self.type != setup.Item.COIN:
            raise ValueError(
                f"type {self.type} is not a thing the game can place; "
                f"`setupItemTemplates` holds only id {setup.Item.COIN}, a coin"
            )
        if self.clear:
            if self.index is None:
                raise ValueError("`clear` needs an `index`; there is no empty item")
            if self._sets_anything:
                raise ValueError(
                    "an edit that removes an item cannot also set its position, "
                    "type or flags"
                )
            return self
        if self.index is None and self.position is None:
            raise ValueError(
                "an added item needs a position; give `index` to change one the "
                "map already places"
            )
        if not self._sets_anything:
            raise ValueError(
                "an edit must change something: set `position`, `type`, "
                "`flags`, or `clear`"
            )
        return self

    @classmethod
    def of(cls, edit: manifest_placements.ItemEdit) -> ItemEdit:
        return cls(
            index=edit.index,
            position=Position.of(edit.position) if edit.position else None,
            type=edit.type,
            flags=edit.flags,
            clear=edit.clear,
        )

    def to_manifest(self) -> manifest_placements.ItemEdit:
        return manifest_placements.ItemEdit(
            index=self.index,
            position=self.position.to_setup() if self.position else None,
            type=self.type,
            flags=self.flags,
            clear=self.clear,
        )


class SetupEdits(Document):
    """Declared changes to one or more maps, as a mod stores them."""

    setup: dict[str, list[PlacementEdit]] = Field(
        default_factory=dict,
        description="Map name to the slots changed in it.",
    )
    items: dict[str, list[ItemEdit]] = Field(
        default_factory=dict,
        description=(
            "Map name to the placed items changed in it. A separate key rather "
            "than a nesting inside `setup`, so a consumer that predates items "
            "reads the same `setup` it always did."
        ),
    )

    @classmethod
    def of(cls, declared: list[manifest_placements.MapPlacements]) -> SetupEdits:
        return cls(
            setup={
                placement.map_name: [PlacementEdit.of(edit) for edit in placement.edits]
                for placement in declared
            },
            items={
                placement.map_name: [ItemEdit.of(edit) for edit in placement.items]
                for placement in declared
                if placement.items
            },
        )

    def to_manifest(self) -> list[manifest_placements.MapPlacements]:
        names = dict.fromkeys([*self.setup, *self.items])
        return [
            manifest_placements.MapPlacements(
                map_name=name,
                edits=[edit.to_manifest() for edit in self.setup.get(name, [])],
                items=[edit.to_manifest() for edit in self.items.get(name, [])],
            )
            for name in names
        ]
