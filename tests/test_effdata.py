"""`effdata.dat`, the effect definitions.

⚠️ Most of this file is undecoded, and the tests say so rather than pretending
otherwise. What *is* established rests on two arithmetics agreeing:

- every effect record's `first + count` lands on the next record's `first`
- the total that implies (704) is exactly `section 1 size / 20`

Neither was assumed. A wrong stride would break both, and it would take a
coincidence to break them consistently.
"""

from __future__ import annotations

import itertools
import math
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


@pytest.mark.gamedata
class TestTransformRows:
    """Section 6: 4,048 rows of four floats, indexed by each effect's `extra`."""

    def _named(self, name: str) -> effdata.Effect:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        found = next(e for e in effdata.read(EFFDATA.read_bytes()) if e.name == name)
        return found

    def _all(self) -> list[effdata.Effect]:  # pylint: disable=container-return
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return effdata.read(EFFDATA.read_bytes())

    def test_chaos_holds_an_exact_72_degree_rotation(self):
        """🟢 360/5, and the Chaos Heart is ringed by *five* hearts (D172, D173).

        Measured from the game, `chaos-heart` orbits five bodies at 72 degrees
        apart. The same angle is sitting in the file, to float32 precision --
        which is what says these rows drive placement rather than being noise
        that happens to look geometric.
        """
        rows = self._named("chaos").rows
        cos72, sin72 = math.cos(math.radians(72)), math.sin(math.radians(72))
        first, second = rows[1].values, rows[2].values
        for got, want in (
            (first[0], cos72),
            (first[1], sin72),
            (second[0], -sin72),
            (second[1], cos72),
        ):
            assert abs(got - want) < 1e-5, f"{got} vs {want}"

    def test_every_row_of_chaos_is_a_unit_vector(self):
        assert all(row.is_unit for row in self._named("chaos").rows)

    def test_a_meaningful_share_of_all_rows_are_unit_vectors(self):
        """⚠️ Weak by design: enough to say the section is geometry, not enough
        to say what any single row means."""
        every = [row for e in self._all() for row in e.rows]
        unit = sum(row.is_unit for row in every)
        assert len(every) > 3000
        assert unit > len(every) // 4

    def test_rows_are_not_grouped_into_3x4_matrices(self):
        """⛔ Pinned as a negative. The obvious reading is three rows per
        transform, and the per-effect counts refute it."""
        counts = [len(e.rows) for e in self._all()]
        assert any(count % 3 for count in counts)


@pytest.mark.gamedata
class TestCurves:
    """Section 10 addresses section 2, and section 2 holds sampled curves."""

    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def test_the_command_list_uses_ten_tags(self):
        commands = effdata.commands(self._data())
        assert len(commands) == 4752
        assert sorted({c.tag for c in commands}) == list(range(10))

    def test_offsets_are_relative_to_section_two_not_absolute(self):
        """⚠️ The measurement that settled it: the largest offset is just under
        section 2's size, and nowhere near the file's."""
        data = self._data()
        offsets = struct.unpack_from(f">{effdata.SECTIONS}I", data, 0)
        section_size = offsets[3] - offsets[2]
        biggest = max(c.offset for c in effdata.commands(data))
        assert biggest < section_size
        assert biggest > section_size * 0.9, "suspiciously far from filling it"

    def test_the_first_curve_is_a_full_rotation(self):
        """🟢 6, 12, 18 ... 360 over 60 samples -- one second at 60 fps."""
        curve = effdata.curve_at(self._data(), 0)
        assert len(curve.samples) == 60
        assert curve.samples[0] == 6.0
        assert curve.samples[-1] == 360.0
        assert curve.is_monotonic

    def test_most_records_are_exactly_as_long_as_they_claim(self):
        """⚠️ Only ~a third, and that is the finding: the rest of the offsets
        point *inside* records, which is what a command list does."""
        data = self._data()
        targets = sorted({c.offset for c in effdata.commands(data)})
        exact = sum(
            1
            for a, b in itertools.pairwise(targets)
            if b - a == effdata.CURVE_HEADER + 4 * len(effdata.curve_at(data, a).samples)
        )
        assert exact > 1000, f"only {exact} records matched their declared size"


@pytest.mark.gamedata
class TestGroupsAndEntries:
    """Sections 7 and 8, which pair: 7 groups 8's records by start and count."""

    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def test_the_group_chain_holds(self):
        """Same start/count shape as the effect records. 2,958 of 2,959.

        ⚠️ Not all of them, and the exceptions are the point: nearly every count
        is 1, so a chain that held perfectly would be indistinguishable from a
        plain sequence. Eight records with a count of 2 are what make it visible.
        """
        groups = effdata.groups(self._data())
        chained = sum(
            1 for a, b in itertools.pairwise(groups) if a.start + a.count == b.start
        )
        assert chained >= len(groups) - 2

    def test_the_group_total_matches_the_entry_count(self):
        """The independent check: what section 7 implies is what section 8 has."""
        data = self._data()
        groups, records = effdata.groups(data), effdata.entries(data)
        last = groups[-1]
        assert max(last.start + last.count, len(groups)) == len(records)

    def test_every_entry_offset_is_a_multiple_of_32(self):
        """⚠️ What says field 3 is a byte offset into a 32-byte-strided table
        rather than an arbitrary number."""
        assert all(e.offset % 32 == 0 for e in effdata.entries(self._data()))

    def test_the_entry_fields_stay_in_their_measured_ranges(self):
        """🔶 Shape only. None of these fields has an established meaning, and
        pinning the ranges is what would make a future change visible."""
        records = effdata.entries(self._data())
        assert len(records) == 2960
        assert max(e.reference for e in records) == 522
        assert len({e.kind for e in records}) == 9
        assert max(e.variant for e in records) == 5
