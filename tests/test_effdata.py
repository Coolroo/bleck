"""`effdata.dat`, the effect definitions.

⚠️ Most of this file is undecoded, and the tests say so rather than pretending
otherwise. What *is* established rests on two arithmetics agreeing:

- every effect record's `first + count` lands on the next record's `first`
- the total that implies (704) is exactly `section 1 size / 20`

Neither was assumed. A wrong stride would break both, and it would take a
coincidence to break them consistently.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from bleck.formats import effdata

REPO = Path(__file__).resolve().parent.parent
EFFDATA = REPO / "work" / "extracted" / "eu0" / "files" / "eff" / "effdata.dat"


def a_file(effects: list[tuple[str, int, int, int]], parts: list[str]) -> bytes:
    """A minimal effdata.dat: section table, magic, records, parts."""
    header_pad = effdata.EFFECT_STRIDE
    sec0 = effdata.HEADER_SIZE
    sec1 = sec0 + header_pad + len(effects) * effdata.EFFECT_STRIDE

    out = bytearray(effdata.HEADER_SIZE)
    offsets = [sec0, sec1, sec1 + len(parts) * effdata.PART_STRIDE]
    offsets += [offsets[-1]] * (effdata.SECTIONS - len(offsets))
    struct.pack_into(f">{effdata.SECTIONS}I", out, 0, *offsets)

    out += effdata.MAGIC.ljust(header_pad, b"\x00")
    for name, first, count, extra in effects:
        out += name.encode().ljust(effdata.EFFECT_NAME, b"\x00")
        out += struct.pack(">3I", first, count, extra)
    for index, name in enumerate(parts):
        out += name.encode().ljust(effdata.PART_NAME, b"\x00")
        out += struct.pack(">HH", index, 100 + index)
    return bytes(out)


class TestReading:
    def test_effects_carry_their_parts(self):
        data = a_file([("fire", 0, 2, 0), ("smoke", 2, 1, 9)], ["A", "B", "C"])
        effects = effdata.read(data)
        assert [e.name for e in effects] == ["fire", "smoke"]
        assert [p.name for p in effects[0].parts] == ["A", "B"]
        assert [p.name for p in effects[1].parts] == ["C"]

    def test_names_are_composed_the_way_the_game_composes_them(self):
        """⚠️ D172: the whole name never appears on the disc, only the pieces."""
        data = a_file([("chaos", 0, 2, 0)], ["A", "C"])
        assert effdata.read(data)[0].composed() == ["chaosA", "chaosC"]

    def test_something_without_the_magic_is_refused(self):
        data = bytearray(a_file([("fire", 0, 1, 0)], ["A"]))
        data[effdata.HEADER_SIZE : effdata.HEADER_SIZE + 4] = b"NOPE"
        with pytest.raises(effdata.EffectDataError, match="EFDT"):
            effdata.read(bytes(data))

    def test_a_short_file_is_refused(self):
        with pytest.raises(effdata.EffectDataError, match="too short"):
            effdata.read(b"\x00" * 8)


@pytest.mark.gamedata
class TestAgainstTheRealFile:
    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def test_the_record_chain_is_exact(self):
        """⛔ The check the whole reading rests on. 138 of 138."""
        assert effdata.chains_cleanly(effdata.read(self._data()))

    def test_the_part_total_matches_the_section_size(self):
        """The second, independent arithmetic: 704 parts x 20 bytes = 14,080."""
        data = self._data()
        offsets = struct.unpack_from(f">{effdata.SECTIONS}I", data, 0)
        effects = effdata.read(data)
        last = effects[-1]
        implied = last.first_part + last.part_count
        assert implied * effdata.PART_STRIDE == offsets[2] - offsets[1]

    def test_the_effects_we_already_measured_are_here(self):
        """`pure_heart` and `chaos` are D172/D173's effects, found from the DOL
        side. Their part lists are why no whole name appears on the disc."""
        effects = {e.name: e for e in effdata.read(self._data())}
        assert [p.name for p in effects["pure_heart"].parts] == ["A", "B", "C", "D", "E"]
        assert [p.name for p in effects["chaos"].parts] == ["A", "C", "D", "E"]

    def test_there_are_139_effects(self):
        assert len(effdata.read(self._data())) == 139

    def test_the_trailing_field_is_not_a_texture_index(self):
        """🔶 Pinned as a *negative*, so the obvious wrong guess stays refuted.

        `effdata.tpl` holds 219 images; this field reaches 621. Whatever links a
        part to its texture, it is not this.
        """
        parts = [p for e in effdata.read(self._data()) for p in e.parts]
        assert max(p.second for p in parts) > 219
