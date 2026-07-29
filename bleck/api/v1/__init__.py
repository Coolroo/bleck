"""Version 1 of the JSON contract."""

from bleck.api.v1.documents import API_VERSION, Document
from bleck.api.v1.mods import (
    Banner,
    Code,
    Dependency,
    Hook,
    ModDocument,
    Patch,
    Table,
)
from bleck.api.v1.placements import (
    EnemyPlacement,
    MapPlacements,
    PlacementEdit,
    Position,
    SetupEdits,
)

__all__ = [
    "API_VERSION",
    "Banner",
    "Code",
    "Dependency",
    "Document",
    "EnemyPlacement",
    "Hook",
    "MapPlacements",
    "ModDocument",
    "Patch",
    "PlacementEdit",
    "Position",
    "SetupEdits",
    "Table",
]
