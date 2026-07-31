"""Character models from `files/a/`, as far as they are decoded.

⚠️ **Deliberately incomplete, and says so.** Geometry is not read. A model
reader that returned empty vertex lists would look like a working one, so
`Model.has_geometry` is a hard `False` rather than an empty list a caller might
render as an invisible mesh.

⛔ The load-bearing test is `TestTheTexturePairing`. A model names its textures
by original TGA path and the bank beside it holds the images; the pairing is
only a reading because **no model on the disc references more textures than its
bank has**, across 787 pairs.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from bleck.formats import model, tpl

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "work" / "extracted" / "eu0" / "files" / "a"


#: Where the fixture puts the record the leading word points at.
RECORD_AT = 0x180


def a_model(name: str = "test_model", height: float = 20.0) -> bytes:
    """The smallest thing `read` accepts: a leading offset, a name, a box.

    ⚠️ The box goes in the *pointed-at* record, not the opening one. Putting it
    at a plausible-looking offset in the header is what the reader used to
    accept, and it gave Mario a height of 17.9 (D202).
    """
    import struct  # pylint: disable=import-outside-toplevel

    out = bytearray(RECORD_AT + 0x80)
    struct.pack_into(">I", out, 0, RECORD_AT)
    out[model.NAME_AT : model.NAME_AT + len(name)] = name.encode()
    stamp = b"Mon Jan 29 10:30:46 2007"
    out[model.STAMP_AT : model.STAMP_AT + len(stamp)] = stamp
    struct.pack_into(
        ">6f", out, RECORD_AT + model.BOUNDS_AT, -1.0, 0.0, -1.0, 1.0, height, 1.0
    )
    return bytes(out)


class TestReading:
    def test_a_minimal_model_reads(self):
        found = model.read(a_model())
        assert found.name == "test_model"
        assert found.stamp.startswith("Mon Jan 29")
        assert found.bounds.height == 20.0

    def test_geometry_is_an_honest_no(self):
        """⛔ Not an empty list. A caller must not be able to render nothing."""
        assert model.read(a_model()).has_geometry is False

    def test_something_shapeless_is_refused(self):
        with pytest.raises(model.ModelError, match="not a character model"):
            model.read(b"\x00" * 512)

    def test_a_leading_offset_past_the_end_is_refused(self):
        import struct  # pylint: disable=import-outside-toplevel

        data = bytearray(a_model())
        struct.pack_into(">I", data, 0, 0xFFFFFF)
        assert not model.is_model(bytes(data))

    def test_six_floats_that_are_not_a_box_are_refused(self):
        """⛔ min above max is not a bounding box. Accepting it is how the
        first version read a sub-object's numbers as the whole model's."""
        import struct  # pylint: disable=import-outside-toplevel

        data = bytearray(a_model())
        struct.pack_into(
            ">6f", data, RECORD_AT + model.BOUNDS_AT, 9.0, 9.0, 9.0, 1.0, 1.0, 1.0
        )
        with pytest.raises(model.ModelError, match="not a bounding box"):
            model.read(bytes(data))

    def test_the_bank_is_the_name_plus_a_dash(self):
        assert model.bank_for(Path("a/p_wii_mario")).name == "p_wii_mario-"


@pytest.mark.gamedata
class TestAgainstTheDisc:
    def _models(self) -> list[Path]:
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        return [
            p
            for p in sorted(MODELS.iterdir())
            if p.is_file() and not p.name.endswith("-")
        ]

    def test_almost_every_model_reads(self):
        """⚠️ Two `.bin` files are refused, and should be: they are a different
        thing that happens to live in the same directory."""
        found = self._models()
        read = sum(1 for p in found if model.is_model(p.read_bytes()))
        assert read > 850
        assert len(found) - read <= 2

    def test_mario_is_mario_shaped(self):
        """A bounding box read from the wrong offset gives six plausible
        numbers, so this checks one whose value is known independently."""
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip("no p_wii_mario")
        found = model.read(path.read_bytes())
        assert found.name == "p_wii_mario"
        assert 70.0 < found.bounds.height < 76.0
        assert any("zentai" in s for s in found.shapes)


@pytest.mark.gamedata
class TestTheTexturePairing:
    """⛔ The invariant that makes the model-to-texture link a reading."""

    def _pairs(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        for path in sorted(MODELS.iterdir()):
            if not path.is_file() or path.name.endswith("-"):
                continue
            bank = model.bank_for(path)
            if not bank.is_file():
                continue
            try:
                found = model.read(path.read_bytes())
                images = tpl.read(bank.read_bytes())
            except Exception:  # pylint: disable=broad-exception-caught
                continue
            yield path.name, found, len(images)

    def test_no_model_names_more_textures_than_its_bank_holds(self):
        """A bank may carry images nothing references. The reverse never
        happens, and if it did the pairing would be wrong."""
        over = [
            (name, len(found.textures), images)
            for name, found, images in self._pairs()
            if len(found.textures) > images
        ]
        assert not over, f"{len(over)} models over-reference: {over[:3]}"

    def test_the_counts_agree_for_the_large_majority(self):
        exact = total = 0
        for _name, found, images in self._pairs():
            total += 1
            exact += len(found.textures) == images
        assert total > 700
        assert exact * 10 > total * 9, f"only {exact} of {total} agree exactly"

    def test_mario_pairs_exactly(self):
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip("no p_wii_mario")
        found = model.read(path.read_bytes())
        images = tpl.read(model.bank_for(path).read_bytes())
        assert len(found.textures) == len(images) == 126


@pytest.mark.gamedata
class TestClips:
    """The animation table: fixed-stride name plus a pointer to clip data."""

    def _mario(self) -> model.Model:
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip("no p_wii_mario")
        return model.read(path.read_bytes())

    def test_mario_has_his_clips(self):
        found = self._mario()
        names = [c.name for c in found.animations]
        assert len(names) == 94
        assert "mario_Z_1" in names
        assert "mario_W_1" in names

    def test_no_clip_name_carries_a_stray_leading_byte(self):
        """⚠️ A loose scan read `mario_S_3` as `Tmario_S_3` -- the tail of the
        previous record, printable by chance. The strided read cannot do that,
        and this is what would notice if it were reintroduced."""
        for clip in self._mario().animations:
            assert clip.name.startswith("mario_"), clip.name

    def test_every_clip_points_inside_its_own_file(self):
        """⛔ The check that makes the pointer a pointer. Across all 869 models
        and 10,851 clips, none falls outside."""
        outside = 0
        checked = 0
        for path in sorted(MODELS.iterdir()) if MODELS.is_dir() else []:
            if not path.is_file() or path.name.endswith("-"):
                continue
            data = path.read_bytes()
            try:
                found = model.read(data)
            except model.ModelError:
                continue
            for clip in found.animations:
                checked += 1
                if not 0 < clip.offset < len(data):
                    outside += 1
        if not checked:
            pytest.skip("no extracted disc")
        assert checked > 10000
        assert outside == 0

    def test_clips_are_not_playable_and_say_so(self):
        """⛔ Names, pointers and section boundaries are not keyframes."""
        assert self._mario().can_animate is False

    def test_record_sizes_chain_to_the_next_clip(self):
        """`offset + size` lands exactly on the next clip's offset."""
        found = self._mario()
        for first, second in itertools.pairwise(found.animations):
            assert first.offset + first.size == second.offset, first.name

    def test_the_records_account_for_every_byte(self):
        """⛔ The check that makes this a decode rather than a plausible read.

        94 record sizes sum to exactly the region between the first clip and
        the end of the file. One wrong size and this misses.
        """
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip("no p_wii_mario")
        data = path.read_bytes()
        found = model.read(data)
        total = sum(clip.size for clip in found.animations)
        assert total == len(data) - found.animations[0].offset

    def test_the_counted_sections_divide_by_their_own_counts(self):
        """⚠️ Only sections 1, 2 and 4 -- and that limit is the finding.

        A first version asserted *every* section divides and failed on a fixed
        12-byte one. Sections 0, 5 and 6 are fixed-size or padded; the counted
        ones divide 94, 88 and 91 times out of 94 with no exceptions, which is
        what says the header's counts describe those sections specifically.
        """
        odd = []
        for clip in self._mario().animations:
            bounds = clip.section_bounds()
            for index in model.COUNTED_SECTIONS:
                if index >= len(bounds):
                    continue
                _start, length = bounds[index]
                if not length:
                    continue
                if not any(c and length % c == 0 for c in clip.counts):
                    odd.append((clip.name, index, length, clip.counts))
        assert not odd, f"{len(odd)} counted sections do not divide: {odd[:3]}"


class TestTheVertexArrays:
    """⛔ The load-bearing test in this file, and the reason `mesh` is trusted.

    Slot 3 holding normals is not an inference from where it sits -- it is the
    only slot whose triples are **unit length**, and that holds on 864 of the
    870 model files on the disc. A wrong reading cannot produce that; floats
    read at the wrong stride or offset scatter immediately (D207).
    """

    def test_every_normal_on_the_disc_is_unit_length(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        decoded = 0
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
            decoded += 1
            for triple in itertools.islice(found.normals, 64):
                length = sum(v * v for v in triple) ** 0.5
                assert abs(length - 1.0) <= model.UNIT_TOLERANCE, path.name
        assert decoded > 800, f"only {decoded} models decoded; the reader regressed"

    def test_mario_matches_what_was_measured(self):
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        found = model.mesh(path.read_bytes())
        assert found.name == "R_Arm_skinShape"
        assert len(found.positions) == 324
        assert len(found.normals) == 336
        assert found.streams == [192, 336, 336, 336]

    def test_positions_sit_inside_a_character_sized_box(self):
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        found = model.mesh(path.read_bytes())
        widest = max(abs(v) for triple in found.positions for v in triple)
        assert 1.0 < widest < 500.0, f"{widest} is not a character coordinate"

    def test_a_non_unit_slot_is_refused_not_returned(self):
        """⚠️ The check must reject. Six files on the disc fail it, and a
        reader that shrugged would hand a viewer garbage that looks like data."""
        data = bytearray(a_model())
        data.extend(b"\x00" * (0x20000 - len(data)))
        import struct  # pylint: disable=import-outside-toplevel

        table = [0x1000 + i * 0x1000 for i in range(model.SHAPE_SECTIONS)]
        struct.pack_into(">8I", data, model.SHAPE_SECTIONS_AT, *table)
        struct.pack_into(">I", data, model.SHAPE_NAME_AT, 0x1B0)
        for i in range(64):
            at = table[model.NORMAL_SLOT] + i * 12
            struct.pack_into(">3f", data, at, 5.0, 5.0, 5.0)
        with pytest.raises(model.ModelError, match="not a normal array"):
            model.mesh(bytes(data))

    def test_a_file_with_no_section_table_is_refused(self):
        with pytest.raises(model.ModelError):
            model.mesh(a_model())


class TestTheFaceList:
    """The second independent proof, and the reason `faces` is trusted.

    Slot 0 read as `(first, count)` pairs is not just a shape that fits: the
    counts **sum to the length of the index streams**, on all 864 models that
    decode. A wrong stride or slot gives a sum that misses, so `mesh` refuses
    rather than returning a face list that would tear a mesh apart (D207).
    """

    def test_every_model_corner_count_adds_up(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        decoded = 0
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
            decoded += 1
            # ⚠️ Faces are rebased and the few that land outside are dropped
            # (D224), so the sum is a ceiling now rather than an equality.
            assert found.corners <= max(found.streams), path.name
        assert decoded > 800, f"only {decoded} models decoded; the reader regressed"

    def test_mario_is_triangles_and_quads(self):
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        found = model.mesh(path.read_bytes())
        assert len(found.faces) == 96
        assert found.corners == 336
        sizes = sorted(face.corners for face in found.faces)
        assert sizes[0] == 3 and sizes[-1] == 11

    def test_no_face_is_degenerate(self):
        """⚠️ A count below 3 is not a polygon. If one appears, the pairs are
        being read at the wrong stride and the sum matching was luck."""
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        for face in model.mesh(path.read_bytes()).faces:
            assert face.corners >= 3, face


def _planarity(points) -> float | None:
    """How far the fourth corner sits out of the plane of the first three,
    as a fraction of the first edge's length."""

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    edge, other = sub(points[1], points[0]), sub(points[2], points[0])
    normal = (
        edge[1] * other[2] - edge[2] * other[1],
        edge[2] * other[0] - edge[0] * other[2],
        edge[0] * other[1] - edge[1] * other[0],
    )
    scale = dot(normal, normal) ** 0.5
    if scale < 1e-9:
        return None
    normal = tuple(c / scale for c in normal)
    return abs(dot(sub(points[3], points[0]), normal)) / max(dot(edge, edge) ** 0.5, 1e-9)


class TestTheFacesAreRealGeometry:
    """⛔ The test that made the mesh trustworthy, and the reason `is_drawable`
    is allowed to be True at all.

    A 4-corner face of a real mesh is **planar**. Shuffled indices are not.

    ⚠️ **Two separate ways this test lied before it was trusted** (D209, D211):

    1. The first shape measured was itself flat, so every *random* quad was
       coplanar too and the control confirmed nothing.
    2. 16% of quads reference fewer than four distinct vertices. A degenerate
       quad is planar for free, and counting them inflated the result from a
       real 72% to a meaningless 98%.

    So this excludes degenerate faces and asserts the *gap* to a per-model
    control, not an absolute rate.
    """

    def test_real_faces_are_far_more_planar_than_shuffled_ones(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        import random  # pylint: disable=import-outside-toplevel

        random.seed(7)
        real_rates, control_rates = [], []
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
            spread = [
                max(p[i] for p in found.positions) - min(p[i] for p in found.positions)
                for i in range(3)
            ]
            if min(spread) < 5:
                continue
            real, control = [], []
            for face in found.faces:
                if face.corners != 4:
                    continue
                corners = found.corner_positions[face.first : face.first + 4]
                if len(set(corners)) < 4:
                    continue
                value = _planarity([found.positions[c] for c in corners])
                if value is not None:
                    real.append(value)
                shuffled = [
                    found.positions[random.randrange(len(found.positions))]
                    for _ in range(4)
                ]
                value = _planarity(shuffled)
                if value is not None:
                    control.append(value)
            if len(real) < 10:
                continue
            real_rates.append(sum(1 for v in real if v < 0.05) / len(real))
            control_rates.append(sum(1 for v in control if v < 0.05) / len(control))

        assert len(real_rates) > 50, f"only {len(real_rates)} 3D shapes; test is weak"
        real_rates.sort()
        control_rates.sort()
        real_median = real_rates[len(real_rates) // 2]
        control_median = control_rates[len(control_rates) // 2]
        assert real_median > 0.60, real_median
        assert control_median < 0.40, control_median
        assert real_median > control_median * 2


class TestDrawing:
    def test_every_readable_model_is_drawable(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        read = drawable = 0
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
            read += 1
            drawable += 1 if found.is_drawable else 0
        assert read > 800
        assert drawable == read, f"{read - drawable} readable models cannot be drawn"

    def test_triangles_index_real_positions(self):
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        found = model.mesh(path.read_bytes())
        assert found.triangles()
        for triangle in found.triangles():
            for index in triangle:
                assert 0 <= index < len(found.positions)

    def test_a_face_off_the_end_is_not_drawable(self):
        """⚠️ `is_drawable` has to be able to say no, or it says nothing."""
        broken = model.Mesh(
            name="x",
            positions=[(0.0, 0.0, 0.0)],
            faces=[model.Face(first=0, corners=3)],
            corner_positions=[0, 1, 99],
        )
        assert not broken.is_drawable


def a_two_shape_model() -> bytes:
    """Two quads written as two shapes, each restarting its indices at zero.

    ⚠️ **The point of the fixture is the restart.** Both shapes name positions
    0-3 and UVs 0-3, so a reader that does not add the per-shape base draws the
    second quad with the first quad's data and cannot tell it went wrong.
    """
    import struct  # pylint: disable=import-outside-toplevel

    out = bytearray(0x3C0)
    table = [0x200, 0x210, 0x270, 0x290, 0x2F0, 0x310, 0x330, 0x350]
    table += [0x370] * 8 + [0x3B0] * 8
    struct.pack_into(">24I", out, model.SHAPE_SECTIONS_AT, *table)
    struct.pack_into(">I", out, model.SHAPE_NAME_AT, 0x100)
    out[0x100:0x108] = b"pairShap"

    struct.pack_into(">II", out, table[0], 0, 4)
    struct.pack_into(">II", out, table[0] + 8, 0, 4)
    corners = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    points = [(x, y, 0.0) for x, y in corners]
    points += [(x + 2.0, y, 0.0) for x, y in corners]
    for i, point in enumerate(points):
        struct.pack_into(">3f", out, table[1] + i * model.TRIPLE, *point)
        struct.pack_into(">3f", out, table[3] + i * model.TRIPLE, 0.0, 0.0, 1.0)
        struct.pack_into(">I", out, table[2] + i * 4, i % 4)
        struct.pack_into(">I", out, table[4] + i * 4, i)
        struct.pack_into(">I", out, table[5] + i * 4, 0xFFFFFFFF)
        struct.pack_into(">I", out, table[6] + i * 4, i)
        struct.pack_into(">I", out, table[7] + i * 4, i % 4)

    lower = [(u / 2, v / 2) for u, v in corners]
    for i, pair in enumerate(lower + [(u + 0.5, v + 0.5) for u, v in lower]):
        struct.pack_into(">2f", out, table[8] + i * model.UV_PAIR, *pair)
    return bytes(out)


class TestTheTexcoordIndex:
    """⛔ UVs are indexed **per corner**, from slot 7, and rebased per shape.

    The reading this replaced paired a UV to a *position* index. It survived
    because 74% of models happen to carry one UV per position — but 26% do not,
    and every one of them exported bare. `e_bara_tib_p` has 64 positions and 96
    UVs, and its slot-7 stream has one entry per corner with a maximum of 63,
    which is only below 96 because each shape restarts (D234).

    ⚠️ The instrument is **UV triangle area**, not "did a texture appear". A
    wrong index still produces a textured model, with the art smeared across
    it. Correct UVs give small coherent triangles; the shuffled control below
    is what says so.
    """

    def test_the_second_shape_gets_its_own_uv_base(self):
        found = model.mesh(a_two_shape_model())
        assert found.shapes == 2
        assert found.corner_positions == [0, 1, 2, 3, 4, 5, 6, 7]
        assert found.corner_uvs == [0, 1, 2, 3, 4, 5, 6, 7], (
            "the per-shape UV base was not folded in; the second quad is "
            "drawing with the first quad's texture coordinates"
        )

    def test_the_second_quad_lands_on_its_own_corner_of_the_image(self):
        """The same fact stated as art rather than as indices: shape 2's UVs
        all sit in the upper half of the image, and shape 1's in the lower."""
        found = model.mesh(a_two_shape_model())
        first, second = found.faces
        for at in range(first.first, first.first + first.corners):
            assert max(found.uvs[found.corner_uvs[at]]) <= 0.5
        for at in range(second.first, second.first + second.corners):
            assert min(found.uvs[found.corner_uvs[at]]) >= 0.5

    def test_a_corner_carries_its_uv_index(self):
        found = model.mesh(a_two_shape_model())
        for triangle in found.corner_triangles():
            for corner in triangle:
                assert corner.uv is not None
                assert corner.uv < len(found.uvs)

    def test_more_uvs_than_positions_is_still_textured(self):
        """⛔ `is_textured` was `len(uvs) == len(positions)`, which is false for
        every model this fixes."""
        found = model.Mesh(
            name="x",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[model.Face(first=0, corners=3)],
            corner_positions=[0, 1, 2],
            corner_uvs=[2, 3, 4],
            uvs=[(0.0, 0.0)] * 5,
        )
        assert len(found.uvs) != len(found.positions)
        assert found.is_textured

    def test_a_corner_pointing_past_the_uv_array_is_not_textured(self):
        """⚠️ The check has to be able to say no, or it says nothing."""
        found = model.Mesh(
            name="x",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[model.Face(first=0, corners=3)],
            corner_positions=[0, 1, 2],
            corner_uvs=[0, 1, 9],
            uvs=[(0.0, 0.0)] * 3,
        )
        assert not found.is_textured

    def test_bara_tib_carries_a_uv_for_every_corner(self):
        """The model this was reported against: 64 positions, 96 UVs, bare."""
        path = MODELS / "e_bara_tib_p"
        if not path.is_file():
            pytest.skip(f"no {path}")
        found = model.mesh(path.read_bytes())
        assert len(found.positions) == 64
        assert len(found.uvs) == 96
        assert found.is_textured

    def test_the_disc_gains_textures_and_loses_none(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        before = after = 0
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
            if not found.is_drawable:
                continue
            before += 1 if len(found.uvs) == len(found.positions) and found.uvs else 0
            after += 1 if found.is_textured else 0
        assert before == 639, f"{before} models match by count; the corpus moved"
        assert after >= 770, (
            f"{after} models are textured, was 770. The slot-7 reading has "
            "regressed to pairing UVs by position index."
        )

    def test_real_uv_triangles_are_tighter_than_shuffled_ones(self):
        """⛔ The control, and the reason the reading is believed at all.

        A face's three corners land close together on the texture; a wrong
        index scatters them across it. Measured over the models slot 7
        unlocked: **0.0474** median UV triangle area against **0.1342** for a
        shuffled control (D234).
        """
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        import random  # pylint: disable=import-outside-toplevel

        random.seed(2026)
        real, control = [], []
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
            if not found.is_textured or len(found.uvs) == len(found.positions):
                continue
            shuffled = list(range(len(found.uvs)))
            random.shuffle(shuffled)
            for triangle in found.corner_triangles():
                real.append(_uv_area([found.uvs[c.uv] for c in triangle]))
                control.append(_uv_area([found.uvs[shuffled[c.uv]] for c in triangle]))
        assert len(real) > 20000, f"only {len(real)} faces; the test is weak"
        real.sort()
        control.sort()
        tight = real[len(real) // 2]
        loose = control[len(control) // 2]
        assert tight < 0.06, tight
        assert tight < loose / 2, (tight, loose)


def _uv_area(points) -> float:
    """Twice the area of a UV triangle, in texture space."""
    (au, av), (bu, bv), (cu, cv) = points
    return abs((bu - au) * (cv - av) - (cu - au) * (bv - av)) / 2.0


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


class TestTheCurveEncoding:
    """⛔ The load-bearing test for animation, and the reason `curves` is
    trusted at all.

    A key's value is a **delta**, not an absolute. Accumulating deltas produces
    a smooth curve; reading the same bytes as absolute values does not. Measured
    as mean second difference over range, against a control that shuffles the
    key array:

    | reading | roughness |
    |---|---|
    | accumulated | **0.0112** |
    | absolute | 0.3229 |
    | shuffled control | 0.155 |

    A fourteen-fold separation from the control (D216).
    """

    def _roughness(self, sequences) -> float:
        import statistics  # pylint: disable=import-outside-toplevel

        scores = []
        for values in sequences:
            if len(values) < 6:
                continue
            span = max(values) - min(values)
            if span < 1e-9:
                continue
            bends = [
                abs(values[i + 1] - 2 * values[i] + values[i - 1])
                for i in range(1, len(values) - 1)
            ]
            scores.append(statistics.mean(bends) / span)
        return statistics.median(scores) if scores else 1.0

    def test_accumulated_curves_are_far_smoother_than_shuffled_keys(self):
        import random  # pylint: disable=import-outside-toplevel
        import struct  # pylint: disable=import-outside-toplevel

        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        random.seed(2)
        data = path.read_bytes()
        found = model.read(data)
        clip = next(c for c in found.animations if c.name == "mario_S_1")

        real = [c.values for c in model.curves(data, clip)]
        assert len(real) > 20

        table = struct.unpack_from(
            f">{model.CLIP_SECTIONS}I", data, clip.offset + model.CLIP_SECTIONS_AT
        )
        keys_at = clip.offset + table[model.KEY_SECTION]
        total = (
            table[model.KEY_SECTION + 1] - table[model.KEY_SECTION]
        ) // model.CLIP_KEY_STRIDE
        order = list(range(total))
        random.shuffle(order)
        pool = b"".join(data[keys_at + i * 4 : keys_at + i * 4 + 4] for i in order)
        shuffled = []
        for curve in model.curves(data, clip):
            running = 0
            values = []
            for step in range(len(curve.values)):
                running += struct.unpack_from(">h", pool, step * 4 + 1)[0]
                values.append(running / model.KEY_SCALE)
            shuffled.append(values)

        assert self._roughness(real) < 0.05
        assert self._roughness(real) < self._roughness(shuffled) / 3

    def test_values_land_in_model_space(self):
        """✅ Track 5 of `mario_S_1` reaches 58.8, and the model's Y bound is
        58.7. That is what fixes the 1/256 scale rather than guessing it."""
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        data = path.read_bytes()
        clip = next(c for c in model.read(data).animations if c.name == "mario_S_1")
        found = model.curves(data, clip)
        reach = max(max(abs(v) for v in c.values) for c in found)
        assert 10.0 < reach < 1000.0, reach

    def test_every_clip_on_the_disc_decodes_without_raising(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        clips = curves = 0
        for path in sorted(MODELS.iterdir()):
            if not path.is_file():
                continue
            data = path.read_bytes()
            if not model.is_model(data):
                continue
            try:
                found = model.read(data)
            except model.ModelError:
                # ⚠️ Some files fail the bounding-box check; that is `read`'s
                # business, and skipping them keeps this about the curves.
                continue
            for clip in found.animations:
                clips += 1
                curves += len(model.curves(data, clip))
        assert clips > 1000, clips
        assert curves > 5000, curves

    def test_a_clip_pointing_past_the_file_yields_nothing(self):
        assert not model.curves(bytes(64), model.Clip(name="x", offset=0x9999))


class TestTriangulation:
    """⛔ A fan is only correct for a convex polygon.

    14% of the disc's 4-corner faces are not convex, and fanning one produces a
    bow-tie: two corners open into a triangle crossing the middle of the shape,
    dragging the texture with it. That is how it was reported from the window
    (D223), which is the only way it could have been — the arithmetic all
    checked out.
    """

    def a_concave_quad(self) -> model.Mesh:
        """A dart whose reflex corner is at index **1**.

        ⚠️ The index matters, and getting it wrong makes this test pass
        against a plain fan. A quad has only two diagonals; fanning from
        corner 0 always uses 0-2, which is a *valid* cut whenever the reflex
        corner is 0 or 2. Only a reflex corner at 1 or 3 forces the other
        diagonal, and only then does a fan produce the bow-tie.
        """
        return model.Mesh(
            name="dart",
            positions=[
                (-2.0, -1.0, 0.0),
                (0.0, 0.0, 0.0),
                (2.0, -1.0, 0.0),
                (0.0, 4.0, 0.0),
            ],
            faces=[model.Face(first=0, corners=4)],
            corner_positions=[0, 1, 2, 3],
            corner_normals=[0, 1, 2, 3],
        )

    def test_a_concave_quad_is_not_fanned_across_its_notch(self):
        found = self.a_concave_quad().triangles()
        assert len(found) == 2
        # ⚠️ The fan would give (0,1,2) and (0,2,3). Both contain corner 0 and
        # corner 2, the diagonal that leaves the shape.
        assert not all({0, 2} <= set(t) for t in found), found

    def test_every_triangle_keeps_the_polygon_winding(self):
        mesh = self.a_concave_quad()
        for a, b, c in mesh.triangles():
            first, second, third = (mesh.positions[i] for i in (a, b, c))
            edge = [second[i] - first[i] for i in range(3)]
            other = [third[i] - second[i] for i in range(3)]
            assert edge[0] * other[1] - edge[1] * other[0] > 0, (a, b, c)

    def test_a_convex_quad_still_makes_two_triangles(self):
        mesh = model.Mesh(
            name="square",
            positions=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            faces=[model.Face(first=0, corners=4)],
            corner_positions=[0, 1, 2, 3],
            corner_normals=[0, 1, 2, 3],
        )
        assert len(mesh.triangles()) == 2

    def test_a_zero_area_face_produces_nothing(self):
        """⚠️ 18 of `e_genjin_b`'s 104 triangles were degenerate. They draw no
        pixels and still cost a depth test each."""
        mesh = model.Mesh(
            name="flat",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            faces=[model.Face(first=0, corners=3)],
            corner_positions=[0, 1, 1],
            corner_normals=[0, 0, 0],
        )
        assert mesh.triangles() == []

    def test_no_model_on_the_disc_emits_a_zero_area_triangle(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        checked = 0
        for path in sorted(MODELS.iterdir()):
            if not path.is_file():
                continue
            data = path.read_bytes()
            if not model.is_model(data):
                continue
            try:
                mesh = model.mesh(data)
            except model.ModelError:
                continue
            checked += 1
            for a, b, c in mesh.triangles():
                first, second, third = (mesh.positions[i] for i in (a, b, c))
                edge = [second[i] - first[i] for i in range(3)]
                other = [third[i] - first[i] for i in range(3)]
                cross = (
                    edge[1] * other[2] - edge[2] * other[1],
                    edge[2] * other[0] - edge[0] * other[2],
                    edge[0] * other[1] - edge[1] * other[0],
                )
                assert sum(v * v for v in cross) > 0.0, path.name
        assert checked > 800
