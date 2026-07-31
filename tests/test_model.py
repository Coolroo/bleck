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
