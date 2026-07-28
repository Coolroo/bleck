"""The JSON contract other applications integrate against.

`bleck`'s CLI prints for people; this is for programs. A GUI cannot shell out to
`bleck mod build` on every keystroke, and an external tool should not have to
parse human-readable output to find out what a map places.

Every model is a pydantic model, so one declaration gives validation, JSON in
both directions, and a published schema (`bleck setup schema`).

⚠️ **Versioned twice.** `api_version` rides inside each top-level document, so
one that has been written to disk or pasted into a bug report still says what it
is. `bleck.api.v1` versions the code, so a v2 can be added beside v1 rather than
replacing it.

This module re-exports the **current** version. Pin to `bleck.api.v1` explicitly
if you would rather break loudly at import than adapt when v2 lands.

⚠️ These are a wire format, deliberately separate from the manifest types in
`bleck/mods/manifest/`. The manifest is what a mod *declares* and is tuned for
being hand-edited and reviewed; this is what a program exchanges, and is tuned
for being unambiguous. Keeping them apart means the file format can change
without breaking integrations. The conversions are round-trip tested.
"""

from bleck.api import v1
from bleck.api.v1 import (
    API_VERSION,
    Banner,
    Code,
    Dependency,
    Document,
    EnemyPlacement,
    MapPlacements,
    ModDocument,
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
    "MapPlacements",
    "ModDocument",
    "PlacementEdit",
    "Position",
    "SetupEdits",
    "v1",
]
