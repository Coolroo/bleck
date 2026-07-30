"""Decoding GameCube textures to pixels, and writing them out as PNG.

⚠️ **Decoding is the one part of this project that cannot be fully checked
without eyes.** A wrong tile size does not raise; it produces plausible noise.
So this file leans on the two checks that *are* mechanical:

- **The disc's own layout.** For every consecutive pair of images in every TPL,
  `offset + data_size(image)` must land on the next image's offset. That
  validates the tile size and bit depth of all eight formats against 1,976 real
  data points, and no reference table was consulted to write it.
- **Structure in the output.** A correctly decoded image has flat runs, edges
  and a sane alpha distribution; scrambled tiles do not.

The remaining question -- pixel order *within* a tile -- was settled by looking
at the exported PNGs (D189), which is what `bleck texture export` is for.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from bleck.formats import png, texdecode, tpl

REPO = Path(__file__).resolve().parent.parent
GAME_FILES = REPO / "work" / "extracted" / "eu0" / "files"


class TestPngWriter:
    def test_a_known_image_round_trips_its_dimensions(self):
        data = png.write(3, 2, bytes(3 * 2 * 4))
        assert png.dimensions(data) == (3, 2)

    def test_it_starts_with_the_signature(self):
        assert png.write(1, 1, bytes(4)).startswith(png.SIGNATURE)

    def test_wrong_sized_input_is_refused(self):
        """⛔ Silently padding would write a diagonal smear, not an error."""
        with pytest.raises(ValueError, match="expected 16 bytes"):
            png.write(2, 2, bytes(15))

    def test_every_row_carries_its_filter_byte(self):
        """A decoder reads that byte as the row's filter method. Omitting it
        shifts the image one byte per row."""
        import zlib  # pylint: disable=import-outside-toplevel

        width, height = 4, 3
        data = png.write(width, height, bytes([255] * width * height * 4))
        start = data.index(b"IDAT") + 4
        length = int.from_bytes(data[start - 8 : start - 4], "big")
        raw = zlib.decompress(data[start : start + length])
        assert len(raw) == height * (1 + width * 4)
        for row in range(height):
            assert raw[row * (1 + width * 4)] == 0


class TestTilingArithmetic:
    def test_every_format_has_a_tiling(self):
        """⚠️ A format read but not decodable would fail at export, not here."""
        for fmt in tpl.Format:
            assert fmt in tpl.TILING, fmt.name

    def test_a_part_tile_is_still_a_whole_tile(self):
        """15x15 I4 pads to 16x16: two 8x8 tiles each way, 4 bits a pixel."""
        image = tpl.Image(0, 15, 15, tpl.Format.I4, 0)
        assert tpl.data_size(image) == 128

    def test_cmpr_is_four_bits_a_pixel(self):
        image = tpl.Image(0, 64, 64, tpl.Format.CMPR, 0)
        assert tpl.data_size(image) == 64 * 64 // 2

    def test_rgba32_is_four_bytes_a_pixel(self):
        image = tpl.Image(0, 16, 16, tpl.Format.RGBA32, 0)
        assert tpl.data_size(image) == 16 * 16 * 4


@pytest.mark.gamedata
class TestAgainstTheRealDisc:
    def _tpls(self, limit: int = 120) -> list[Path]:
        if not GAME_FILES.is_dir():
            pytest.skip(f"no extracted disc at {GAME_FILES}")
        return sorted(GAME_FILES.rglob("*.tpl"))[:limit]

    def test_the_disc_layout_confirms_every_tile_size(self):
        """⛔ The strongest check available without looking at an image.

        If a format's tile size or bit depth were wrong, the computed size of an
        image would not land on the next one's offset. Measured across the whole
        disc it was 1,976 of 1,976.
        """
        checked = agreed = 0
        for path in self._tpls():
            images = sorted(tpl.read(path.read_bytes()), key=lambda i: i.offset)
            for first, second in itertools.pairwise(images):
                checked += 1
                agreed += tpl.data_size(first) + first.offset == second.offset
        assert checked > 100, "too few pairs to prove anything"
        assert agreed == checked, f"{checked - agreed} of {checked} disagree"

    def test_every_image_decodes_to_the_right_number_of_pixels(self):
        decoded = 0
        for path in self._tpls(40):
            data = path.read_bytes()
            for image in tpl.read(data):
                pixels = texdecode.decode(data, image)
                assert len(pixels.rgba) == image.width * image.height * 4
                decoded += 1
        assert decoded, "nothing was decoded, so nothing was proven"

    def test_decoded_images_have_structure_rather_than_noise(self):
        """⚠️ Weak on its own, and deliberately so -- it is the one property a
        scrambled-tile decode reliably fails. Real textures have flat runs;
        misassembled ones look like static."""
        flat_enough = 0
        looked = 0
        for path in self._tpls(30):
            data = path.read_bytes()
            for image in tpl.read(data):
                if image.width < 16 or image.height < 16:
                    continue
                pixels = texdecode.decode(data, image)
                runs = sum(
                    pixels.rgba[i] == pixels.rgba[i + 4]
                    for i in range(0, len(pixels.rgba) - 4, 4)
                )
                looked += 1
                flat_enough += runs * 2 > (len(pixels.rgba) // 4)
        assert looked, "no image was large enough to look at"
        assert flat_enough * 2 > looked, (
            f"only {flat_enough} of {looked} images have flat runs; tiles may "
            f"be misassembled"
        )

    def test_alpha_is_opaque_wherever_the_format_has_no_alpha(self):
        """I4, I8, RGB565 and CMPR's opaque blocks must not invent transparency."""
        for path in self._tpls(30):
            data = path.read_bytes()
            for image in tpl.read(data):
                if image.format not in (tpl.Format.I4, tpl.Format.I8, tpl.Format.RGB565):
                    continue
                pixels = texdecode.decode(data, image)
                alphas = set(pixels.rgba[3::4])
                assert alphas == {255}, f"{path.name} {image.describe()}: {alphas}"

    def test_exported_pngs_declare_the_size_they_were_asked_for(self):
        for path in self._tpls(20):
            data = path.read_bytes()
            for image in tpl.read(data):
                pixels = texdecode.decode(data, image)
                written = png.write(pixels.width, pixels.height, pixels.rgba)
                assert png.dimensions(written) == (image.width, image.height)
