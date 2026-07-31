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
from bleck.formats import gltf, model

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


def a_clip(name: str, poses: int, step: float = 10.0) -> command.ClipInfo:
    """A clip of `poses` morphs, each moving vertex 0 a little further."""
    return command.ClipInfo(
        name=name,
        poses=[
            model.Morph(time=step * index, offsets=[(0, index + 1, 0, 0)])
            for index in range(poses)
        ],
    )


class TestTheAnimationBudget:
    """How many clips a file gets, and what it says about the ones it drops.

    ⚠️ **Silent truncation is the failure this guards.** A model that exported
    3 of its 94 clips with no note reads as a model with 3 animations, and
    nothing downstream could tell the difference.
    """

    def test_the_byte_budget_binds_before_the_target_cap_on_a_big_mesh(self):
        """4,096 vertices is the size `e_3D_manera2` is in; the cap alone would
        give it an 11 MB animation block on a 130 KB mesh."""
        vertices = 4096
        expected = command.MORPH_BUDGET // (vertices * gltf.TARGET_BYTES)
        assert command.budget(vertices) == expected
        assert expected < command.MAX_TARGETS

    def test_the_target_cap_binds_on_a_small_mesh(self):
        assert command.budget(4) == command.MAX_TARGETS

    def test_a_mesh_too_large_to_afford_one_target_gets_none(self):
        assert command.budget(command.MORPH_BUDGET) == 0

    def test_clips_are_kept_in_file_order_until_the_budget_runs_out(self):
        clips = [a_clip(f"c{i}", 100) for i in range(5)]
        written = command.fit_animations(clips, vertices=4)
        assert [clip.name for clip in written.clips] == ["c0", "c1"]
        assert written.dropped == 3
        assert written.targets == 200

    def test_a_clip_too_big_to_fit_does_not_cost_the_shorter_ones_behind_it(self):
        """⚠️ `p_wii_mario` has a 245-pose clip in the middle of 94. Stopping
        at the first clip that does not fit would drop everything after it."""
        clips = [a_clip("huge", command.MAX_TARGETS + 1), a_clip("small", 2)]
        written = command.fit_animations(clips, vertices=4)
        assert [clip.name for clip in written.clips] == ["small"]
        assert written.dropped == 1

    def test_a_clip_with_no_poses_is_neither_written_nor_counted_as_dropped(self):
        written = command.fit_animations([command.ClipInfo(name="still")], vertices=4)
        assert not written.clips
        assert written.dropped == 0

    def test_key_times_are_converted_from_frames_to_seconds(self):
        """glTF's sampler input is seconds; the file counts in frames. A clip
        of 280 frames plays for 4.7 seconds, not 4 minutes 40."""
        clip = a_clip("run", 2, step=280.0)
        assert clip.frames == 280.0
        assert clip.seconds == pytest.approx(280.0 / 60.0)
        assert clip.as_gltf().poses[1].time == pytest.approx(280.0 / 60.0)

    def test_written_is_by_identity_so_a_repeated_name_is_not_confused(self):
        first, second = a_clip("same", 2), a_clip("same", 2)
        written = command.Animations(clips=[first])
        assert written.wrote(first)
        assert not written.wrote(second)


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

    def test_the_manifest_names_the_clips_the_glb_actually_carries(self, tmp_path):
        """⚠️ The two must agree in *order*, not just as sets. The viewer picks
        a clip by index off the manifest and plays that index out of the file;
        a disagreement plays the wrong animation under the right name."""
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        import argparse  # pylint: disable=import-outside-toplevel
        import struct  # pylint: disable=import-outside-toplevel

        args = argparse.Namespace(
            out=str(tmp_path),
            search="p_wii_mario",
            no_textures=True,
            no_animation=False,
            guess_textures=False,
            min_coverage=0.0,
        )
        assert command.cmd_export(args) == 0
        manifest = json.loads((tmp_path / command.MANIFEST).read_text())

        animated = 0
        for entry in manifest["models"]:
            blob = (tmp_path / entry["file"]).read_bytes()
            length = struct.unpack_from("<I", blob, 12)[0]
            document = json.loads(blob[20 : 20 + length])
            promised = [c["name"] for c in entry["clips"] if c["written"]]
            assert promised == [a["name"] for a in document.get("animations", [])]
            assert len(promised) == entry["animations"]
            assert entry["animations_dropped"] == sum(
                1 for c in entry["clips"] if c["poses"] and not c["written"]
            )
            animated += 1 if promised else 0
        assert animated, "no model in this search carried a clip"

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
