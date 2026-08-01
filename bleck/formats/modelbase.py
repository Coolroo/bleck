"""What every character-model reader shares: the error, and the name field.

Split out of `model` so that the container reader, the geometry reader and the
animation reader can each depend on this and not on each other. `model` imports
`modelmesh` and `modelanim` to re-export them; if either imported `model` back
for the error type the package would not load at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bleck.common.errors import BleckError

#: Names are written into a fixed-width field and padded with nulls -- the
#: model's own name and build stamp in the opening record, and a shape's name
#: in its own record, all use the same width.
FIELD = 32


class ModelError(BleckError):
    """A character model could not be read."""


def text(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("ascii", "replace").strip()


#: A shape record lists eight data sections here, as file-absolute offsets. The
#: group table and the geometry reader both start from this word, so it lives
#: here rather than in either of them.
SHAPE_SECTIONS_AT = 0x150
SHAPE_SECTIONS = 8


@dataclass(frozen=True)
class Face:
    """One polygon: where its corners start, and how many it has."""

    first: int
    corners: int


@dataclass(frozen=True)
class Shape:
    """One shape's faces, as a span of the mesh's face list.

    ✅ **`name` is the group's Maya name**, read from the group record that owns
    the span (D240). ⛔ D236 said which name went with which span was not
    decoded; that is superseded. It stays optional because a hand-built `Mesh`
    has no group table behind it.
    """

    first: int
    count: int
    name: str = ""
    #: The `modelmat.Layer` records this shape draws with, in GX texture-map
    #: order -- each naming a material, a wrap mode and a UV transform. ✅
    #: **Read from the shape record's layer list** (D243, D247); empty for a
    #: shape that draws untextured, which is 23% of the disc's shapes.
    #:
    #: ⚠️ **Two entries is a base layer and an alpha mask**, not two colours
    #: (D247). Entry 0 is `GX_TEXMAP0` and supplies the colour; entry 1's alpha
    #: multiplies it.
    textures: list = field(default_factory=list)  # pylint: disable=container-return
