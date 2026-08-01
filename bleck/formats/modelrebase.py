"""Where a shape's indices are relative to, read from the file's own tables.

Split out of `modelmesh`, which reads the vertex arrays themselves. This decides
*which slice* of those arrays each shape indexes into, and the two came from
different places: the arrays were found by their contents, the slices by
disassembling the draw code.

✅ **Every base here is stated by the file** (D240). The word at `0x14C` names a
table of 168-byte group records and slot 19 a table of 108-byte shape records;
the draw code loads a shape's position base with `lwz r15, 64(r14)` and scales
it by 12, then hands `GXSetArray` the array plus that offset.

⛔ **The reading this replaced counted.** It advanced the base by the number of
distinct indices each shape used, which is wrong twice over -- a slice is as
long as its largest index plus one, and consecutive shapes can share one. It
walked 4,902 of the disc's 67,280 faces off the end of the position array.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from itertools import pairwise

from bleck.formats.modelbase import SHAPE_SECTIONS_AT, Face, Shape, text

#: The word just before the sections points at the group table -- the records
#: the draw code walks. `lwz r3, 332(r4)` reads it and `mulli r0, r14, 168`
#: steps it, so one record is 168 bytes (D240).
GROUP_TABLE_AT = 0x14C
GROUP_STRIDE = 168

#: Where each field sits inside a group record. The draw code loads
#: `lwz r15, 64(r14)` and scales it by 12 for the position array, `72(r14)` by
#: 12 for normals and `88(r14)` by 8 for the first UV channel -- so each base is
#: an element index, not a byte offset. `152(r14)` and `156(r14)` are the run of
#: shapes the group owns.
GROUP_NAME_AT = 0x00
GROUP_NAME_FIELD = 0x40
GROUP_POSITION_AT = 0x40
GROUP_NORMAL_AT = 0x48
GROUP_UV_AT = 0x58
GROUP_FIRST_SHAPE_AT = 0x98
GROUP_SHAPE_COUNT_AT = 0x9C

#: A group cannot own more shapes than a file can hold. A record that claims
#: more than this is being read out of a section that is not the group table.
GROUP_LIMIT = 0x10000

#: Slot 19 holds one 108-byte record per shape -- the runtime pointer the draw
#: code loads with `lwz r4, 412(r4)` and steps with `mulli r3, r0, 108`. Its
#: `+0x38`/`+0x3C` are the shape's first face and face count, which is what
#: splits the face list.
SHAPE_RECORD_SLOT = 19
SHAPE_RECORD_STRIDE = 108

#: How many texture layers the shape draws with. ⛔ **Not a boolean** (D243):
#: 0, 1 and 2 all occur, and reading it as a flag left the 40 two-layer shapes
#: on the disc reading their UVs at the wrong corner. `modelmat` resolves the
#: layers themselves; this half only needs to know whether there are any.
RECORD_LAYERS_AT = 0x00
RECORD_FIRST_FACE_AT = 0x38
RECORD_FACE_COUNT_AT = 0x3C
RECORD_CORNER_AT = 0x40

#: The first of eight per-channel UV corner offsets: `addi r24, r29, 76` builds
#: the table and `lwzx r0, r24, r5` picks the channel. ⚠️ **Not the same as
#: `RECORD_CORNER_AT`.** A shape whose `+0x00` is zero draws with no texture
#: coordinates at all and does not advance this, so the two run apart the moment
#: a model mixes textured and untextured shapes -- `e_lui_robo_hige` reaches
#: corner 368 with 136 UV corners behind it.
RECORD_UV_CORNER_AT = 0x4C


@dataclass(frozen=True)
class Slice:
    """A run of one array: where a group's slice starts, and how long it is."""

    base: int
    count: int

    @property
    def stop(self) -> int:
        return self.base + self.count


@dataclass(frozen=True)
class Group:
    """One group record: a named run of shapes and the array slices they share.

    ✅ **This is where a shape's indices are relative to** (D240). Several
    consecutive shapes belong to one group and share its slices, which is why
    counting distinct indices per shape got the bases wrong.
    """

    name: str
    #: The run of shapes the group owns, as indices into the face groups.
    first: int
    count: int
    positions: Slice
    normals: Slice
    uvs: Slice


@dataclass(frozen=True)
class Rebased:
    """A file's faces and index streams, made absolute together.

    They travel as one value because a stream is only meaningful beside the
    faces it was rebased against — the corner base that moved a face is the
    same one that found the entries to shift.
    """

    faces: list = field(default_factory=list)  # pylint: disable=container-return
    positions: list = field(default_factory=list)  # pylint: disable=container-return
    uvs: list = field(default_factory=list)  # pylint: disable=container-return
    #: Which shape each face came from, parallel to `faces`. ⚠️ The only place
    #: the boundaries are still visible -- rebasing makes every `first`
    #: absolute, so nothing downstream can tell where one shape ended.
    groups: list = field(default_factory=list)  # pylint: disable=container-return
    #: One Maya group name per shape, in shape order. Empty when the file
    #: carries no readable group table.
    names: list = field(default_factory=list)  # pylint: disable=container-return


@dataclass(frozen=True)
class Record:
    """One shape record: its faces, and where its index streams start.

    `corner` and `uv_corner` are offsets into two different streams and are not
    interchangeable -- see `RECORD_UV_CORNER_AT`.
    """

    first: int
    count: int
    corner: int
    uv_corner: int
    textured: bool


@dataclass(frozen=True)
class Batch:
    """One shape's faces beside the corner offsets they are read at."""

    faces: list = field(default_factory=list)  # pylint: disable=container-return
    corner: int = 0
    uv_corner: int = 0
    textured: bool = True


@dataclass(frozen=True)
class Bases:
    """Where one shape's indices start in the file's shared arrays."""

    positions: int
    uvs: int


@dataclass(frozen=True)
class Held:
    """How many entries the file's shared arrays hold, which is what the group
    slices have to add up to."""

    positions: int
    uvs: int


@dataclass(frozen=True)
class Plan:
    """What the file says about where each shape's indices point.

    The records and the array lengths travel together because neither settles
    anything alone: a base is only usable once the slices are known to tile the
    array it indexes.
    """

    groups: list = field(default_factory=list)  # pylint: disable=container-return
    held: Held = Held(positions=0, uvs=0)


def group_table(data: bytes, shapes: int) -> list:  # pylint: disable=container-return
    """The group records at `0x14C`, or nothing when they do not read as such.

    ✅ **The bases are stated, not derived** (D240). Each record is 168 bytes:
    a 64-byte Maya name, then `(base, count)` pairs for positions, normals,
    colours and eight UV channels, then the run of shapes the group owns.

    ⚠️ **The table runs to the first section, not to the last drawn shape.**
    A group may own *no* shapes and still hold a slice — `e_pakflwr`'s
    `pPlaneShape1` and `e_ddtas`'s `dummy_charShape` both do — and stopping at
    the last drawn shape leaves their points out, which fails the tiling check
    and costs the model its bases.

    ⚠️ Returns `[]` rather than raising. Half the files under `files/a` are not
    models at all, and a caller that got an exception here would lose the models
    that *are* readable; the caller falls back to counting distinct indices.
    """
    if len(data) < SHAPE_SECTIONS_AT + 4 or not shapes:
        return []
    at = struct.unpack_from(">I", data, GROUP_TABLE_AT)[0]
    stop = struct.unpack_from(">I", data, SHAPE_SECTIONS_AT)[0]
    span = stop - at
    if not 0 < at < stop <= len(data) or span % GROUP_STRIDE:
        return []
    found: list[Group] = []
    covered = 0
    for index in range(span // GROUP_STRIDE):
        record = _group(data, at + index * GROUP_STRIDE)
        if record.first != covered or record.count > GROUP_LIMIT:
            return []
        found.append(record)
        covered += record.count
    return found if covered == shapes else []


def _group(data: bytes, start: int) -> Group:
    """One 168-byte group record."""
    fields = struct.unpack_from(">6I", data, start + GROUP_POSITION_AT)
    uvs = struct.unpack_from(">2I", data, start + GROUP_UV_AT)
    run = struct.unpack_from(">2I", data, start + GROUP_FIRST_SHAPE_AT)
    return Group(
        name=text(data[start + GROUP_NAME_AT :][:GROUP_NAME_FIELD]),
        first=run[0],
        count=run[1],
        positions=Slice(base=fields[0], count=fields[1]),
        normals=Slice(base=fields[2], count=fields[3]),
        uvs=Slice(base=uvs[0], count=uvs[1]),
    )


def _bases(groups: list, shapes: int, held: Held) -> list:
    # pylint: disable=container-return
    """One `Bases` per shape, spread from the groups that own them.

    ⛔ **Empty when the table does not tile the position array.** A group's
    slices are contiguous and cover the whole array, so the last group's
    `base + count` is the array's length; anything else means the records were
    misread and the caller should fall back rather than index into the wrong
    points. ✅ 860 of the disc's 864 readable models tile exactly (D240).

    ⚠️ The UV slices are checked separately and fall back to zero on their own.
    A model whose positions tile can still carry a UV table that does not, and
    losing its geometry over a texture coordinate would be the wrong trade.
    """
    if not groups:
        return []
    if groups[0].positions.base or groups[-1].positions.stop != held.positions:
        return []
    if any(a.positions.stop != b.positions.base for a, b in pairwise(groups)):
        return []
    scaled = bool(held.uvs) and groups[-1].uvs.stop == held.uvs
    found: list[Bases] = []
    for group in groups:
        found += [
            Bases(positions=group.positions.base, uvs=group.uvs.base if scaled else 0)
        ] * group.count
    return found if len(found) == shapes else []


def rebase(shapes: list, positions: list, uvs: list, plan: Plan) -> Rebased:
    """Fold each shape's corner, position and UV bases into absolute values.

    ✅ **This is what takes coverage from 13% to 100%** (D224). A file's faces
    are grouped by shape, and a group restarts its `first` at zero — so the
    corner offset *and* every index it reaches are relative to the shape, not
    the file. The draw code says so outright: `GXSetArray` is handed
    `add r16, r4, r0`, a position array **plus a per-shape offset**.

    ✅ **That offset is `0x40` of the shape's group record** (D240), which is
    why this takes `groups`. Several consecutive shapes can belong to one group
    and share its slice, so a base that advanced once per shape ran off the end
    of the array — 4,902 faces across the disc had to be dropped for it.

    ⚠️ The fallback is the older reading: advance by the number of distinct
    indices a shape used. It is wrong whenever a shape skips a point or shares a
    group, and it stays only because a file with no readable group table would
    otherwise export nothing at all.
    """
    stated = _bases(plan.groups, len(shapes), plan.held)
    bases = stated or _counted(shapes, positions, uvs)
    return Rebased(
        faces=[
            Face(first=batch.corner + face.first, corners=face.corners)
            for batch in shapes
            for face in batch.faces
        ],
        positions=_shift_positions(shapes, bases, positions),
        uvs=_shift_uvs(shapes, bases, uvs, len(positions)),
        groups=[index for index, batch in enumerate(shapes) for _ in batch.faces],
        names=[g.name for g in plan.groups for _ in range(g.count)] if stated else [],
    )


def _shift_positions(shapes: list, bases: list, stream: list) -> list:
    # pylint: disable=container-return
    """Every position index made absolute against its group's base."""
    out = list(stream)
    for base, batch in zip(bases, shapes, strict=True):
        for face in batch.faces:
            low = batch.corner + face.first
            for at in range(low, min(low + face.corners, len(out))):
                out[at] += base.positions
    return out


def _shift_uvs(shapes: list, bases: list, stream: list, size: int) -> list:
    # pylint: disable=container-return
    """One UV index per *position* corner, or `None` where there is none.

    ⚠️ **The two corner spaces are not the same one** (D240). A shape's UV
    corner offset only advances for shapes that carry texture coordinates, so
    the UV stream is shorter than the position stream on any model that mixes
    the two. Re-packing into position-corner order is what lets a `Corner` hold
    both, and the `None` is what stops an untextured shape reading the previous
    shape's coordinates.
    """
    out: list = [None] * size
    for base, batch in zip(bases, shapes, strict=True):
        if not batch.textured:
            continue
        for face in batch.faces:
            for step in range(face.corners):
                at = batch.corner + face.first + step
                source = batch.uv_corner + face.first + step
                if at < size and source < len(stream):
                    out[at] = stream[source] + base.uvs
    return out


def _counted(shapes: list, positions: list, uvs: list) -> list:
    # pylint: disable=container-return
    """The fallback bases: advance by the distinct indices each shape used.

    ⛔ **Wrong whenever a shape skips a point or shares a group** (D240), which
    is why it is only reached when the group table does not read. It stays
    because a file without one would otherwise export nothing at all.
    """
    found: list[Bases] = []
    walked = Bases(positions=0, uvs=0)
    for batch in shapes:
        found.append(walked)
        seen_positions: set[int] = set()
        seen_uvs: set[int] = set()
        for face in batch.faces:
            low = batch.corner + face.first
            stop = low + face.corners
            seen_positions |= set(positions[low:stop])
            seen_uvs |= set(uvs[low:stop])
        walked = Bases(
            positions=walked.positions + len(seen_positions),
            uvs=walked.uvs + len(seen_uvs),
        )
    return found


def spans(owners: list, names: list, bindings: list | None = None) -> list:  # pylint: disable=container-return
    """Runs of one shape id, as spans of the face list they cover.

    `bindings` is one `modelmat.Binding` per shape, so each span carries the
    images its shape draws with. It is optional because a file whose material
    chain does not read still has geometry worth returning.
    """
    bound = bindings or []
    found: list[Shape] = []
    start = 0
    for index in range(1, len(owners) + 1):
        if index == len(owners) or owners[index] != owners[start]:
            owner = owners[start]
            found.append(
                Shape(
                    first=start,
                    count=index - start,
                    name=names[owner] if owner < len(names) else "",
                    textures=(list(bound[owner].layers) if owner < len(bound) else []),
                )
            )
            start = index
    return found


def batches(data: bytes, faces: list) -> list:  # pylint: disable=container-return
    """The face list split into shapes, each with the corners it starts at.

    ✅ **Read from slot 19, not inferred** (D240). Each 108-byte record carries
    the shape's first face, its face count and where its index streams begin,
    and they partition the list exactly on 863 of the disc's 864 readable
    models.

    ⚠️ Falls back to splitting where `first` restarts at zero and accumulating
    the corner offset. That reading disagrees with the records on **51 models**
    — a shape whose first face does not start at corner zero is merged into the
    one before it — so it is a last resort, not the reading.
    """
    stated = _records(data, len(faces))
    if stated:
        return [
            Batch(
                faces=faces[r.first : r.first + r.count],
                corner=r.corner,
                uv_corner=r.uv_corner,
                textured=r.textured,
            )
            for r in stated
        ]
    found: list[Batch] = []
    corner = 0
    for group in split(faces):
        found.append(Batch(faces=group, corner=corner, uv_corner=corner, textured=True))
        corner += max((f.first + f.corners for f in group), default=0)
    return found


def _records(data: bytes, faces: int) -> list:  # pylint: disable=container-return
    """Slot 19's per-shape records, checked against the face list they split."""
    need = SHAPE_SECTIONS_AT + (SHAPE_RECORD_SLOT + 2) * 4
    if len(data) < need or not faces:
        return []
    table = struct.unpack_from(f">{SHAPE_RECORD_SLOT + 2}I", data, SHAPE_SECTIONS_AT)
    start, stop = table[SHAPE_RECORD_SLOT], table[SHAPE_RECORD_SLOT + 1]
    span = stop - start
    if not 0 < start < stop <= len(data) or span % SHAPE_RECORD_STRIDE:
        return []
    found: list[Record] = []
    seen = 0
    for index in range(span // SHAPE_RECORD_STRIDE):
        at = start + index * SHAPE_RECORD_STRIDE
        first, count = struct.unpack_from(">2I", data, at + RECORD_FIRST_FACE_AT)
        if first != seen or count > faces - seen:
            return []
        found.append(
            Record(
                first=first,
                count=count,
                corner=struct.unpack_from(">I", data, at + RECORD_CORNER_AT)[0],
                uv_corner=struct.unpack_from(">I", data, at + RECORD_UV_CORNER_AT)[0],
                textured=struct.unpack_from(">I", data, at + RECORD_LAYERS_AT)[0] > 0,
            )
        )
        seen += count
    return found if seen == faces else []


def split(faces: list) -> list:  # pylint: disable=container-return
    """Faces split where `first` restarts at zero, which is where one shape
    ends and the next begins."""
    found: list[list] = []
    current: list = []
    for face in faces:
        if face.first == 0 and current:
            found.append(current)
            current = []
        current.append(face)
    if current:
        found.append(current)
    return found
