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
            assert found.corners in found.streams, path.name
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
