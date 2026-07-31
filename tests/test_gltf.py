"""The glTF writer, checked structurally rather than by eye.

⚠️ **A `.glb` that opens empty looks exactly like one that opens correctly**
until somebody launches a viewer. So these assert the things a reader actually
depends on: chunk lengths that match, 4-byte alignment, the POSITION accessor's
required `min`/`max`, and indices that stay inside the vertex list.

⛔ **Wavefront OBJ is gone.** It has no skeleton and no keyframe, so animation
could never be expressed in it (D215).
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from bleck.formats import gltf, model

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "work" / "extracted" / "eu0" / "files" / "a"


def a_mesh(textured: bool = True) -> model.Mesh:
    """A square of two triangles, with normals and UVs."""
    positions = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    return model.Mesh(
        name="squareShape",
        positions=positions,
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[model.Face(first=0, corners=4)],
        corner_positions=[0, 1, 2, 3],
        corner_normals=[0, 1, 2, 3],
        corner_uvs=[0, 1, 2, 3] if textured else [],
        uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)] if textured else [],
    )


def parsed(blob: bytes) -> dict:  # pylint: disable=container-return
    """The JSON chunk, as the document a glTF reader would see."""
    length = struct.unpack_from("<I", blob, 12)[0]
    return json.loads(blob[20 : 20 + length])


class TestTheContainer:
    def test_the_header_length_matches_the_file(self):
        blob = gltf.write(a_mesh())
        magic, version, total = struct.unpack_from("<III", blob, 0)
        assert magic == gltf.MAGIC
        assert version == 2
        assert total == len(blob), "a reader trusting this field would run off the end"

    def test_every_chunk_is_four_byte_aligned(self):
        """⚠️ Not cosmetic. Misaligned chunks make the second one unparseable."""
        blob = gltf.write(a_mesh())
        assert len(blob) % 4 == 0
        json_len = struct.unpack_from("<I", blob, 12)[0]
        assert json_len % 4 == 0
        bin_len = struct.unpack_from("<I", blob, 20 + json_len)[0]
        assert bin_len % 4 == 0

    def test_the_json_chunk_is_declared_as_json(self):
        blob = gltf.write(a_mesh())
        assert struct.unpack_from("<I", blob, 16)[0] == gltf.JSON_CHUNK


class TestTheDocument:
    def test_position_carries_min_and_max(self):
        """⚠️ Required by the specification, and viewers frame the camera from
        it — without it a valid file opens looking empty."""
        document = parsed(gltf.write(a_mesh()))
        accessor = document["accessors"][0]
        assert accessor["min"] == [0.0, 0.0, 0.0]
        assert accessor["max"] == [1.0, 1.0, 0.0]

    def test_a_textured_mesh_declares_texcoords(self):
        attributes = parsed(gltf.write(a_mesh()))["meshes"][0]["primitives"][0][
            "attributes"
        ]
        assert set(attributes) == {"POSITION", "NORMAL", "TEXCOORD_0"}

    def test_an_untextured_mesh_declares_none(self):
        attributes = parsed(gltf.write(a_mesh(textured=False)))["meshes"][0][
            "primitives"
        ][0]["attributes"]
        assert "TEXCOORD_0" not in attributes

    def test_a_texture_arrives_only_with_texcoords(self):
        """⚠️ A material sampling a mesh with no UVs renders one flat colour."""
        document = parsed(gltf.write(a_mesh(textured=False), b"not-a-real-png"))
        assert "materials" not in document

    def test_an_embedded_texture_is_masked_and_double_sided(self):
        """Game art is cut out with alpha; OPAQUE renders those pixels black."""
        material = parsed(gltf.write(a_mesh(), b"pretend-png"))["materials"][0]
        assert material["alphaMode"] == "MASK"
        assert material["doubleSided"] is True

    def test_indices_stay_inside_the_vertex_list(self):
        document = parsed(gltf.write(a_mesh()))
        vertices = document["accessors"][0]["count"]
        primitive = document["meshes"][0]["primitives"][0]
        assert document["accessors"][primitive["indices"]]["count"] == 6
        assert vertices <= 6

    def test_an_empty_mesh_is_refused_not_written(self):
        with pytest.raises(ValueError, match="no triangles"):
            gltf.write(model.Mesh(name="empty"))


def attribute(blob, document, name):
    """One vertex attribute read back out of the binary chunk."""
    accessor = document["accessors"][
        document["meshes"][0]["primitives"][0]["attributes"][name]
    ]
    view = document["bufferViews"][accessor["bufferView"]]
    json_len = struct.unpack_from("<I", blob, 12)[0]
    start = 20 + json_len + 8 + view["byteOffset"]
    wide = {"VEC2": 2, "VEC3": 3}[accessor["type"]]
    return [
        struct.unpack_from(f"<{wide}f", blob, start + i * wide * 4)
        for i in range(accessor["count"])
    ]


class TestTexcoordsComeFromTheCorner:
    """⛔ A UV belongs to a **corner**, not to the position the corner names.

    Reading `uvs[corner.position]` looks right and is wrong wherever the two
    streams disagree, which is most of the disc: `e_bara_tib_p` has 64
    positions against 96 UVs (D234). The failure is silent — the model still
    exports, with the art on the wrong triangles.
    """

    def a_split_mesh(self):
        """One triangle whose UV indices are nothing like its position ones."""
        return model.Mesh(
            name="split",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            faces=[model.Face(first=0, corners=3)],
            corner_positions=[0, 1, 2],
            corner_normals=[0, 1, 2],
            corner_uvs=[3, 4, 5],
            uvs=[
                (0.9, 0.9),
                (0.8, 0.8),
                (0.7, 0.7),
                (0.0, 0.0),
                (1.0, 0.0),
                (0.0, 1.0),
            ],
        )

    def test_the_written_uvs_are_the_ones_the_corners_name(self):
        blob = gltf.write(self.a_split_mesh())
        found = attribute(blob, parsed(blob), "TEXCOORD_0")
        assert sorted(found) == [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0)], (
            "the UVs came from the position index, not the corner's own"
        )

    def test_more_uvs_than_positions_still_exports_textured(self):
        """⚠️ The count comparison this replaced dropped the texture here."""
        assert self.a_split_mesh().is_textured
        attributes = parsed(gltf.write(self.a_split_mesh()))["meshes"][0]["primitives"][
            0
        ]["attributes"]
        assert "TEXCOORD_0" in attributes


class TestWelding:
    def test_corners_sharing_a_position_but_not_a_uv_stay_apart(self):
        """⛔ Two corners on a texture seam sit at one point in space and two
        places on the image. Welding them stretches the art across the seam."""
        mesh = model.Mesh(
            name="seam",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[model.Face(first=0, corners=3), model.Face(first=3, corners=3)],
            corner_positions=[0, 1, 2, 0, 1, 2],
            corner_uvs=[0, 1, 2, 3, 4, 5],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)] * 2,
        )
        assert parsed(gltf.write(mesh))["accessors"][0]["count"] == 6

    def test_corners_sharing_a_position_but_not_a_normal_stay_apart(self):
        """⛔ Collapsing them would weld a hard edge into a smooth one."""
        mesh = model.Mesh(
            name="x",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            normals=[(0.0, 0.0, 1.0), (0.0, 1.0, 0.0)],
            faces=[model.Face(first=0, corners=3), model.Face(first=3, corners=3)],
            corner_positions=[0, 1, 2, 0, 1, 2],
            corner_normals=[0, 0, 0, 1, 1, 1],
        )
        assert parsed(gltf.write(mesh))["accessors"][0]["count"] == 6


class TestAgainstTheDisc:
    def test_a_real_model_writes_a_well_formed_file(self):
        path = MODELS / "p_wii_mario"
        if not path.is_file():
            pytest.skip(f"no {path}")
        mesh = model.mesh(path.read_bytes())
        blob = gltf.write(mesh, name="p_wii_mario")
        assert struct.unpack_from("<I", blob, 8)[0] == len(blob)

        document = parsed(blob)
        vertices = document["accessors"][0]["count"]
        assert vertices > 0
        for accessor in document["accessors"]:
            view = document["bufferViews"][accessor["bufferView"]]
            assert (
                view["byteOffset"] + view["byteLength"]
                <= (document["buffers"][0]["byteLength"])
            ), "a buffer view runs past the end of the buffer"


class TestMorphAnimation:
    """Poses written as glTF morph targets, which is what makes a clip play.

    ⛔ **The binding search was the wrong question.** Animation here is not
    skeletal: `animPoseMain` adds per-vertex offsets to a copy of the position
    array, so the target is the vertex list and there is no joint to bind
    (D217). glTF morph targets express exactly that.
    """

    def a_clip(self) -> gltf.Clip:
        return gltf.Clip(
            name="wave",
            poses=[
                model.Morph(time=0.0, offsets=[(0, 1, 0, 0)]),
                model.Morph(time=10.0, offsets=[(0, 0, 2, 0), (2, -1, 0, 0)]),
            ],
        )

    def test_targets_appear_on_the_primitive(self):
        document = parsed(gltf.write(a_mesh(), clips=[self.a_clip()]))
        targets = document["meshes"][0]["primitives"][0]["targets"]
        assert len(targets) == 2
        assert all("POSITION" in t for t in targets)

    def test_the_mesh_declares_a_weight_per_target(self):
        """⚠️ Required: a mesh with targets and no weights is rejected by
        strict readers and silently static in lenient ones."""
        document = parsed(gltf.write(a_mesh(), clips=[self.a_clip()]))
        assert document["meshes"][0]["weights"] == [0.0, 0.0]

    def test_the_animation_drives_weights_on_the_node(self):
        document = parsed(gltf.write(a_mesh(), clips=[self.a_clip()]))
        channel = document["animations"][0]["channels"][0]
        assert channel["target"]["path"] == "weights"
        assert channel["target"]["node"] == 0

    def test_one_weight_per_target_per_keyframe(self):
        """⛔ glTF requires output count == input count * target count. Getting
        this wrong loads without complaint and plays nothing."""
        document = parsed(gltf.write(a_mesh(), clips=[self.a_clip()]))
        sampler = document["animations"][0]["samplers"][0]
        times = document["accessors"][sampler["input"]]["count"]
        weights = document["accessors"][sampler["output"]]["count"]
        targets = len(document["meshes"][0]["primitives"][0]["targets"])
        assert times == 2
        assert weights == times * targets

    def test_a_target_actually_moves_something(self):
        """⚠️ An all-zero target is a valid file that animates nothing."""
        blob = gltf.write(a_mesh(), clips=[self.a_clip()])
        document = parsed(blob)
        accessor = document["accessors"][
            document["meshes"][0]["primitives"][0]["targets"][0]["POSITION"]
        ]
        assert accessor["max"] != [0.0, 0.0, 0.0] or accessor["min"] != [0.0, 0.0, 0.0]

    def test_no_clip_means_no_animation_block(self):
        assert "animations" not in parsed(gltf.write(a_mesh()))

    def test_an_empty_clip_is_not_written_as_an_animation(self):
        document = parsed(gltf.write(a_mesh(), clips=[gltf.Clip(name="none")]))
        assert "animations" not in document


class TestSeveralClips:
    """More than one animation per file, over the one target list glTF allows.

    ⛔ **There is no per-animation target list.** Every clip drives the same
    weights array, so a clip that did not zero the other clips' targets would
    play its own poses *plus* whatever the previous clip left standing.
    """

    def clips(self) -> list:
        return [
            gltf.Clip(
                name="wave",
                poses=[
                    model.Morph(time=0.0, offsets=[(0, 1, 0, 0)]),
                    model.Morph(time=1.0, offsets=[(1, 0, 2, 0)]),
                ],
            ),
            gltf.Clip(name="jump", poses=[model.Morph(time=0.0, offsets=[(2, 0, 0, 3)])]),
        ]

    def test_every_clip_becomes_its_own_named_animation(self):
        document = parsed(gltf.write(a_mesh(), clips=self.clips()))
        assert [a["name"] for a in document["animations"]] == ["wave", "jump"]

    def test_the_clips_share_one_target_list(self):
        document = parsed(gltf.write(a_mesh(), clips=self.clips()))
        targets = document["meshes"][0]["primitives"][0]["targets"]
        assert len(targets) == 3, "two poses plus one, in one list"
        assert document["meshes"][0]["weights"] == [0.0, 0.0, 0.0]

    def test_each_keyframe_weights_every_target_in_the_file(self):
        document = parsed(gltf.write(a_mesh(), clips=self.clips()))
        for animation in document["animations"]:
            sampler = animation["samplers"][0]
            times = document["accessors"][sampler["input"]]["count"]
            weights = document["accessors"][sampler["output"]]["count"]
            assert weights == times * 3

    def test_a_later_clip_drives_its_own_targets_and_zeroes_the_rest(self):
        """⚠️ The off-by-one that would look right: the second clip driving
        target 0 plays the *first* clip's opening pose under its own name."""
        blob = gltf.write(a_mesh(), clips=self.clips())
        document = parsed(blob)
        sampler = document["animations"][1]["samplers"][0]
        weights = _floats(blob, document, sampler["output"])
        assert weights == [0.0, 0.0, 1.0]

    def test_the_first_clip_holds_the_later_ones_at_zero(self):
        blob = gltf.write(a_mesh(), clips=self.clips())
        document = parsed(blob)
        sampler = document["animations"][0]["samplers"][0]
        weights = _floats(blob, document, sampler["output"])
        assert weights == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]

    def test_a_clip_with_no_poses_is_skipped_not_written_empty(self):
        document = parsed(
            gltf.write(a_mesh(), clips=[gltf.Clip(name="empty"), *self.clips()])
        )
        assert [a["name"] for a in document["animations"]] == ["wave", "jump"]


def _floats(blob: bytes, document: dict, accessor: int) -> list:
    """One float accessor's values, read back out of the binary chunk."""
    json_length = struct.unpack_from("<I", blob, 12)[0]
    binary = 20 + json_length + 8
    record = document["accessors"][accessor]
    view = document["bufferViews"][record["bufferView"]]
    at = binary + view["byteOffset"]
    return list(struct.unpack_from(f"<{record['count']}f", blob, at))
