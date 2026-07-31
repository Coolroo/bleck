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

import struct

import pytest

from bleck.formats import model, modelmat
from tests.test_model import MODELS


def a_painted_model() -> bytes:
    """Two materials, three layers and three shapes that reach them.

    Shape 0 draws with one layer, shape 1 with none, and shape 2 with two — the
    three cases the disc actually contains (18,982 shapes with one layer, 4,319
    with none, 40 with two).
    """
    out = bytearray(0x800)
    layers_at = 0x200
    materials_at = layers_at + 3 * modelmat.LAYER_STRIDE
    records_at = materials_at + 2 * modelmat.MATERIAL_STRIDE
    end = records_at + 3 * modelmat.RECORD_STRIDE
    table = [0x180] * 17 + [layers_at, materials_at, records_at, end]
    struct.pack_into(f">{len(table)}I", out, model.SHAPE_SECTIONS_AT, *table)
    struct.pack_into(">3I", out, modelmat.COUNTS_AT, 3, 2, 3)

    for index, material in enumerate([1, 0, 1]):
        struct.pack_into(">I", out, layers_at + index * modelmat.LAYER_STRIDE, material)
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
