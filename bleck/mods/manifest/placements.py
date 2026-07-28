"""Declared changes to a map's enemy placement.

⚠️ Edits are *declared*, never shipped as bytes; `bleck` derives the file at
build time so the change stays reviewable and undoable (`docs/vision.md`).
"""

from __future__ import annotations

from dataclasses import dataclass

from bleck.formats import setup
from bleck.mods.errors import ManifestError


@dataclass(frozen=True)
class PlacementEdit:
    """One change to one enemy slot, as declared rather than as bytes."""

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
