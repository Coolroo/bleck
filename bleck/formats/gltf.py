"""Writing glTF 2.0, in the single-file `.glb` container.

⚠️ **Chosen because it can be checked by someone other than us.** A `.glb`
opens in Blender, Windows 3D Viewer and any browser, so a claim about the
geometry stops depending on `dimentio` — which is the only thing that could
display a mesh, on a machine that cannot capture its own screen (D213). An
export nobody can open independently is an export nobody can falsify.

⛔ **Wavefront OBJ was the first choice and cannot survive.** It has no
skeleton and no keyframe, so animation is not expressible in it at all. FBX
carries both and is proprietary, binary, and has no maintainable open writer.

glTF is JSON plus one binary blob, so this is stdlib-only. `bleck` ships with
two runtime dependencies, both argued for in `pyproject.toml`, and a model
exporter is not the place to spend a third.

## Four modules, one file format

| module | what it writes |
|---|---|
| `gltfcore` | the binary blob, accessors, and the per-shape vertex partition |
| `gltfmorph` | morph targets and the animations that drive them |
| `gltfpaint` | materials, samplers, textures and images |
| here | the document, the geometry attributes, and the container |

⚠️ **The imports run one way** — the three read `gltfcore`, this reads all
three, and nothing reads back.

## One primitive per shape

⛔ **Merging a file's shapes into one mesh is what made `e_lui_robo` look
broken** (D236). It holds 92 of them, one is a flat quad 130 units off to the
side, and merged there was no way to see that it was a separate object or to
hide it. Each shape is its own primitive, which is also the prerequisite for
binding a texture per shape (D229).

## Where the textures went

`gltfpaint` writes the materials, samplers, textures and images. This module
writes the geometry and calls it; the split is because a shape's texture layers
carry a wrap mode, a UV transform and possibly a mask (D247), and none of that
belongs beside the accessor arithmetic.

## The container

    [12-byte header][JSON chunk][BIN chunk]

Every chunk is padded to a 4-byte boundary -- JSON with spaces, binary with
zeros. ⚠️ The padding is not optional; a reader that trusts the length fields
will misparse the second chunk without it.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

from bleck.formats import gltfmorph, gltfpaint
from bleck.formats.gltfcore import (
    ARRAY_BUFFER,
    ELEMENT_ARRAY_BUFFER,
    FLOAT,
    UNSIGNED_BYTE,
    UNSIGNED_INT,
    Blob,
    Part,
    accessor,
    parts,
)

MAGIC = 0x46546C67
VERSION = 2
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942

#: An opaque white vertex multiplies its texture by 1 in every channel, which
#: is what a primitive with no `COLOR_0` already means.
WHITE = (255, 255, 255, 255)


def _tint_is_literal(colours: list) -> bool:
    """Whether a model's colour array can be read as a plain multiply.

    🔶 **The one place this reading is not taken at face value** (D251). Four
    models — `e_card_fre3`, `e_zun_tail`, `n_gid_tyou` and `OFF_house_02` —
    store black in **every** entry, and a literal multiply by zero would draw
    them as black silhouettes. The game draws them normally, so whatever the
    channel is configured with there, it is not this.

    ⚠️ **A positive argument, not a convenience.** The claim is only that a
    model multiplied to nothing everywhere cannot be right; a *shape* that is
    black inside a model that is not stays black, because that is ordinary art
    — 45% of `e_lui_robo`'s vertices are, and it renders correctly.
    """
    return any(tuple(rgba)[:3] != (0, 0, 0) for rgba in colours)


def _colour_attribute(
    blob: Blob,  # pylint: disable=too-many-positional-arguments
    accessors: list,
    mesh,
    part: Part,
    attributes: dict,
) -> None:
    """`COLOR_0`, where the shape's vertices carry a colour that is not white.

    ✅ **glTF multiplies `COLOR_0` into the base colour**, which is exactly the
    `GX_MODULATE` the draw code programs for a one-layer shape (D247, D251).
    Leaving it out is what made `e_lui_robo` render near-white: the disc stores
    one greyscale panel and tints it per shape.

    ⚠️ **Omitted when every vertex is opaque white**, on 524 of 864 models. The
    specification's default is a multiply by 1, so the file draws identically
    and does not carry four bytes per vertex to say nothing.
    """
    colours = getattr(mesh, "colours", None)
    if not colours or not _tint_is_literal(colours):
        return
    vertices = part.vertices
    if any(v.colour is None or v.colour >= len(colours) for v in vertices):
        return
    found = [colours[v.colour] for v in vertices]
    if all(tuple(rgba) == WHITE for rgba in found):
        return
    data = b"".join(bytes(rgba) for rgba in found)
    attributes["COLOR_0"] = len(accessors)
    record = accessor(blob.add(data, ARRAY_BUFFER), len(vertices), "VEC4", UNSIGNED_BYTE)
    # ⚠️ Required: an unsigned-byte COLOR_0 is read as 0..1 only when the
    # accessor says so, and a reader that took 255 literally would blow the
    # colour out rather than leave it alone.
    record["normalized"] = True
    accessors.append(record)


def _primitive(blob: Blob, accessors: list, mesh, part: Part) -> dict:
    # pylint: disable=container-return
    """One shape's attributes and indices, as the primitive that draws it."""
    vertices = part.vertices
    positions = [mesh.positions[v.position] for v in vertices]
    payload = b"".join(struct.pack("<3f", *p) for p in positions)

    attributes = {"POSITION": len(accessors)}
    record = accessor(blob.add(payload, ARRAY_BUFFER), len(vertices), "VEC3", FLOAT)
    # ⚠️ Required by the specification on POSITION, and some readers frame the
    # camera from it. Omitting it makes a valid-looking file open empty.
    record["min"] = [min(p[i] for p in positions) for i in range(3)]
    record["max"] = [max(p[i] for p in positions) for i in range(3)]
    accessors.append(record)

    if mesh.normals and all(
        v.normal is not None and v.normal < len(mesh.normals) for v in vertices
    ):
        data = b"".join(struct.pack("<3f", *mesh.normals[v.normal]) for v in vertices)
        attributes["NORMAL"] = len(accessors)
        accessors.append(
            accessor(blob.add(data, ARRAY_BUFFER), len(vertices), "VEC3", FLOAT)
        )

    # ⚠️ **Asked of this primitive, not of the mesh** (D243). `mesh.is_textured`
    # is false the moment any one shape draws bare, and 269 models mix the two,
    # so gating here on the whole mesh left every one of them unpaintable.
    if mesh.uvs and all(v.uv is not None and v.uv < len(mesh.uvs) for v in vertices):
        data = b"".join(struct.pack("<2f", *mesh.uvs[v.uv]) for v in vertices)
        attributes["TEXCOORD_0"] = len(accessors)
        accessors.append(
            accessor(blob.add(data, ARRAY_BUFFER), len(vertices), "VEC2", FLOAT)
        )

    _colour_attribute(blob, accessors, mesh, part, attributes)

    view = blob.add(
        struct.pack(f"<{len(part.indices)}I", *part.indices), ELEMENT_ARRAY_BUFFER
    )
    indices = len(accessors)
    accessors.append(accessor(view, len(part.indices), "SCALAR", UNSIGNED_INT))
    return {"attributes": attributes, "indices": indices}


def _lone(document: dict, blob: Blob, painted: list, texture: bytes) -> None:
    """One image over every primitive that can carry it.

    ⚠️ **Only for a caller with no layer table at all** -- `bleck model export`
    always has one. It keeps `write(texture=...)` working for a hand-built mesh
    and a single PNG.
    """
    document["images"] = [{"bufferView": blob.add(texture), "mimeType": "image/png"}]
    document["samplers"] = [{"wrapS": gltfpaint.REPEAT, "wrapT": gltfpaint.REPEAT}]
    document["textures"] = [{"sampler": 0, "source": 0}]
    document["materials"] = [
        gltfpaint.material_over(gltfpaint.Surface(image=0), texture=0)
    ]
    for primitive in painted:
        primitive["material"] = 0


#: Where a primitive says the file hides it. ⚠️ glTF has no visibility on a
#: primitive, so this is `extras` and every other reader ignores it: Blender
#: draws the shape, `dimentio` leaves it out until asked.
HIDDEN_KEY = "spmHidden"


def _mark_hidden(primitives: list, shapes: list, hidden: frozenset | None) -> None:
    """Flag every primitive whose shape slot 20 marks as off.

    ⚠️ **Matched on `Part.shape`, never on position.** `parts` drops a shape
    with no drawable faces, so the nth primitive is not the nth shape on a model
    that has one -- and the flag would land on the wrong piece silently.
    """
    if not hidden:
        return
    for primitive, part in zip(primitives, shapes, strict=True):
        if part.shape in hidden:
            primitive.setdefault("extras", {})[HIDDEN_KEY] = True


def write(  # pylint: disable=too-many-positional-arguments,too-many-arguments
    mesh,
    texture: bytes = b"",
    name: str = "",
    clips: list | None = None,
    sparse: bool = True,
    paints: list | None = None,
    hidden: frozenset | None = None,
) -> bytes:
    """One mesh as a `.glb`, one primitive per shape.

    ⚠️ Returns bytes rather than writing a file, so a caller can size it,
    checksum it or hand it to a test without touching a disk.

    ⚠️ **`clips` is a list, and the caller decides how long it is.** Every
    entry is another full set of morph targets; nothing here refuses one for
    being large, because only the caller knows the file's budget.

    ⚠️ **Primitives of one mesh, not a node each.** Both split the geometry;
    only this one keeps a single shared `weights` array, so an animation stays
    one channel rather than one per shape (D236).

    `sparse=False` writes every target in full instead — see `gltfmorph`.
    """
    shapes = parts(mesh)
    if not shapes:
        raise ValueError("the mesh has no triangles to write")

    blob = Blob()
    accessors: list = []
    primitives = [_primitive(blob, accessors, mesh, part) for part in shapes]
    _mark_hidden(primitives, shapes, hidden)

    document = {
        "asset": {"version": "2.0", "generator": "bleck"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name or mesh.name}],
        "meshes": [{"name": mesh.name, "primitives": primitives}],
        "accessors": accessors,
        "bufferViews": blob.views,
    }

    if paints:
        gltfpaint.paint(document, blob, primitives, shapes, paints)
    else:
        painted = [p for p in primitives if "TEXCOORD_0" in p["attributes"]]
        if texture and painted:
            _lone(document, blob, painted, texture)

    if clips:
        gltfmorph.apply(document, blob, shapes, clips, sparse)

    document["buffers"] = [{"byteLength": len(blob.data)}]
    return _container(document, bytes(blob.data))


@dataclass(frozen=True)
class Painting:
    """What a written `.glb` actually carries, counted from its own bytes."""

    primitives: int
    painted: int
    images: int
    #: How many distinct materials the primitives name. ⚠️ **No longer the same
    #: as `images`.** A two-layer shape's material reaches two of them (D247),
    #: and the viewer's cross-check counts materials rather than pictures.
    materials: int = 0
    #: Materials carrying a second layer in `extras`.
    masked: int = 0
    #: Primitives carrying `COLOR_0`, which multiplies their texture (D251).
    coloured: int = 0
    #: Primitives the file marks as off in slot 20. ⚠️ Counted from the emitted
    #: bytes, so a flag that never reached a primitive reads as 0 here rather
    #: than as the number of shapes the reader was handed.
    hidden: int = 0

    @property
    def textured(self) -> bool:
        """Whether any primitive in the file resolves to an image."""
        return bool(self.painted)


def parse(blob: bytes) -> dict:  # pylint: disable=container-return
    """The JSON chunk of a `.glb`, parsed the way a reader parses it."""
    at = 12
    while at + 8 <= len(blob):
        length, kind = struct.unpack_from("<II", blob, at)
        if kind == JSON_CHUNK:
            return json.loads(blob[at + 8 : at + 8 + length])
        at += 8 + length
    raise ValueError("the file carries no JSON chunk")


def painting(blob: bytes) -> Painting:
    """How much of a written file a reader will find painted.

    ⚠️ **Read back out of the emission, not taken from what the writer was
    handed** (D245). The manifest reported the images a caller had decoded, so
    ten files counted as textured while every primitive in them drew bare and
    nobody could tell from the manifest.
    """
    parsed = parse(blob)
    primitives = [p for mesh in parsed.get("meshes", []) for p in mesh["primitives"]]
    materials = parsed.get("materials", [])
    return Painting(
        primitives=len(primitives),
        painted=sum(1 for p in primitives if "material" in p),
        images=len(parsed.get("images", [])),
        materials=len(materials),
        masked=sum(1 for m in materials if gltfpaint.MASK_KEY in m.get("extras", {})),
        coloured=sum(1 for p in primitives if "COLOR_0" in p["attributes"]),
        hidden=sum(1 for p in primitives if p.get("extras", {}).get(HIDDEN_KEY)),
    )


def _container(document: dict, binary: bytes) -> bytes:
    """The 12-byte header and two padded chunks."""
    text = json.dumps(document, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)

    total = 12 + 8 + len(text) + (8 + len(binary) if binary else 0)
    out = bytearray(struct.pack("<III", MAGIC, VERSION, total))
    out += struct.pack("<II", len(text), JSON_CHUNK) + text
    if binary:
        out += struct.pack("<II", len(binary), BIN_CHUNK) + binary
    return bytes(out)
