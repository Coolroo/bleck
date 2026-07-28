"""The JSON contract other applications integrate against.

Versioned twice: `api_version` rides inside each top-level document, and
`bleck.api.v1` versions the code so a v2 can sit beside v1. This module
re-exports the current version; pin to `bleck.api.v1` to break loudly instead.

⚠️ A wire format, deliberately separate from the manifest types in
`bleck/mods/manifest/`, so the file format can change without breaking
integrations. The conversions are round-trip tested.
"""

from bleck.api import v1
from bleck.api.v1 import (
    API_VERSION,
    Banner,
    Code,
    Dependency,
    Document,
    EnemyPlacement,
    Hook,
    MapPlacements,
    ModDocument,
    Patch,
    PlacementEdit,
    Position,
    SetupEdits,
)

#: The version this module's re-exports point at.
CURRENT = v1

__all__ = [
    "API_VERSION",
    "CURRENT",
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
    "v1",
]
