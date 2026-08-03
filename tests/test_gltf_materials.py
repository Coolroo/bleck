"""The material chain, walked in the bytes the writer produced.

⚠️ **This is the check that was missing when 864 textureless models shipped**
(D245). Every earlier texture test asserted on what the writer was handed or on
one field of the document it built. None of them followed a primitive through
to image bytes, so an export that embedded art no primitive referenced — and an
export that embedded none at all — both read as success.

The walk here is the one a reader performs:

    primitive.material -> materials[m].pbrMetallicRoughness.baseColorTexture
      -> textures[t].source -> images[i].bufferView -> PNG bytes

⚠️ **The walk is itself controlled.** `TestTheWalkCanSeeABrokenChain` cuts each
link in turn and requires a fault, because a checker that cannot tell a good
file from a broken one is not a checker.
"""

from __future__ import annotations

import binascii
import copy
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from bleck.formats import gltf, gltfcore, gltfpaint, model, modelmat, png

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "work" / "extracted" / "eu0" / "files" / "a"

#: The four bytes every PNG opens with, and the three chunks one must carry.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
REQUIRED_CHUNKS = (b"IHDR", b"IDAT", b"IEND")


@dataclass(frozen=True)
class Loaded:
    """A `.glb` split the way a reader splits it: the document and the blob."""

    document: dict = field(default_factory=dict)  # pylint: disable=container-return
    binary: bytes = b""


def load(blob: bytes) -> Loaded:
    """Both chunks of a `.glb`, read out of the bytes rather than the writer."""
    at = 12
    document: dict = {}
    binary = b""
    while at + 8 <= len(blob):
        length, kind = struct.unpack_from("<II", blob, at)
        body = blob[at + 8 : at + 8 + length]
        if kind == gltf.JSON_CHUNK:
            document = json.loads(body)
        elif kind == gltf.BIN_CHUNK:
            binary = body
        at += 8 + length
    return Loaded(document=document, binary=binary)


def png_faults(blob: bytes, label: str) -> list[str]:
    """Whether these bytes are a PNG a decoder will accept.

    ⚠️ **The CRCs are checked, not just the signature.** A truncated or
    mis-sliced image still opens with the right eight bytes, and a reader that
    rejects it drops the texture silently — which looks exactly like a model
    that was never painted.
    """
    if blob[:8] != PNG_MAGIC:
        return [f"{label}: does not open with the PNG signature"]
    found: list[bytes] = []
    faults: list[str] = []
    at = 8
    while at + 12 <= len(blob):
        length, kind = struct.unpack_from(">I4s", blob, at)
        if at + 12 + length > len(blob):
            faults.append(f"{label}: chunk {kind.decode()} runs past the end")
            break
        body = blob[at + 8 : at + 8 + length]
        stored = struct.unpack_from(">I", blob, at + 8 + length)[0]
        if stored != binascii.crc32(kind + body) & 0xFFFFFFFF:
            faults.append(f"{label}: chunk {kind.decode()} has a bad CRC")
        if kind == b"IHDR" and struct.unpack_from(">II", body, 0)[0] == 0:
            faults.append(f"{label}: IHDR declares a zero width")
        found.append(kind)
        at += 12 + length
    if at != len(blob):
        faults.append(f"{label}: the chunk walk ends at {at} of {len(blob)} bytes")
    faults += [
        f"{label}: no {kind.decode()} chunk"
        for kind in REQUIRED_CHUNKS
        if kind not in found
    ]
    return faults


def image_faults(loaded: Loaded) -> list[str]:
    """Each embedded image, from its buffer view down to the pixel bytes."""
    document = loaded.document
    views = document.get("bufferViews", [])
    faults: list[str] = []
    for index, image in enumerate(document.get("images", [])):
        view = image.get("bufferView")
        if view is None:
            faults.append(f"image[{index}] embeds nothing and names no uri")
            continue
        if "mimeType" not in image:
            faults.append(f"image[{index}] embeds a bufferView with no mimeType")
        if view >= len(views):
            faults.append(f"image[{index}] names bufferView {view}, out of range")
            continue
        if "byteStride" in views[view]:
            faults.append(f"image[{index}] bufferView carries a forbidden byteStride")
        start = views[view].get("byteOffset", 0)
        faults += png_faults(
            loaded.binary[start : start + views[view]["byteLength"]], f"image[{index}]"
        )
    return faults


def texture_faults(document: dict) -> list[str]:
    """Each texture's link to an image and to a sampler."""
    images = document.get("images", [])
    samplers = document.get("samplers", [])
    faults: list[str] = []
    for index, texture in enumerate(document.get("textures", [])):
        if texture.get("source") is None or texture["source"] >= len(images):
            faults.append(f"texture[{index}] does not resolve to an image")
        sampler = texture.get("sampler")
        if sampler is not None and sampler >= len(samplers):
            faults.append(f"texture[{index}] names sampler {sampler}, out of range")
    for index, sampler in enumerate(samplers):
        for axis in ("wrapS", "wrapT"):
            mode = sampler.get(axis)
            if mode is not None and mode not in gltfpaint.WRAPPING:
                faults.append(f"sampler[{index}] {axis} is {mode}, not a wrap mode")
    return faults


def _references(material: dict):
    """Every `textureInfo` a material names, base colour and mask alike."""
    pbr = material.get("pbrMetallicRoughness", {})
    if pbr.get("baseColorTexture") is not None:
        yield "baseColorTexture", pbr["baseColorTexture"]
    mask = material.get("extras", {}).get(gltfpaint.MASK_KEY)
    if mask is not None:
        yield gltfpaint.MASK_KEY, mask


def _primitive_faults(document: dict, at: int, primitive: dict) -> list[str]:
    """One primitive's walk from its material to every texture it names."""
    textures = document.get("textures", [])
    materials = document.get("materials", [])
    material = primitive.get("material")
    tag = f"primitive[{at}]"
    if material >= len(materials):
        return [f"{tag} names material {material}, out of range"]
    if (
        materials[material].get("pbrMetallicRoughness", {}).get("baseColorTexture")
        is None
    ):
        return [f"{tag} material {material} has no baseColorTexture"]
    faults: list[str] = []
    for role, info in _references(materials[material]):
        slot = info.get("texCoord", 0)
        if f"TEXCOORD_{slot}" not in primitive.get("attributes", {}):
            faults.append(f"{tag} {role} samples TEXCOORD_{slot}, which it lacks")
        texture = info.get("index")
        if texture is None or texture >= len(textures):
            faults.append(f"{tag} {role} does not resolve to a texture")
    return faults


def _reached(document: dict) -> set[int]:
    """Which images some primitive actually arrives at.

    ⚠️ **Through `extras` as well as through the core chain** (D247). A second
    layer is declared there because glTF has no slot that means "multiply by
    this image's alpha", and an image reachable only that way is still reached.
    """
    textures = document.get("textures", [])
    materials = document.get("materials", [])
    found: set[int] = set()
    for mesh in document.get("meshes", []):
        for primitive in mesh["primitives"]:
            material = primitive.get("material")
            if material is None or material >= len(materials):
                continue
            for _, info in _references(materials[material]):
                texture = info.get("index")
                if texture is None or texture >= len(textures):
                    continue
                source = textures[texture].get("source")
                if source is not None:
                    found.add(source)
    return found


def _extension_faults(document: dict) -> list[str]:
    """`KHR_texture_transform` must be declared where it is used, and only used.

    ⛔ **It must not appear in `extensionsRequired`.** A reader that ignores it
    draws the untransformed texture, which is what every reader did before D247
    and is strictly better than refusing the file.
    """
    used = set(document.get("extensionsUsed", []))
    faults = [
        f"{name} is required, so a reader that ignores it must refuse the file"
        for name in document.get("extensionsRequired", [])
    ]
    for index, material in enumerate(document.get("materials", [])):
        for role, info in _references(material):
            for name in info.get("extensions", {}):
                if name not in used:
                    faults.append(
                        f"material[{index}] {role} uses {name}, undeclared in "
                        f"extensionsUsed"
                    )
    return faults


def chain_faults(loaded: Loaded) -> list[str]:
    """Every break in the primitive-to-image chain, not merely the first."""
    document = loaded.document
    faults = image_faults(loaded) + texture_faults(document) + _extension_faults(document)
    for mesh in document.get("meshes", []):
        for at, primitive in enumerate(mesh["primitives"]):
            if primitive.get("material") is not None:
                faults += _primitive_faults(document, at, primitive)
    reached = _reached(document)
    return faults + [
        f"image[{index}] is embedded but no primitive reaches it"
        for index in range(len(document.get("images", [])))
        if index not in reached
    ]


def masked_primitives(document: dict) -> int:
    """How many shapes draw with a material carrying a second layer.

    ⚠️ **Not the material count.** `MOBJ_EFF_mahojin_omote` has 19 two-layer
    shapes over 4 masked materials, so counting materials would report 4 where
    D243 counted 19.
    """
    masked = {
        index
        for index, material in enumerate(document.get("materials", []))
        if gltfpaint.MASK_KEY in material.get("extras", {})
    }
    return sum(
        1
        for mesh in document.get("meshes", [])
        for primitive in mesh["primitives"]
        if primitive.get("material") in masked
    )


def a_png(width: int = 2, height: int = 2) -> bytes:
    """A small opaque red image, written the way the exporter writes one."""
    return png.write(width, height, bytes([255, 0, 0, 255]) * width * height)


def a_painted_mesh() -> model.Mesh:
    """Two shapes with UVs, the first drawing image 7 and the second image 3."""
    return model.Mesh(
        name="pairShape",
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
        corner_uvs=[0, 1, 2, 0, 1, 2],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        groups=[
            model.Shape(first=0, count=1, textures=[7]),
            model.Shape(first=1, count=1, textures=[3]),
        ],
    )


def a_painted_file() -> bytes:
    """The mesh above, written with both images it names."""
    return gltf.write(
        a_painted_mesh(),
        paints=[
            gltfcore.Paint(index=7, png=a_png()),
            gltfcore.Paint(index=3, png=a_png(4, 4)),
        ],
    )


class TestTheEmittedChainResolves:
    """✅ The claim, made against the file: a reader finds an image."""

    def test_every_primitive_walks_through_to_valid_png_bytes(self):
        assert not chain_faults(load(a_painted_file()))

    def test_both_shapes_are_painted_and_with_different_images(self):
        """⚠️ Two shapes resolving to *one* material is the failure that looks
        like success: the model renders, wearing the wrong art (D243)."""
        document = load(a_painted_file()).document
        chosen = [p["material"] for p in document["meshes"][0]["primitives"]]
        assert len(chosen) == 2
        assert len(set(chosen)) == 2

    def test_the_file_reports_what_it_carries(self):
        painted = gltf.painting(a_painted_file())
        assert painted.primitives == 2
        assert painted.painted == 2
        assert painted.images == 2
        assert painted.textured

    def test_an_image_no_shape_names_is_not_embedded(self):
        """⛔ **Not merely wasted bytes** (D245). Ten models embedded art
        nothing referenced, and the manifest counted every one as textured
        while each opened bare in a viewer."""
        blob = gltf.write(
            a_painted_mesh(),
            paints=[
                gltfcore.Paint(index=7, png=a_png()),
                gltfcore.Paint(index=99, png=a_png()),
            ],
        )
        assert gltf.painting(blob).images == 1
        assert not chain_faults(load(blob))

    def test_a_shape_with_no_usable_uv_is_left_unpainted(self):
        """A `baseColorTexture` with no `TEXCOORD_0` samples nothing and draws
        black, so no material is better than a broken one."""
        mesh = a_painted_mesh()
        bare = model.Mesh(
            name=mesh.name,
            positions=mesh.positions,
            faces=mesh.faces,
            corner_positions=mesh.corner_positions,
            groups=mesh.groups,
        )
        blob = gltf.write(bare, paints=[gltfcore.Paint(index=7, png=a_png())])
        assert gltf.painting(blob).painted == 0
        assert not chain_faults(load(blob))


def a_layer(
    material: int, flag: int = 0, transform: modelmat.Transform | None = None
) -> modelmat.Layer:
    """One layer as `modelmat.read` would hand it over."""
    return modelmat.Layer(
        material=material,
        wrap=modelmat.Wrap.of(flag),
        transform=transform or modelmat.Transform(),
    )


def a_layered_file(first: list, second: list) -> bytes:
    """`a_painted_mesh`'s two shapes, each drawing the layers given."""
    mesh = a_painted_mesh()
    layered = model.Mesh(
        name=mesh.name,
        positions=mesh.positions,
        faces=mesh.faces,
        corner_positions=mesh.corner_positions,
        corner_uvs=mesh.corner_uvs,
        uvs=mesh.uvs,
        groups=[
            model.Shape(first=0, count=1, textures=first),
            model.Shape(first=1, count=1, textures=second),
        ],
    )
    wanted = sorted({layer.material for layer in first + second})
    return gltf.write(
        layered, paints=[gltfcore.Paint(index=at, png=a_png()) for at in wanted]
    )


class TestWrapModeReachesTheFile:
    """✅ Read from slot 17 `+0x04`, not assumed (D247)."""

    def test_each_axis_gets_the_mode_the_layer_states(self):
        """The four values the disc carries, plus the mirror bits it barely does."""
        cases = {
            0: (gltfpaint.CLAMP_TO_EDGE, gltfpaint.CLAMP_TO_EDGE),
            1: (gltfpaint.REPEAT, gltfpaint.CLAMP_TO_EDGE),
            2: (gltfpaint.CLAMP_TO_EDGE, gltfpaint.REPEAT),
            3: (gltfpaint.REPEAT, gltfpaint.REPEAT),
            12: (gltfpaint.MIRRORED_REPEAT, gltfpaint.MIRRORED_REPEAT),
        }
        for flag, (wrap_s, wrap_t) in cases.items():
            document = load(a_layered_file([a_layer(7, flag)], [a_layer(7, flag)]))
            sampler = document.document["samplers"][0]
            assert (sampler["wrapS"], sampler["wrapT"]) == (wrap_s, wrap_t), flag

    def test_two_shapes_wrapping_one_image_differently_get_two_samplers(self):
        """⚠️ **Deduplicated on the whole reference, not on the image.** Keying
        a material on its picture alone would give both shapes whichever mode
        was written first, and nothing downstream could tell."""
        document = load(a_layered_file([a_layer(7, 0)], [a_layer(7, 3)])).document
        assert len(document["images"]) == 1, "one picture, embedded once"
        assert len(document["samplers"]) == 2
        assert len(document["textures"]) == 2
        assert len({p["material"] for p in document["meshes"][0]["primitives"]}) == 2

    def test_a_negative_flag_falls_back_rather_than_writing_a_bad_enum(self):
        """`GXInitTexObj` keeps the image's own default there and glTF has no
        way to say that. ⚠️ Nothing on the disc is negative, so this pins the
        behaviour of a branch the corpus cannot exercise."""
        assert modelmat.Wrap.of(-1) == modelmat.Wrap(
            s=modelmat.WRAP_DEFAULT, t=modelmat.WRAP_DEFAULT
        )
        surface = gltfpaint.surface_of(a_layer(7, -1))
        assert surface.wrap_s == gltfpaint.REPEAT
        assert surface.wrap_t == gltfpaint.REPEAT


class TestTheSecondLayerIsAMask:
    """✅ Two layers is the base times the mask's alpha, and no core glTF slot
    means that (D247)."""

    def _masked(self) -> Loaded:
        return load(a_layered_file([a_layer(7), a_layer(3)], [a_layer(3)]))

    def test_the_base_layer_is_texture_map_zero(self):
        """⚠️ The layer list is stored backwards and `modelmat` already reverses
        it, so entry 0 is what supplies the colour."""
        document = self._masked().document
        first = document["meshes"][0]["primitives"][0]["material"]
        base = document["materials"][first]["pbrMetallicRoughness"]["baseColorTexture"]
        assert document["textures"][base["index"]]["source"] == 0

    def test_the_mask_is_declared_and_reachable(self):
        document = self._masked().document
        first = document["meshes"][0]["primitives"][0]["material"]
        mask = document["materials"][first]["extras"][gltfpaint.MASK_KEY]
        assert (
            mask["index"]
            != document["materials"][first]["pbrMetallicRoughness"]["baseColorTexture"][
                "index"
            ]
        )
        assert not chain_faults(
            load(a_layered_file([a_layer(7), a_layer(3)], [a_layer(3)]))
        )

    def test_the_mask_samples_a_uv_set_the_primitive_carries(self):
        """⛔ **The class of bug D245 caught.** A `texCoord` a primitive does
        not have samples nothing; every layer on the disc reads UV channel 0,
        which the shape record states at `+0x30`."""
        document = self._masked().document
        for material in document["materials"]:
            for _, info in _references(material):
                assert info.get("texCoord", 0) == 0

    def test_a_file_with_no_second_layer_declares_no_mask(self):
        document = load(a_painted_file()).document
        assert all("extras" not in m for m in document["materials"])
        assert gltf.painting(a_painted_file()).masked == 0

    def test_the_manifest_counts_masks_from_the_bytes(self):
        painted = gltf.painting(a_layered_file([a_layer(7), a_layer(3)], [a_layer(3)]))
        assert painted.images == 2
        assert painted.materials == 2
        assert painted.masked == 1


class TestTheUvTransformSurvivesTheRoundTrip:
    """✅ Slot 16's five floats, as `KHR_texture_transform` (D247)."""

    def test_an_identity_record_writes_no_extension(self):
        """⚠️ Asked of the composed matrix, not of the branches the draw code
        takes. The default record builds a translation matrix that happens to
        be the identity, and 7,170 layers carry it."""
        assert modelmat.Transform().is_identity
        document = load(a_painted_file()).document
        assert "extensionsUsed" not in document

    def test_a_mirrored_scale_reaches_the_material(self):
        """`OFF_doorL` scales U by -1, which is how one door faces the other."""
        mirrored = modelmat.Transform(scale_u=-1.0)
        document = load(
            a_layered_file([a_layer(7, 0, mirrored)], [a_layer(7, 0, mirrored)])
        ).document
        assert document["extensionsUsed"] == [gltfpaint.TRANSFORM_EXTENSION]
        info = document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]
        moved = info["extensions"][gltfpaint.TRANSFORM_EXTENSION]
        assert moved["scale"] == [-1.0, 1.0]
        assert moved["offset"] == [0.0, 0.0]


def game_matrix(shift: modelmat.Transform) -> list:
    """The 2x3 matrix the draw code composes, built the way the draw code does.

    `MTXConcat(a, b, ab)` is `ab = a * b`, disassembled and confirmed; the three
    factors are rotate, translate and scale, and only the rotation is bracketed
    by the half-unit shift to the middle of the image.
    """
    made = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

    def times(left, right):
        rows = [left[0], left[1], [0.0, 0.0, 1.0]]
        columns = [right[0], right[1], [0.0, 0.0, 1.0]]
        return [
            [sum(rows[r][k] * columns[k][c] for k in range(3)) for c in range(3)]
            for r in range(2)
        ]

    if shift.turns:
        angle = -math.radians(shift.rotation)
        cos, sin = math.cos(angle), math.sin(angle)
        made = times(made, [[1.0, 0.0, 0.5], [0.0, 1.0, 0.5]])
        made = times(made, [[cos, -sin, 0.0], [sin, cos, 0.0]])
        made = times(made, [[1.0, 0.0, -0.5], [0.0, 1.0, -0.5]])
    if shift.shifts:
        across = shift.translate_u
        down = 1.0 - shift.translate_v - shift.scale_v
        made = times(made, [[1.0, 0.0, across], [0.0, 1.0, down]])
    if shift.stretches:
        made = times(made, [[shift.scale_u, 0.0, 0.0], [0.0, shift.scale_v, 0.0]])
    return made


def khr_matrix(shift: modelmat.Transform) -> list:
    """The same transform as `KHR_texture_transform` defines it: `T * R * S`."""
    cos, sin = math.cos(shift.radians), math.sin(shift.radians)
    return [
        [
            cos * shift.scale.u,
            sin * shift.scale.v,
            shift.offset.u,
        ],
        [
            -sin * shift.scale.u,
            cos * shift.scale.v,
            shift.offset.v,
        ],
    ]


class TestTheKhrFormIsTheGamesMatrix:
    """⚠️ **The equivalence is arithmetic, so it is checked as arithmetic.**

    Nobody here can look at a rotated texture, and "it looked right" is what
    D245 was about. What *can* be settled without eyes is whether the extension
    form and the game's own composition move a coordinate to the same place —
    so both are built and compared over a grid.
    """

    CASES = (
        modelmat.Transform(),
        modelmat.Transform(rotation=45.0),
        modelmat.Transform(rotation=61.0),
        modelmat.Transform(rotation=360.0),
        modelmat.Transform(rotation=315.0),
        modelmat.Transform(translate_u=-2.5),
        modelmat.Transform(translate_u=-1.0),
        modelmat.Transform(scale_u=-1.0),
        modelmat.Transform(translate_u=0.25, translate_v=0.5, rotation=30.0),
        modelmat.Transform(scale_u=2.0, scale_v=0.5, rotation=30.0, translate_u=0.1),
    )

    @pytest.mark.parametrize("shift", CASES)
    def test_both_forms_move_a_coordinate_to_the_same_place(self, shift):
        mine, theirs = game_matrix(shift), khr_matrix(shift)
        for u in (0.0, 0.25, 0.5, 1.0, 2.0, -0.75):
            for v in (0.0, 0.25, 0.5, 1.0, 2.0, -0.75):
                for row in range(2):
                    want = mine[row][0] * u + mine[row][1] * v + mine[row][2]
                    got = theirs[row][0] * u + theirs[row][1] * v + theirs[row][2]
                    assert abs(want - got) < 1e-6, f"{shift} at ({u}, {v})"

    def test_the_control_can_tell_the_two_apart(self):
        """⛔ A comparison that passes on a wrong answer proves nothing. Flip the
        rotation's sign and the grid must disagree."""
        shift = modelmat.Transform(rotation=45.0)
        theirs = khr_matrix(modelmat.Transform(rotation=-45.0))
        mine = game_matrix(shift)
        assert any(
            abs(
                (mine[row][0] * u + mine[row][1] * v + mine[row][2])
                - (theirs[row][0] * u + theirs[row][1] * v + theirs[row][2])
            )
            > 1e-6
            for u in (0.25, 1.0)
            for v in (0.25, 1.0)
            for row in range(2)
        )


#: The two cuts that damage the blob rather than the document.
BINARY_CUTS = ("png bytes", "png truncated")


def _cut_binary(document: dict, binary: bytes, name: str) -> bytes:
    """Break the image bytes themselves, leaving the document intact."""
    view = document["bufferViews"][document["images"][0]["bufferView"]]
    if name == "png truncated":
        view["byteLength"] -= 20
        return binary
    start = view["byteOffset"]
    return binary[:start] + b"notapng!" + binary[start + 8 :]


def _unpaint(document: dict) -> None:
    """Leave every primitive bare, so the embedded image is unreachable."""
    for primitive in document["meshes"][0]["primitives"]:
        primitive.pop("material", None)


def _cut_document(document: dict, name: str) -> None:
    """Break one link of the chain in the JSON chunk.

    A table rather than a chain of branches: sixteen cuts is more `elif` than a
    reader holds, and every one of them is a single edit to one place.
    """
    base = document["materials"][0]["pbrMetallicRoughness"]
    primitive = document["meshes"][0]["primitives"][0]
    cuts = {
        "material index": lambda: primitive.update(material=9),
        "baseColorTexture": lambda: base.pop("baseColorTexture"),
        "texture index": lambda: base["baseColorTexture"].update(index=9),
        "texture source": lambda: document["textures"][0].pop("source"),
        "sampler": lambda: document.update(samplers=[]),
        "mimeType": lambda: document["images"][0].pop("mimeType"),
        "texcoord": lambda: primitive["attributes"].pop("TEXCOORD_0"),
        "texcoord slot": lambda: base["baseColorTexture"].update(texCoord=1),
        "image byteStride": lambda: document["bufferViews"][
            document["images"][0]["bufferView"]
        ].update(byteStride=12),
        "unreachable image": lambda: _unpaint(document),
        "wrap mode": lambda: document["samplers"][0].update(wrapS=12345),
        "mask index": lambda: document["materials"][0].update(
            extras={gltfpaint.MASK_KEY: {"index": 9}}
        ),
        "mask texcoord": lambda: document["materials"][0].update(
            extras={gltfpaint.MASK_KEY: {"index": 0, "texCoord": 1}}
        ),
        "undeclared extension": lambda: base["baseColorTexture"].update(
            extensions={gltfpaint.TRANSFORM_EXTENSION: {"rotation": 1.0}}
        ),
        "required extension": lambda: document.update(
            extensionsRequired=[gltfpaint.TRANSFORM_EXTENSION]
        ),
    }
    if name not in cuts:
        raise AssertionError(f"no such cut: {name}")
    cuts[name]()


def cut(name: str) -> Loaded:
    """The good file with one link of the chain broken."""
    loaded = load(a_painted_file())
    document = copy.deepcopy(loaded.document)
    if name in BINARY_CUTS:
        return Loaded(
            document=document, binary=_cut_binary(document, loaded.binary, name)
        )
    _cut_document(document, name)
    return Loaded(document=document, binary=loaded.binary)


class TestTheWalkCanSeeABrokenChain:
    """⚠️ **The control on the instrument** — the rule the repo has burned four
    decision-log entries on. A walk that passes everything proves nothing, so
    each link is cut in turn and a fault is required."""

    CUTS = (
        "material index",
        "baseColorTexture",
        "texture index",
        "texture source",
        "sampler",
        "mimeType",
        "texcoord",
        "texcoord slot",
        "image byteStride",
        "png bytes",
        "png truncated",
        "unreachable image",
        "wrap mode",
        "mask index",
        "mask texcoord",
        "undeclared extension",
        "required extension",
    )

    def test_the_intact_file_is_clean(self):
        assert not chain_faults(load(a_painted_file()))

    @pytest.mark.parametrize("name", CUTS)
    def test_cutting_a_link_is_seen(self, name: str):
        assert chain_faults(cut(name)), f"cutting {name!r} went unnoticed"


class TestAgainstTheDisc:
    """The two models a person opened in Blender and found bare (D245)."""

    NAMES = ("e_lui_robo", "p_wii_mario")

    def a_written_model(self, name: str) -> bytes:
        path = MODELS / name
        if not path.is_file():
            pytest.skip(f"no {path}")
        data = path.read_bytes()
        mesh = model.mesh(data)
        base = MODELS.parent.parent
        # pylint: disable=import-outside-toplevel
        from bleck.cli.commands import model as command

        paints = command.textures_for(base, f"files/a/{name}", mesh)
        return gltf.write(mesh, name=name, paints=paints)

    @pytest.mark.parametrize("name", NAMES)
    def test_a_real_model_exports_with_a_resolvable_material(self, name: str):
        blob = self.a_written_model(name)
        painted = gltf.painting(blob)
        assert painted.images, f"{name} embedded no image"
        assert painted.painted, f"{name} painted no primitive"
        assert not chain_faults(load(blob))

    #: The four models that carry the disc's 40 two-layer shapes (D243).
    TWO_LAYER = (
        "MOBJ_EFF_mahojin_omote",
        "MOBJ_EFF_mahojin_ura",
        "MOBJ_EFF_queen_tornade",
        "MOBJ_EFF_uranoko",
    )

    @pytest.mark.parametrize("name", TWO_LAYER)
    def test_a_two_layer_model_exports_its_mask(self, name: str):
        """✅ The 40 shapes D246 left drawing their first layer only (D247)."""
        blob = self.a_written_model(name)
        loaded = load(blob)
        assert gltf.painting(blob).masked, f"{name} declared no mask"
        assert masked_primitives(loaded.document), f"{name} draws no masked shape"
        assert not chain_faults(loaded)

    def test_a_masks_image_is_not_the_one_it_masks(self):
        """⛔ The failure that would look like success: a mask resolving to the
        base layer multiplies a texture by its own alpha and still renders."""
        document = load(self.a_written_model("MOBJ_EFF_uranoko")).document
        for material in document["materials"]:
            mask = material.get("extras", {}).get(gltfpaint.MASK_KEY)
            if mask is None:
                continue
            base = material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
            assert (
                document["textures"][mask["index"]]["source"]
                != (document["textures"][base]["source"])
            )

    def test_the_whole_corpus_stays_structurally_clean(self):
        """Every model on the disc, walked in its own emitted bytes.

        ⚠️ **The count is asserted as a floor, not pinned.** What matters is
        that nothing regresses to zero faults by exporting nothing.
        """
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        # pylint: disable=import-outside-toplevel
        from bleck.cli.commands import model as command

        base = MODELS.parent.parent
        looked = wrapped = masked = faults = 0
        for path in sorted(MODELS.iterdir()):
            if path.name.endswith("-") or path.suffix == ".bin":
                continue
            data = path.read_bytes()
            if not model.is_model(data):
                continue
            try:
                mesh = model.mesh(data)
            except model.ModelError:
                continue
            paints = command.textures_for(base, f"files/a/{path.name}", mesh)
            try:
                blob = gltf.write(mesh, name=path.name, paints=paints)
            except ValueError:
                continue
            looked += 1
            loaded = load(blob)
            faults += len(chain_faults(loaded))
            masked += masked_primitives(loaded.document)
            wrapped += any(
                sampler["wrapS"] != gltfpaint.REPEAT
                or sampler["wrapT"] != gltfpaint.REPEAT
                for sampler in loaded.document.get("samplers", [])
            )
        assert looked > 800, "too few models written to mean anything"
        assert faults == 0, f"{faults} structural faults across {looked} models"
        assert masked == 40, (
            f"{masked} shapes export a mask; the disc carries exactly 40 "
            "two-layer shapes (D243)"
        )
        assert wrapped > 600, (
            f"only {wrapped} of {looked} models sample anything other than "
            "REPEAT; the wrap flag has stopped being read"
        )

    def test_a_model_whose_bank_is_named_rather_than_guessed_is_painted(self):
        """✅ `e_bari_beam` draws from `e__bari_beam-`, with a doubled
        underscore (D245). Guessing the bank from the model's own filename left
        this and 51 others exporting bare."""
        blob = self.a_written_model("e_bari_beam")
        assert gltf.painting(blob).painted
