"""What every character-model reader shares: the error, and the name field.

Split out of `model` so that the container reader, the geometry reader and the
animation reader can each depend on this and not on each other. `model` imports
`modelmesh` and `modelanim` to re-export them; if either imported `model` back
for the error type the package would not load at all.
"""

from __future__ import annotations

from bleck.common.errors import BleckError

#: Names are written into a fixed-width field and padded with nulls -- the
#: model's own name and build stamp in the opening record, and a shape's name
#: in its own record, all use the same width.
FIELD = 32


class ModelError(BleckError):
    """A character model could not be read."""


def text(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("ascii", "replace").strip()
