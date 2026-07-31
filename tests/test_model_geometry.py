"""The per-shape rebasing: where a shape's indices are relative to.

⛔ **This is the load-bearing reading for geometry.** The word at `0x14C` names
a table of 168-byte group records and each one states the slice of the position
array its shapes index into. Counting the indices a shape used instead walked
4,902 of the disc's 67,280 faces off the end of the array and left the models
that survived at 90 degrees to their own normals (D240).

The split from `test_model` is size, not subject -- that module is at its
1,000-line ceiling.
"""

from __future__ import annotations

import pytest

from bleck.formats import model
from tests.test_model import MODELS, a_two_shape_model


def a_grouped_model() -> bytes:
    """Three shapes in two groups, with the group table the draw code reads.

    ⚠️ **The fixture's whole point is the second group.** It owns *two* shapes
    that share one slice of the position array, and the first of them skips a
    point — so a reader that advanced the base once per shape, by the count of
    distinct indices it saw, lands the third shape past the end of the array
    and loses it. That is exactly the defect this replaced (D240).
    """
    import struct  # pylint: disable=import-outside-toplevel

    out = bytearray(0x640)
    groups_at = 0x1B0
    table = [0x300, 0x318, 0x390, 0x3C0, 0x438, 0x468, 0x468, 0x468]
    table += [0x498] * 8 + [0x4D8] * 4 + [0x61C] * 4
    struct.pack_into(">24I", out, model.SHAPE_SECTIONS_AT, *table)
    struct.pack_into(">I", out, model.GROUP_TABLE_AT, groups_at)

    for index, (name, points, uvs, first, count) in enumerate(
        [
            (b"firstShape", (0, 4), (0, 4), 0, 1),
            (b"sharedShape", (4, 6), (4, 4), 1, 2),
        ]
    ):
        at = groups_at + index * model.GROUP_STRIDE
        out[at : at + len(name)] = name
        struct.pack_into(">4I", out, at + 0x40, points[0], points[1], 0, 0)
        struct.pack_into(">2I", out, at + 0x58, uvs[0], uvs[1])
        struct.pack_into(">2I", out, at + 0x98, first, count)

    for index in range(3):
        at = table[19] + index * model.SHAPE_RECORD_STRIDE
        struct.pack_into(">I", out, at + 0x00, 1)
        struct.pack_into(">2I", out, at + 0x38, index, 1)
        struct.pack_into(">I", out, at + 0x40, index * 4)
        struct.pack_into(">I", out, at + 0x4C, index * 4)
        struct.pack_into(">II", out, table[0] + index * model.FACE_STRIDE, 0, 4)

    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    points += [(x, y, 1.0) for x, y, _ in points]
    points += [(2.0, 0.0, 1.0), (2.0, 1.0, 1.0)]
    for index, point in enumerate(points):
        struct.pack_into(">3f", out, table[1] + index * model.TRIPLE, *point)
        struct.pack_into(">3f", out, table[3] + index * model.TRIPLE, 0.0, 0.0, 1.0)

    reached = [0, 1, 2, 3, 0, 1, 2, 5, 0, 1, 2, 3]
    for index, position in enumerate(reached):
        struct.pack_into(">I", out, table[2] + index * 4, position)
        struct.pack_into(">I", out, table[4] + index * 4, index % len(points))
        struct.pack_into(">I", out, table[7] + index * 4, index % 4)

    lower = [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)]
    for index, pair in enumerate(lower + [(u + 0.5, v + 0.5) for u, v in lower]):
        struct.pack_into(">2f", out, table[8] + index * model.UV_PAIR, *pair)
    return bytes(out)


class TestTheGroupTable:
    """⛔ **A shape's position base is stated, never counted** (D240).

    The word at `0x14C` points at 168-byte group records, and the draw code
    loads the base out of one: `lwz r15, 64(r14)` then `mulli r0, r15, 12`, fed
    to `GXSetArray` as `add r16, r4, r0`.

    The reading it replaced advanced the base by the number of *distinct*
    indices each shape used. That is wrong twice over — a block is as long as
    its largest index plus one, and consecutive shapes can share one block — and
    it walked 4,902 faces of the disc's 67,280 off the end of the position
    array.

    ⚠️ **Pin the invariants, not the numbers.** Earlier tests here were rewritten
    three times because each encoded a count a later reading changed. What has
    to stay true is that the slices tile the array and that nothing falls off it.
    """

    def test_a_shared_group_does_not_advance_the_base(self):
        found = model.mesh(a_grouped_model())
        assert found.shapes == 3
        assert found.corner_positions == [0, 1, 2, 3, 4, 5, 6, 9, 4, 5, 6, 7], (
            "the third shape did not get its group's base; counting distinct "
            "indices per shape would have sent it to 8-11, past the array"
        )

    def test_no_face_falls_off_the_end_of_the_fixture(self):
        """⚠️ The defect showed up as *missing* geometry, not wrong geometry —
        a face whose indices leave the array is dropped rather than drawn."""
        found = model.mesh(a_grouped_model())
        assert len(found.faces) == 3
        assert found.is_drawable
        assert found.coverage == 0.9, (
            "one point is skipped on purpose: a block is as long as its "
            "largest index plus one, not as long as the indices used"
        )

    def test_a_span_carries_its_maya_name(self):
        """⛔ D236 said which name went with which span was not decoded."""
        found = model.mesh(a_grouped_model())
        assert [span.name for span in found.shape_spans()] == [
            "firstShape",
            "sharedShape",
            "sharedShape",
        ]

    def test_a_file_with_no_group_table_still_reads(self):
        """⚠️ The fallback has to survive. Half of `files/a` is not a model, and
        a reader that needed the table would return nothing for the rest."""
        found = model.mesh(a_two_shape_model())
        assert found.shapes == 2
        assert found.corner_positions == [0, 1, 2, 3, 4, 5, 6, 7]

    def test_the_slices_tile_the_position_array_across_the_disc(self):
        """✅ The invariant that says the records were read correctly: a group's
        slice starts where the one before it ended, the first starts at zero and
        the last ends at the array's length."""
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        import struct  # pylint: disable=import-outside-toplevel

        tiled = 0
        for path in sorted(MODELS.iterdir()):
            if not path.is_file():
                continue
            data = path.read_bytes()
            try:
                found = model.mesh(data)
            except model.ModelError:
                continue
            at = struct.unpack_from(">I", data, model.GROUP_TABLE_AT)[0]
            stop = struct.unpack_from(">I", data, model.SHAPE_SECTIONS_AT)[0]
            span = stop - at
            if not 0 < at < stop <= len(data) or span % model.GROUP_STRIDE:
                continue
            slices = [
                struct.unpack_from(">2I", data, at + i * model.GROUP_STRIDE + 0x40)
                for i in range(span // model.GROUP_STRIDE)
            ]
            walked = 0
            for base, count in slices:
                if base != walked:
                    break
                walked += count
            else:
                if walked == len(found.positions):
                    tiled += 1
        assert tiled >= 860, (
            f"only {tiled} models tile their position array; the group records "
            "are no longer being read where the draw code reads them"
        )

    def test_no_face_on_the_disc_rebases_past_its_array(self):
        """⛔ **This was 4,902 faces over 98 models** and is the headline the
        fix earned. A dropped face is silent — the export just has a hole."""
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        import struct  # pylint: disable=import-outside-toplevel

        dropped = 0
        checked = 0
        for path in sorted(MODELS.iterdir()):
            if not path.is_file():
                continue
            data = path.read_bytes()
            try:
                found = model.mesh(data)
            except model.ModelError:
                continue
            table = struct.unpack_from(">2I", data, model.SHAPE_SECTIONS_AT)
            written = (table[1] - table[0]) // model.FACE_STRIDE
            dropped += written - len(found.faces)
            checked += written
        assert checked > 60000, f"only {checked} faces; the sweep is weak"
        assert dropped == 0, f"{dropped} of {checked} faces rebased off the end"

    def test_the_stored_normals_agree_with_the_geometry(self):
        """✅ **The reference-free oracle** (D240): a face's own normal against
        the mean of the normals its corners name. It needs no reference model,
        so it runs on everything.

        ⛔ **Both controls matter.** `_hige` and `_foot` already read correctly
        before the group table was found, and had to stay that way; `e_lui_robo`
        and `_hand` sat at 90 degrees, which is what a wrong base looks like —
        the geometry is not merely inaccurate, it is unrelated.
        """
        for name in (
            "e_lui_robo",
            "e_lui_robo_hand",
            "e_lui_robo_hige",
            "e_lui_robo_foot",
            "e_lui_robo_antena",
            "e_lui_robo_missile",
        ):
            path = MODELS / name
            if not path.is_file():
                pytest.skip(f"no {path}")
            found = model.mesh(path.read_bytes())
            angles = sorted(_normal_angles(found))
            assert angles, name
            median = angles[len(angles) // 2]
            assert median < 5.0, f"{name}: median {median:.2f} deg off"


def _normal_angles(found) -> list:
    """The angle between each face's own normal and its corners' stored ones."""
    import math  # pylint: disable=import-outside-toplevel

    out = []
    for triangle in found.corner_triangles():
        a, b, c = (found.positions[corner.position] for corner in triangle)
        edge = [b[i] - a[i] for i in range(3)]
        arm = [c[i] - a[i] for i in range(3)]
        plane = _unit(
            [
                edge[1] * arm[2] - edge[2] * arm[1],
                edge[2] * arm[0] - edge[0] * arm[2],
                edge[0] * arm[1] - edge[1] * arm[0],
            ]
        )
        stored = [0.0, 0.0, 0.0]
        for corner in triangle:
            if corner.normal is None or corner.normal >= len(found.normals):
                stored = None
                break
            for axis in range(3):
                stored[axis] += found.normals[corner.normal][axis]
        stored = _unit(stored) if stored else None
        if plane is None or stored is None:
            continue
        dot = max(-1.0, min(1.0, sum(plane[i] * stored[i] for i in range(3))))
        out.append(math.degrees(math.acos(dot)))
    return out


def _unit(vector) -> list | None:
    length = sum(value * value for value in vector) ** 0.5
    return None if length < 1e-12 else [value / length for value in vector]


class TestCoverageIsReported:
    """Coverage, which is now the check that the rebasing still works.

    ⛔ **This class used to assert the opposite.** It pinned a median of 13.7%
    as the expected state, so it would have passed forever while the reader was
    wrong -- and would have *failed* the fix. A test that encodes a known
    deficiency as an invariant defends the bug (D224).
    """

    def test_coverage_is_low_and_says_so(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        rates = []
        for path in sorted(MODELS.iterdir()):
            if not path.is_file():
                continue
            data = path.read_bytes()
            if not model.is_model(data):
                continue
            try:
                found = model.mesh(data)
            except model.ModelError:
                continue
            rates.append(found.coverage)
        assert len(rates) > 800
        rates.sort()
        median = rates[len(rates) // 2]
        # ⛔ Inverted in D224. It used to demand coverage stay *below* 50%,
        # pinning 13.7% as though that were the format rather than a
        # misreading of it -- so it would have failed the fix.
        assert median > 0.95, (
            f"median coverage is {median:.1%}, was 100%. The per-shape "
            "rebasing in D224 has regressed."
        )

    def test_describe_names_the_coverage(self):
        mesh = model.Mesh(
            name="x",
            positions=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (2.0, 2.0, 2.0),
            ],
            faces=[model.Face(first=0, corners=3)],
            corner_positions=[0, 1, 2],
        )
        assert mesh.coverage == 0.75
        assert "75.0% covered" in mesh.describe()

    def test_an_empty_mesh_has_no_coverage(self):
        assert model.Mesh(name="x").coverage == 0.0
