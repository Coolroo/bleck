"""Which image a shape draws with: the layer table, and what pins it.

✅ **The binding is stated by the file** (D243). A shape record counts its
texture layers at `+0x00` and lists them at `+0x10`; each layer resolves through
slot 17 to a slot-18 material record, whose `+0x04` is the image's place in the
TPL bank beside the model and whose `+0x0C` is the source art path.

⛔ **D229 said this was undecoded** and shipped every multi-shape model bare.
The three candidates it refuted — shape *i* to image *i*, slot 17 read as a
per-shape array, and a material index in the face record — all skipped the
indirection, which is why none of them scored above its own control.

⚠️ **Pin the invariants, not the numbers**, for the same reason
`test_model_geometry` does: the counts in this area have already been rewritten
once and the structure is what has to stay true.
"""

from __future__ import annotations

import math
import struct

import pytest

from bleck.formats import model, modelmat
from tests.test_model import MODELS

#: What one layer states about itself: which material, and slot 17 `+0x04`.
LAYERS = ((1, 0), (0, 3), (1, 12))


def a_painted_model() -> bytes:
    """Two materials, three layers and three shapes that reach them.

    Shape 0 draws with one layer, shape 1 with none, and shape 2 with two — the
    three cases the disc actually contains (18,982 shapes with one layer, 4,319
    with none, 40 with two).

    The slot-16 table is real rather than absent, because it is real on all 870
    models and a fixture that skipped it would exercise only the fallback.
    """
    out = bytearray(0x800)
    layers_at = 0x200
    moves_at = layers_at - len(LAYERS) * modelmat.TRANSFORM_STRIDE
    materials_at = layers_at + len(LAYERS) * modelmat.LAYER_STRIDE
    records_at = materials_at + 2 * modelmat.MATERIAL_STRIDE
    end = records_at + 3 * modelmat.RECORD_STRIDE
    table = [0x100] * 16 + [moves_at, layers_at, materials_at, records_at, end]
    struct.pack_into(f">{len(table)}I", out, model.SHAPE_SECTIONS_AT, *table)
    struct.pack_into(">3I", out, modelmat.COUNTS_AT, len(LAYERS), 2, 3)

    for index, (material, wrap) in enumerate(LAYERS):
        at = layers_at + index * modelmat.LAYER_STRIDE
        struct.pack_into(">2i", out, at, material, wrap)
        moved = moves_at + index * modelmat.TRANSFORM_STRIDE
        struct.pack_into(">4f", out, moved + modelmat.TRANSFORM_TRANSLATE_AT, 0, 0, 1, 1)
    for index, path in enumerate([b"art/first.tga", b"art/second.tga"]):
        at = materials_at + index * modelmat.MATERIAL_STRIDE
        struct.pack_into(">I", out, at + modelmat.MATERIAL_IMAGE_AT, index)
        start = at + modelmat.MATERIAL_PATH_AT
        out[start : start + len(path)] = path

    for index, used in enumerate([[0], [], [1, 2]]):
        at = records_at + index * modelmat.RECORD_STRIDE
        struct.pack_into(">I", out, at, len(used))
        slots = used + [modelmat.NO_LAYER] * (modelmat.RECORD_LAYERS - len(used))
        struct.pack_into(">8i", out, at + modelmat.RECORD_LAYERS_FROM, *slots)
    return bytes(out)


class TestTheLayerChain:
    def test_a_shape_reaches_its_own_material(self):
        found = modelmat.read(a_painted_model())
        assert [m.path for m in found.images] == ["art/first.tga", "art/second.tga"]
        assert [b.images for b in found.shapes] == [[1], [], [1, 0]]

    def test_the_layer_list_is_read_in_texture_map_order(self):
        """⚠️ **The file stores it backwards.** The draw loop reads
        `indices[count - i - 1]` and binds it to `GX_TEXMAP` *i*, so the last
        stored layer is map 0 — which is what a `baseColorTexture` wants."""
        found = modelmat.read(a_painted_model())
        assert found.shapes[2].images == [1, 0], (
            "shape 2 lists layers 1 then 2, which name materials 0 then 1; "
            "reading them in file order would put material 0 on map 0"
        )

    def test_a_layer_count_is_not_a_flag(self):
        """⛔ `+0x00` was read as a boolean before D243. Two layers occur — 40
        shapes on the disc — and a reader testing `== 1` called them
        untextured, which cost them their UV corner offset as well."""
        found = modelmat.read(a_painted_model())
        assert [len(b.images) for b in found.shapes] == [1, 0, 2]

    def test_a_file_that_is_not_this_layout_yields_nothing(self):
        """⚠️ Empty rather than an exception. Half of `files/a` is not a model,
        and a caller that got a raise here would lose the geometry too."""
        assert modelmat.read(b"\x00" * 0x800) == modelmat.Palette()
        assert modelmat.read(b"") == modelmat.Palette()

    def test_a_layer_index_past_the_table_drops_the_whole_palette(self):
        """⛔ Not a partial answer: a file that fails here is not this layout,
        so the indices that did resolve would be coincidence."""
        raw = bytearray(a_painted_model())
        table = struct.unpack_from(">21I", raw, model.SHAPE_SECTIONS_AT)
        at = table[19] + modelmat.RECORD_LAYERS_FROM
        struct.pack_into(">i", raw, at, 9)
        assert modelmat.read(bytes(raw)) == modelmat.Palette()

    def test_each_layer_carries_its_own_wrap_mode(self):
        """✅ Slot 17 `+0x04`, decoded per axis (D247). ⛔ It was assumed to be
        REPEAT everywhere, and 92% of the disc's layers clamp instead."""
        found = modelmat.read(a_painted_model())
        assert [layer.wrap for layer in found.shapes[0].layers] == [
            modelmat.Wrap(s=modelmat.CLAMP, t=modelmat.CLAMP)
        ]
        assert [layer.wrap for layer in found.shapes[2].layers] == [
            modelmat.Wrap(s=modelmat.MIRROR, t=modelmat.MIRROR),
            modelmat.Wrap(s=modelmat.REPEAT, t=modelmat.REPEAT),
        ]

    def test_the_transform_table_is_read_beside_the_layer_table(self):
        found = modelmat.read(a_painted_model())
        assert all(
            layer.transform.is_identity
            for binding in found.shapes
            for layer in binding.layers
        )

    def test_a_missing_transform_table_costs_the_transform_not_the_palette(self):
        """⚠️ Slot 16 is `layers * 24` bytes on all 870 models, so nothing on
        the disc takes this path — but refusing a file here would trade a whole
        model's geometry for a UV offset."""
        raw = bytearray(a_painted_model())
        at = model.SHAPE_SECTIONS_AT + modelmat.TRANSFORM_SLOT * 4
        struct.pack_into(">I", raw, at, 0x104)
        found = modelmat.read(bytes(raw))
        assert [b.images for b in found.shapes] == [[1], [], [1, 0]]
        assert found.shapes[0].layers[0].transform == modelmat.Transform()


class TestTheUvTransform:
    """Slot 16's five floats, and the branches the draw code takes over them."""

    def test_the_default_record_composes_to_the_identity(self):
        """⚠️ Asked of the result. The draw code *does* build a translation
        matrix for the default record — `scale_v` is one of the three fields it
        tests — and that matrix is `(0, 0)` because the V term is
        `1 - translate_v - scale_v`."""
        default = modelmat.Transform()
        assert default.shifts, "the translate branch is taken at the defaults"
        assert default.is_identity, "and composes to nothing anyway"

    def test_a_rotation_turns_about_the_middle_of_the_image(self):
        """✅ The middle of the image is the fixed point, for any angle.

        `MTXTrans(0.5, 0.5)` and `MTXTrans(-0.5, -0.5)` bracket the rotation, so
        `(0.5, 0.5)` must come out of the composed transform unmoved. A rotation
        about the corner instead would move it for every angle but a full turn.
        """
        for degrees in (45.0, 61.0, 90.0, 315.0):
            shift = modelmat.Transform(rotation=degrees)
            assert not shift.is_identity
            cos, sin = math.cos(shift.radians), math.sin(shift.radians)
            here_u = cos * 0.5 + sin * 0.5 + shift.offset.u
            here_v = -sin * 0.5 + cos * 0.5 + shift.offset.v
            assert abs(here_u - 0.5) < 1e-9, degrees
            assert abs(here_v - 0.5) < 1e-9, degrees

    def test_a_mirrored_scale_reads_as_one(self):
        """`OFF_doorL` and its three siblings scale U by -1."""
        mirrored = modelmat.Transform(scale_u=-1.0)
        assert mirrored.stretches
        assert mirrored.scale == modelmat.Pair(u=-1.0, v=1.0)
        assert mirrored.offset == modelmat.Pair(u=0.0, v=0.0)


class TestAgainstTheDisc:
    """The checks that make the strides a reading rather than a fit."""

    def _models(self):
        for path in sorted(MODELS.iterdir()):
            if path.name.endswith("-"):
                continue
            data = path.read_bytes()
            if model.is_model(data):
                yield path, data

    def test_every_model_states_its_own_three_counts(self):
        """✅ The header at `0x130` names the layer, material and shape counts,
        and they agree with the section strides on every model. That agreement
        is what says 8, 64 and 108 are the record sizes."""
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        checked = disagreed = 0
        for _, data in self._models():
            edges = struct.unpack_from(">21I", data, model.SHAPE_SECTIONS_AT)
            stated = struct.unpack_from(">3I", data, modelmat.COUNTS_AT)
            spans = (
                (edges[18] - edges[17]) // modelmat.LAYER_STRIDE,
                (edges[19] - edges[18]) // modelmat.MATERIAL_STRIDE,
                (edges[20] - edges[19]) // modelmat.RECORD_STRIDE,
            )
            checked += 1
            disagreed += stated != spans
        assert checked > 800, "the disc should hold hundreds of models"
        assert disagreed == 0, f"{disagreed} of {checked} models disagree with 0x130"

    def test_no_shape_names_an_image_its_bank_does_not_hold(self):
        """⛔ **The invariant.** A bank may carry images nothing references, but
        a material never names one the bank has not got — which is what makes
        `Material.index` a bank index rather than a number that happens to fit.
        """
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        from bleck.formats import tpl  # pylint: disable=import-outside-toplevel

        checked = over = 0
        for path, data in self._models():
            bank = model.bank_for(path)
            palette = modelmat.read(data)
            if not palette.images or not bank.is_file():
                continue
            raw = bank.read_bytes()
            if not tpl.is_tpl(raw):
                continue
            held = len(tpl.read(raw))
            checked += 1
            over += any(image.index >= held for image in palette.images)
        assert checked > 700, "too few pairs checked to mean anything"
        assert over == 0, f"{over} models name an image past the end of their bank"

    def test_every_material_names_source_art(self):
        """✅ The record's `+0x0C` is the exporter's own TGA path, which is what
        `model.TEXTURE_RE` has always been scraping out of the file."""
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        checked = stray = 0
        for _, data in self._models():
            for image in modelmat.read(data).images:
                checked += 1
                stray += not image.path.endswith(".tga")
        assert checked > 5000, "too few materials read to mean anything"
        assert stray == 0, f"{stray} material records do not name a .tga"

    def test_the_transform_table_is_one_record_per_layer_everywhere(self):
        """✅ **What makes slot 16 a reading rather than a fit** (D247). Its span
        is exactly `layers * 24` on every model the disc carries, which is the
        same shape of check `_counts_agree` makes for slots 17, 18 and 19."""
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        checked = ragged = 0
        for _, data in self._models():
            edges = struct.unpack_from(">21I", data, model.SHAPE_SECTIONS_AT)
            layers = (edges[18] - edges[17]) // modelmat.LAYER_STRIDE
            checked += 1
            ragged += (edges[17] - edges[16]) != layers * modelmat.TRANSFORM_STRIDE
        assert checked > 800, "the disc should hold hundreds of models"
        assert ragged == 0, f"{ragged} of {checked} models disagree with slot 16"

    def test_the_disc_clamps_far_more_often_than_it_repeats(self):
        """⛔ **The exporter assumed REPEAT and was wrong about most of them.**

        The point of the assertion is the ordering, not the exact counts: if
        clamping ever stopped being the majority reading, `+0x04` would have
        stopped being decoded rather than the disc having changed.
        """
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        seen = {modelmat.CLAMP: 0, modelmat.REPEAT: 0, modelmat.MIRROR: 0}
        default = 0
        for _, data in self._models():
            for binding in modelmat.read(data).shapes:
                for layer in binding.layers:
                    for mode in (layer.wrap.s, layer.wrap.t):
                        if mode == modelmat.WRAP_DEFAULT:
                            default += 1
                        else:
                            seen[mode] += 1
        assert sum(seen.values()) > 10000, "too few axes read to mean anything"
        assert seen[modelmat.CLAMP] > seen[modelmat.REPEAT] * 2
        assert seen[modelmat.MIRROR], "the mirror bits are used, if barely"
        assert default == 0, (
            f"{default} axes ask for the image's own default; nothing on the "
            "disc did before, so a new one means the flag is being misread"
        )

    def test_most_shapes_are_bound_and_the_rest_say_so(self):
        """⚠️ **A shape draws bare or it does not** — asking per model was the
        mistake D240 recorded. Roughly a quarter of the disc's shapes carry no
        layer at all, and that is the file speaking, not a failed read."""
        if not MODELS.is_dir():
            pytest.skip(f"no extracted disc at {MODELS}")
        shapes = bound = 0
        for _, data in self._models():
            for binding in modelmat.read(data).shapes:
                shapes += 1
                bound += bool(binding.images)
        assert shapes > 15000, "too few shapes read to mean anything"
        assert 0.5 < bound / shapes < 0.95, (
            f"{bound}/{shapes} shapes bound -- a swing this large means the "
            "layer list stopped being read, not that the disc changed"
        )
