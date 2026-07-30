"""Colour operations on TPL textures, in the CMPR endpoint domain.

⛔ **The load-bearing test is `TestBlockKindIsPreserved`.** DXT1 chooses between
a 4-colour opaque block and a 3-colour-plus-transparent one by comparing the two
endpoints, so a colour map that reorders them silently turns opaque pixels
transparent. `docs/plan-textures.md` says to write this test *before* believing
the endpoint trick works, because the failure is invisible in a byte diff and
subtle on screen.

⚠️ Second is `TestIdentityIsExact`. The whole claim of this approach is that it
never re-compresses, so an identity map must return the input byte for byte. If
that ever fails, rebuilding a mod degrades its textures a generation at a time
and nobody notices until several rebuilds in.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from bleck.formats import tpl

REPO = Path(__file__).resolve().parent.parent
GAME_TEXTURES = REPO / "work" / "extracted" / "eu0" / "files"


HEADER_SIZE = 36
TABLE_AT = 12


def a_tpl(images: list[tuple[int, int, tpl.Format, bytes]]) -> bytes:
    """A minimal but real TPL: header, image table, headers, then pixel data."""
    count = len(images)
    header_at = TABLE_AT + count * 8
    cursor = header_at + count * HEADER_SIZE

    out = bytearray(struct.pack(">III", tpl.TPL_MAGIC, count, TABLE_AT))
    for index in range(count):
        out += struct.pack(">II", header_at + index * HEADER_SIZE, 0)

    for width, height, fmt, payload in images:
        head = bytearray(HEADER_SIZE)
        struct.pack_into(">HHI", head, 0, height, width, int(fmt))
        struct.pack_into(">I", head, 8, cursor)
        out += head
        cursor += len(payload)

    for _width, _height, _fmt, payload in images:
        out += payload
    return bytes(out)


def a_block(c0: int, c1: int, indices: bytes = b"\x1b\x1b\x1b\x1b") -> bytes:
    """One CMPR block: two endpoints, then four bytes of 2-bit indices."""
    return struct.pack(">HH", c0, c1) + indices


class TestReadingAContainer:
    def test_a_constructed_tpl_reads_back(self):
        data = a_tpl([(8, 8, tpl.Format.CMPR, a_block(0xF800, 0x001F) * 4)])
        images = tpl.read(data)
        assert len(images) == 1
        assert images[0].width == 8
        assert images[0].height == 8
        assert images[0].format is tpl.Format.CMPR

    def test_block_count_rounds_up(self):
        """A 6x6 image still needs 2x2 blocks; the hardware pads."""
        image = tpl.Image(0, 6, 6, tpl.Format.CMPR, 0)
        assert image.blocks == 4

    def test_something_that_is_not_a_tpl_is_refused(self):
        with pytest.raises(tpl.TextureError, match="not a TPL"):
            tpl.read(b"NOPE" + b"\x00" * 64)

    def test_an_unknown_format_is_refused_not_skipped(self):
        """⛔ Skipping would make a declared texture edit silently do nothing."""
        data = bytearray(a_tpl([(8, 8, tpl.Format.CMPR, a_block(1, 2) * 4)]))
        head = struct.unpack_from(">I", data, 12)[0]
        struct.pack_into(">I", data, head + 4, 99)
        with pytest.raises(tpl.TextureError, match="format 99"):
            tpl.read(bytes(data))


class TestIdentityIsExact:
    """⚠️ The acceptance test for never re-compressing."""

    def test_identity_returns_the_input_byte_for_byte(self):
        blocks = a_block(0xF800, 0x001F) + a_block(0x07E0, 0xFFFF)
        data = a_tpl([(8, 4, tpl.Format.CMPR, blocks)])
        image = tpl.read(data)[0]
        assert tpl.map_cmpr(data, image, tpl.IDENTITY).data == data

    def test_every_possible_rgb565_value_round_trips(self):
        """⛔ Exhaustive, because a sampled version passed while broken.

        `v * 255 // 31` looks like the obvious 5-to-8-bit expansion and does not
        round trip -- 1 becomes 8, and 8 comes back 0. Constructed fixtures used
        0xF800 and 0x001F, which happen to survive it; a real texture did not
        (D187). All 65,536 is a fifth of a second and admits no such luck.
        """
        broken = [v for v in range(65536) if tpl.pack565(tpl.unpack565(v)) != v]
        assert not broken, f"{len(broken)} values fail, first {broken[:4]}"

    def test_identity_is_recognised_as_such(self):
        assert tpl.IDENTITY.is_identity
        assert not tpl.OPERATIONS["invert"].is_identity
        assert not tpl.brightness(0.5).is_identity

    def test_inverting_twice_returns_the_original(self):
        """Not guaranteed exactly -- RGB565 has 5 and 6 bits, so a round trip
        through 8-bit space can move a channel by one step. Pinned so a change
        in the packing arithmetic is noticed."""
        invert = tpl.OPERATIONS["invert"]
        for value in (0x0000, 0xFFFF, 0xF800, 0x07E0, 0x001F, 0x8410):
            once = tpl.pack565(invert.apply(tpl.unpack565(value)))
            twice = tpl.pack565(invert.apply(tpl.unpack565(once)))
            assert twice == value, f"{value:#06x} -> {once:#06x} -> {twice:#06x}"


class TestBlockKindIsPreserved:
    """⛔ The trap the plan said to test before believing anything.

    `c0 > c1` is a 4-colour opaque block. `c0 <= c1` is 3 colours plus
    transparent. A colour map that reorders the endpoints flips the block
    between the two, and a byte diff looks perfectly reasonable either way.
    """

    def _kinds(self, data: bytes, image: tpl.Image) -> list[bool]:
        return [
            struct.unpack_from(">H", data, image.offset + i * tpl.CMPR_BLOCK)[0]
            > struct.unpack_from(">H", data, image.offset + i * tpl.CMPR_BLOCK + 2)[0]
            for i in range(image.blocks)
        ]

    @pytest.mark.parametrize(
        "operation",
        [
            tpl.OPERATIONS["invert"],
            tpl.OPERATIONS["greyscale"],
            tpl.brightness(0.4),
            tpl.brightness(2.5),
            tpl.tint(tpl.Colour(0x88, 0x00, 0xFF)),
        ],
    )
    def test_no_block_changes_kind(self, operation):
        # Both kinds, and pairs that an invert is guaranteed to reorder.
        blocks = (
            a_block(0xFFFF, 0x0000)  # opaque, extreme
            + a_block(0x0000, 0xFFFF)  # transparent, extreme
            + a_block(0xF800, 0x001F)  # opaque, red over blue
            + a_block(0x001F, 0xF800)  # transparent, blue over red
            + a_block(0x8410, 0x8410)  # equal: transparent by the <= rule
        )
        data = a_tpl([(20, 4, tpl.Format.CMPR, blocks)])
        image = tpl.read(data)[0]
        before = self._kinds(data, image)

        result = tpl.map_cmpr(data, image, operation)

        assert self._kinds(result.data, image) == before, operation.name

    def test_an_invert_really_does_reorder_something(self):
        """⚠️ Guards the guard. If nothing ever needed swapping, the test above
        would pass against code that does no preserving at all."""
        blocks = a_block(0xFFFF, 0x0000) + a_block(0x0000, 0xFFFF)
        data = a_tpl([(8, 4, tpl.Format.CMPR, blocks)])
        image = tpl.read(data)[0]
        result = tpl.map_cmpr(data, image, tpl.OPERATIONS["invert"])
        assert result.reordered == 2

    def test_identity_reorders_nothing(self):
        data = a_tpl([(8, 4, tpl.Format.CMPR, a_block(0xF800, 0x001F) * 2)])
        image = tpl.read(data)[0]
        assert tpl.map_cmpr(data, image, tpl.IDENTITY).reordered == 0


class TestIndicesAreNeverTouched:
    """The other half of the claim: only endpoints move."""

    def test_the_index_bytes_survive_every_operation(self):
        indices = b"\x1b\x4e\x93\xd2"
        data = a_tpl([(4, 4, tpl.Format.CMPR, a_block(0xF800, 0x001F, indices))])
        image = tpl.read(data)[0]
        for operation in (
            tpl.OPERATIONS["invert"],
            tpl.OPERATIONS["greyscale"],
            tpl.tint(tpl.Colour(0, 255, 0)),
        ):
            result = tpl.map_cmpr(data, image, operation)
            assert result.data[image.offset + 4 : image.offset + 8] == indices

    def test_nothing_outside_the_pixel_data_moves(self):
        data = a_tpl([(4, 4, tpl.Format.CMPR, a_block(0xF800, 0x001F))])
        image = tpl.read(data)[0]
        result = tpl.map_cmpr(data, image, tpl.OPERATIONS["invert"])
        assert result.data[: image.offset] == data[: image.offset]
        assert len(result.data) == len(data)


class TestRefusals:
    def test_a_direct_format_image_is_refused_by_the_cmpr_path(self):
        """⛔ Reading endpoints out of RGB5A3 would corrupt it silently."""
        data = a_tpl([(4, 4, tpl.Format.RGB5A3, b"\x00" * 32)])
        image = tpl.read(data)[0]
        with pytest.raises(tpl.TextureError, match="not CMPR"):
            tpl.map_cmpr(data, image, tpl.OPERATIONS["invert"])

    def test_a_truncated_image_is_refused(self):
        data = a_tpl([(64, 64, tpl.Format.CMPR, a_block(1, 2))])
        image = tpl.read(data)[0]
        with pytest.raises(tpl.TextureError, match="ends after"):
            tpl.map_cmpr(data, image, tpl.OPERATIONS["invert"])


@pytest.mark.gamedata
class TestAgainstTheRealDisc:
    """⚠️ Constructed TPLs prove the arithmetic; only the disc proves the parse."""

    def _textures(self) -> list[Path]:
        if not GAME_TEXTURES.is_dir():
            pytest.skip(f"no extracted disc at {GAME_TEXTURES}")
        return sorted(GAME_TEXTURES.rglob("*.tpl"))[:40]

    def test_real_containers_parse(self):
        found = self._textures()
        assert found, "no .tpl files found"
        for path in found:
            images = tpl.read(path.read_bytes())
            assert images, f"{path.name} declared no images"

    def test_identity_is_exact_on_every_real_cmpr_image(self):
        """The acceptance criterion, against real data rather than a fixture."""
        checked = 0
        for path in self._textures():
            data = path.read_bytes()
            for image in tpl.read(data):
                if image.format is not tpl.Format.CMPR:
                    continue
                assert tpl.map_cmpr(data, image, tpl.IDENTITY).data == data
                checked += 1
        assert checked, "no CMPR images were reached, so nothing was proven"

    def test_no_real_image_changes_block_kind_under_invert(self):
        flipped_back = 0
        for path in self._textures():
            data = path.read_bytes()
            for image in tpl.read(data):
                if image.format is not tpl.Format.CMPR:
                    continue
                result = tpl.map_cmpr(data, image, tpl.OPERATIONS["invert"])
                for i in range(image.blocks):
                    at = image.offset + i * tpl.CMPR_BLOCK
                    was = struct.unpack_from(">HH", data, at)
                    now = struct.unpack_from(">HH", result.data, at)
                    assert (was[0] > was[1]) == (now[0] > now[1])
                flipped_back += result.reordered
        assert flipped_back, "no real block needed reordering, so nothing was proven"
