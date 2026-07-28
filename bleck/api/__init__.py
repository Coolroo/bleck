"""The JSON contract other applications integrate against.

`bleck`'s CLI prints for people; this is for programs. A GUI cannot shell out to
`bleck mod build` on every keystroke, and an external tool should not have to
parse human-readable output to find out what a map places.

Every model here is a pydantic model, so the same declaration gives validation,
JSON in both directions, and a published schema (`bleck setup schema`).

⚠️ These are a **wire format**, deliberately separate from the manifest types in
`bleck/mods/manifest/`. The manifest is what a mod *declares* and is tuned for
being hand-edited and reviewed; this is what a program exchanges, and is tuned
for being unambiguous. Keeping them apart means the file format can change
without breaking integrations, and vice versa. `to_edit`/`from_placement`
convert, and are round-trip tested.
"""

from bleck.api.placements import (
    EnemyPlacement,
    MapPlacements,
    PlacementEdit,
    Position,
    SetupEdits,
)

__all__ = [
    "EnemyPlacement",
    "MapPlacements",
    "PlacementEdit",
    "Position",
    "SetupEdits",
]
