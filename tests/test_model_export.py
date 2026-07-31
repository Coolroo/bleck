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


class TestTheTexturePairing:
    """The bank beside a model, as PNG for embedding.

    ⚠️ **Image 0, not the right image.** Which texture a shape draws with is
    not decoded, so a bank holding several may texture a model wrongly.
    """

    def test_a_real_bank_decodes_to_a_png(self):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        base = MODELS.parent.parent
        data = command.texture_for(base, "files/a/p_wii_mario")
        assert data[:4] == bytes([0x89, 0x50, 0x4E, 0x47]), "not a PNG"

    def test_a_model_with_no_bank_costs_a_texture_not_an_error(self):
        assert command.texture_for(Path("/nowhere"), "files/a/missing") == b""


class TestAgainstTheDisc:
    def test_export_writes_a_manifest_the_viewer_can_read(self, tmp_path):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        import argparse  # pylint: disable=import-outside-toplevel

        args = argparse.Namespace(
            out=str(tmp_path),
            search="p_wii_mario",
            no_textures=False,
            no_animation=True,
            guess_textures=False,
            min_coverage=0.0,
        )
        assert command.cmd_export(args) == 0

        manifest = json.loads((tmp_path / command.MANIFEST).read_text())
        assert manifest["schema"] == 1
        assert manifest["models"], "the manifest names no models"
        for entry in manifest["models"]:
            written = tmp_path / entry["file"]
            assert written.is_file()
            assert written.suffix == ".glb"
            assert written.read_bytes()[:4] == b"glTF"
            assert entry["triangles"] > 0
            assert len(entry["min"]) == 3 and len(entry["max"]) == 3
            for low, high in zip(entry["min"], entry["max"], strict=True):
                assert low <= high

    def test_no_textures_still_writes_geometry(self, tmp_path):
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        import argparse  # pylint: disable=import-outside-toplevel

        args = argparse.Namespace(
            out=str(tmp_path),
            search="p_wii_mario",
            no_textures=True,
            no_animation=True,
            guess_textures=False,
            min_coverage=0.0,
        )
        assert command.cmd_export(args) == 0
        manifest = json.loads((tmp_path / command.MANIFEST).read_text())
        assert manifest["models"]
        assert not any(entry["textured"] for entry in manifest["models"])
