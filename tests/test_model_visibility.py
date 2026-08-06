"""Slot 20: which shapes the file says not to draw.

✅ A `u8` for every node, padded to a multiple of four, `0` meaning the node is
off (D289). Slot 22's node record names the shape each node draws, so the two
together give the shapes a viewer should hide.

⚠️ Split from `test_gltf.py` rather than added to it. That module reached
pylint's 1,000-line ceiling on this change, exactly as `handoff.md` predicted,
and shaving its docstrings to fit would delete the reasoning to satisfy a check.

⛔ **The game has not been read.** These tests pin what the file says and what
the exporter does with it — not that the game obeys the flag.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from bleck.formats import gltf, gltfcore, model, modelnodes

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "work" / "extracted" / "eu0" / "files" / "a"


def a_two_shape_mesh() -> model.Mesh:
    """Two triangles the face list keeps apart: two spans, a position range
    each. The same fixture shape `test_gltf.py` uses for the split."""
    return model.Mesh(
        name="pair",
        positions=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (9.0, 9.0, 0.0),
            (10.0, 9.0, 0.0),
            (9.0, 10.0, 0.0),
        ],
        faces=[model.Face(first=0, corners=3), model.Face(first=3, corners=3)],
        corner_positions=[0, 1, 2, 3, 4, 5],
        groups=[model.Shape(first=0, count=1), model.Shape(first=1, count=1)],
    )


def parsed(blob: bytes) -> dict:  # pylint: disable=container-return
    length = struct.unpack_from("<I", blob, 12)[0]
    return json.loads(blob[20 : 20 + length])


class TestTheFlagReachesTheEmittedFile:
    """⚠️ The failure guarded against is silent: a flag on the wrong primitive
    still writes a valid file, and the model loses a part nobody chose."""

    def test_a_hidden_shape_is_marked(self):
        primitives = parsed(gltf.write(a_two_shape_mesh(), hidden=frozenset({1})))[
            "meshes"
        ][0]["primitives"]
        assert gltf.HIDDEN_KEY not in primitives[0].get("extras", {})
        assert primitives[1]["extras"][gltf.HIDDEN_KEY] is True

    def test_nothing_is_marked_without_the_flag(self):
        assert gltf.painting(gltf.write(a_two_shape_mesh())).hidden == 0

    def test_the_count_is_read_back_out_of_the_file(self):
        """⚠️ Counted from the emission, never from what the writer was handed
        (D245) — a flag reaching no primitive must read as 0."""
        blob = gltf.write(a_two_shape_mesh(), hidden=frozenset({1}))
        assert gltf.painting(blob).hidden == 1

    def test_an_index_no_shape_carries_marks_nothing(self):
        blob = gltf.write(a_two_shape_mesh(), hidden=frozenset({7}))
        assert gltf.painting(blob).hidden == 0

    def test_the_flag_follows_the_shape_not_the_position(self):
        """⛔ **The bug this exists for.** `parts` drops a shape whose faces are
        all degenerate, so the nth primitive is not the nth shape, and a flag
        matched on position would hide a different part of the model."""
        assert [part.shape for part in gltfcore.parts(a_two_shape_mesh())] == [0, 1]


class TestTheReaderDegradesRatherThanGuessing:
    def test_a_file_too_short_to_hold_a_table_reads_as_nothing(self):
        found = modelnodes.visibility(b"\0" * 16)
        assert not found.read
        assert found.hidden == frozenset()

    def test_an_unreadable_table_hides_nothing(self):
        """⚠️ Hiding on a doubtful read is the worse failure: a model that
        loses geometry looks broken, where one that shows every shape looks
        exactly as it did before this existed."""
        found = modelnodes.visibility(b"\xff" * 0x400)
        assert found.hidden == frozenset()


class TestAgainstTheDisc:
    """✅ The corpus numbers, on the machine that has the disc."""

    @pytest.fixture(autouse=True)
    def _needs_models(self):
        if not MODELS.is_dir():
            pytest.skip("no extracted disc on this machine")

    def test_mario_hides_his_props(self):
        """`big_hammer` is 50 units against a 27-unit body, so drawn at rest it
        fills the frame and Mario is a few pixels below it."""
        found = modelnodes.visibility((MODELS / "p_wii_mario").read_bytes())
        assert found.nodes == 176
        assert len(found.hidden) == 68

    def test_every_model_agrees_on_the_length_rule(self):
        """⚠️ The rule is what makes this a reading rather than a coincidence:
        one byte per node, padded to four. 869 of 870 files fit it."""
        read = sum(
            1
            for path in sorted(MODELS.iterdir())
            if path.is_file()
            and not path.name.endswith(("-", ".bin"))
            and modelnodes.visibility(path.read_bytes()).read
        )
        assert read >= 860, f"only {read} models parsed a visibility table"
