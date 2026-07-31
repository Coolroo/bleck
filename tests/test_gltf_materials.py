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
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from bleck.formats import gltf, model, png

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
    return faults


def _primitive_faults(document: dict, at: int, primitive: dict) -> list[str]:
    """One primitive's walk from its material to a texture."""
    textures = document.get("textures", [])
    materials = document.get("materials", [])
    material = primitive.get("material")
    tag = f"primitive[{at}]"
    if material >= len(materials):
        return [f"{tag} names material {material}, out of range"]
    pbr = materials[material].get("pbrMetallicRoughness", {})
    info = pbr.get("baseColorTexture")
    if info is None:
        return [f"{tag} material {material} has no baseColorTexture"]
    faults: list[str] = []
    slot = info.get("texCoord", 0)
    if f"TEXCOORD_{slot}" not in primitive.get("attributes", {}):
        faults.append(f"{tag} samples TEXCOORD_{slot}, which the primitive lacks")
    texture = info.get("index")
    if texture is None or texture >= len(textures):
        faults.append(f"{tag} baseColorTexture does not resolve to a texture")
    return faults


def _reached(document: dict) -> set[int]:
    """Which images some primitive actually arrives at."""
    textures = document.get("textures", [])
    materials = document.get("materials", [])
    found: set[int] = set()
    for mesh in document.get("meshes", []):
        for primitive in mesh["primitives"]:
            material = primitive.get("material")
            if material is None or material >= len(materials):
                continue
            pbr = materials[material].get("pbrMetallicRoughness", {})
            texture = (pbr.get("baseColorTexture") or {}).get("index")
            if texture is not None and texture < len(textures):
                source = textures[texture].get("source")
                if source is not None:
                    found.add(source)
    return found


def chain_faults(loaded: Loaded) -> list[str]:
    """Every break in the primitive-to-image chain, not merely the first."""
    document = loaded.document
    faults = image_faults(loaded) + texture_faults(document)
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
        paints=[gltf.Paint(index=7, png=a_png()), gltf.Paint(index=3, png=a_png(4, 4))],
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
            paints=[gltf.Paint(index=7, png=a_png()), gltf.Paint(index=99, png=a_png())],
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
        blob = gltf.write(bare, paints=[gltf.Paint(index=7, png=a_png())])
        assert gltf.painting(blob).painted == 0
        assert not chain_faults(load(blob))


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


def _cut_document(document: dict, name: str) -> None:
    """Break one link of the chain in the JSON chunk."""
    primitive = document["meshes"][0]["primitives"][0]
    if name == "material index":
        primitive["material"] = 9
    elif name == "baseColorTexture":
        del document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]
    elif name == "texture index":
        document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"] = 9
    elif name == "texture source":
        del document["textures"][0]["source"]
    elif name == "sampler":
        document["samplers"] = []
    elif name == "mimeType":
        del document["images"][0]["mimeType"]
    elif name == "texcoord":
        del primitive["attributes"]["TEXCOORD_0"]
    elif name == "texcoord slot":
        document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"][
            "texCoord"
        ] = 1
    elif name == "image byteStride":
        document["bufferViews"][document["images"][0]["bufferView"]]["byteStride"] = 12
    elif name == "unreachable image":
        for entry in document["meshes"][0]["primitives"]:
            entry.pop("material", None)
    else:
        raise AssertionError(f"no such cut: {name}")


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

    def test_a_model_whose_bank_is_named_rather_than_guessed_is_painted(self):
        """✅ `e_bari_beam` draws from `e__bari_beam-`, with a doubled
        underscore (D245). Guessing the bank from the model's own filename left
        this and 51 others exporting bare."""
        blob = self.a_written_model("e_bari_beam")
        assert gltf.painting(blob).painted
