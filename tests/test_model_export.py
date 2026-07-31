"""Exporting geometry, and the one mistake that would not look like a mistake.

⚠️ OBJ indices are **1-based**. An off-by-one still produces a file that loads
and renders — as a recognisable model with every face shifted by a vertex. That
is precisely the failure this whole reading has been guarding against, so it is
pinned here rather than left to inspection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bleck.cli.commands import model as command
from bleck.formats import model

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "work" / "extracted" / "eu0" / "files" / "a"


def a_mesh() -> model.Mesh:
    """A square built from two triangles, with vertex 0 at the origin."""
    return model.Mesh(
        name="squareShape",
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[model.Face(first=0, corners=4)],
        corner_positions=[0, 1, 2, 3],
    )


class TestTheObjWriter:
    def test_indices_are_one_based(self):
        text = command.write_obj(a_mesh())
        faces = [line for line in text.splitlines() if line.startswith("f ")]
        assert faces == ["f 1 2 3", "f 1 3 4"]

    def test_no_index_is_zero(self):
        """⚠️ A zero would be silently wrong: OBJ has no vertex 0."""
        for line in command.write_obj(a_mesh()).splitlines():
            if line.startswith("f "):
                assert "0" not in line.split()[1:], line

    def test_a_vertex_line_per_position(self):
        text = command.write_obj(a_mesh())
        assert len([x for x in text.splitlines() if x.startswith("v ")]) == 4

    def test_the_origin_survives_the_round_trip(self):
        """`%.6g` must not turn 0.0 into something a parser rejects."""
        assert "v 0 0 0" in command.write_obj(a_mesh()).splitlines()


class TestAgainstTheDisc:
    def test_a_real_model_exports_indices_in_range(self):
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        mesh = model.mesh(path.read_bytes())
        text = command.write_obj(mesh)
        vertices = len([x for x in text.splitlines() if x.startswith("v ")])
        for line in text.splitlines():
            if not line.startswith("f "):
                continue
            for token in line.split()[1:]:
                assert 1 <= int(token) <= vertices, line

    def test_export_writes_a_manifest_the_viewer_can_read(self, tmp_path):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        import argparse  # pylint: disable=import-outside-toplevel

        args = argparse.Namespace(out=str(tmp_path), search="p_wii_mario")
        assert command.cmd_export(args) == 0

        manifest = json.loads((tmp_path / command.MANIFEST).read_text())
        assert manifest["schema"] == 1
        assert manifest["models"], "the manifest names no models"
        for entry in manifest["models"]:
            assert (tmp_path / entry["file"]).is_file()
            assert entry["triangles"] > 0
            assert len(entry["min"]) == 3 and len(entry["max"]) == 3
            for low, high in zip(entry["min"], entry["max"], strict=True):
                assert low <= high
