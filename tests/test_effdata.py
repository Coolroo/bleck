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
from dataclasses import dataclass
from pathlib import Path

import pytest

from bleck.formats import effcurve, effdata, effgeom, effnode, effsections

REPO = Path(__file__).resolve().parent.parent
EFFDATA = REPO / "work" / "extracted" / "eu0" / "files" / "eff" / "effdata.dat"


def a_file(effects: list[tuple[str, int, int, int]], parts: list[str]) -> bytes:
    """A minimal effdata.dat: section table, magic, records, parts."""
    header_pad = effdata.EFFECT_STRIDE
    sec0 = effdata.HEADER_SIZE
    sec1 = sec0 + header_pad + len(effects) * effdata.EFFECT_STRIDE

    out = bytearray(effdata.HEADER_SIZE)
    offsets = [sec0, sec1, sec1 + len(parts) * effdata.PART_STRIDE]
    offsets += [offsets[-1]] * (effsections.SECTIONS - len(offsets))
    struct.pack_into(f">{effsections.SECTIONS}I", out, 0, *offsets)

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
        offsets = struct.unpack_from(f">{effsections.SECTIONS}I", data, 0)
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
class TestSectionSix:
    """⛔ `Row` is deleted (D270). What replaced it is `Transform`, and its
    tests live in `TestTheNodeTransforms` — section 6 is 1,349 3x4 matrices
    reached from a node's `+0x06`, not four-float rows sliced by an effect.

    ⚠️ **The 72-degree finding survives the deletion.** D172/D173 measured a
    five-fold ring in game and the same angle was in these floats; that is
    still true, and is now read as part of a real matrix rather than as a row
    grouped under an effect that never owned it.
    """

    def test_the_old_row_view_is_gone(self):
        """A refuted reading that keeps shipping is the trap D252 recorded."""
        assert not hasattr(effdata, "Row")
        assert not hasattr(effdata, "TRANSFORM_SECTION")
        effects = effdata.read(EFFDATA.read_bytes()) if EFFDATA.is_file() else []
        if effects:
            assert not hasattr(effects[0], "rows")


@pytest.mark.gamedata
class TestCurves:
    """Section 10 addresses section 2, and section 2 holds sampled curves."""

    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def test_the_command_list_uses_ten_tags(self):
        commands = effnode.commands(self._data())
        assert len(commands) == 4752
        assert sorted({c.tag for c in commands}) == list(range(10))

    def test_offsets_are_relative_to_section_two_not_absolute(self):
        """⚠️ The measurement that settled it: the largest offset is just under
        section 2's size, and nowhere near the file's."""
        data = self._data()
        offsets = struct.unpack_from(f">{effsections.SECTIONS}I", data, 0)
        section_size = offsets[3] - offsets[2]
        biggest = max(c.offset for c in effnode.commands(data))
        assert biggest < section_size
        assert biggest > section_size * 0.9, "suspiciously far from filling it"

    def test_the_first_curve_is_a_full_rotation(self):
        """🟢 6, 12, 18 ... 360 over 60 samples -- one second at 60 fps, and a
        curve whose values *are* degrees, which is what the rotation slots want.

        ⚠️ The sample count is `end - start + 1`, not a field. Reading `+0x06`
        as a count is the superseded layout (D266).
        """
        curve = effcurve.curve_at(self._data(), 0)
        assert (curve.start, curve.end) == (1, 60)
        assert len(curve.samples) == 60
        assert curve.samples[0] == 6.0
        assert curve.samples[-1] == 360.0
        assert all(b >= a for a, b in itertools.pairwise(curve.samples))

    def test_a_curve_reads_the_way_the_games_evaluator_reads_it(self):
        """✅ The header the code at `0x8005f2d4` loads, field for field."""
        curve = effcurve.curve_at(self._data(), 0)
        assert curve.length > 0
        assert curve.byte_samples == effcurve.CURVE_FLOAT
        # Before the first frame it says nothing, so the node keeps its own
        # static value -- which is not the same as saying zero.
        assert curve.value_at(float(curve.start)) == 6.0
        assert curve.value_at(float(curve.end)) == 360.0
        # ⚠️ Past the end it holds, rather than wrapping or vanishing.
        assert curve.value_at(float(curve.end) + 5.0) == 360.0

    def test_most_records_are_exactly_as_long_as_they_claim(self):
        """⚠️ Only ~a third, and that is the finding: the rest of the offsets
        point *inside* records, which is what a command list does."""
        data = self._data()
        targets = sorted({c.offset for c in effnode.commands(data)})
        exact = sum(
            1
            for a, b in itertools.pairwise(targets)
            if b - a
            == effcurve.CURVE_HEADER + 4 * len(effcurve.curve_at(data, a).samples)
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

    def test_every_display_list_offset_is_aligned_and_inside_section_3(self):
        """⚠️ The 32 is GX display-list alignment, not a record stride.

        Reading it as a stride is what made the old four-`u16` layout look
        right: an offset divisible by 32 is equally consistent with both, and
        only the *upper* one distinguishes them. As two `u16` the offset tops
        out at 64,960; as one `u32` it reaches 350,944, and section 3 is
        350,976 bytes long — which the two-`u16` reading could never fill.
        """
        data = self._data()
        offsets = struct.unpack_from(f">{effsections.SECTIONS}I", data, 0)
        size = offsets[effgeom.DISPLAY_SECTION + 1] - offsets[effgeom.DISPLAY_SECTION]
        records = effdata.entries(data)
        assert all(e.display_list % effgeom.DISPLAY_ALIGN == 0 for e in records)
        assert all(0 <= e.display_list < size for e in records)
        assert max(e.display_list for e in records) > 0xFFFF

    def test_the_entry_fields_stay_in_their_measured_ranges(self):
        """The three fields of a draw, pinned at what the file holds."""
        records = effdata.entries(self._data())
        assert len(records) == 2960
        assert max(e.material for e in records) == 522
        assert len({e.descriptor for e in records}) == 9
        # ⚠️ Bit 15 aside, no descriptor names an attribute past TEX0 — which
        # is what lets `ATTRIBUTE_SECTIONS` cover four bits and stop.
        assert all(
            e.descriptor & effgeom.DESCRIPTOR_ATTRIBUTES <= 0b1111 for e in records
        )

    def test_the_translucent_bit_is_surfaced_rather_than_only_masked_away(self):
        """✅ Bit 15 asks for alpha blending (D283), and 211 entries set it.

        ⚠️ **Both readings of the same bit have to hold at once.** The attribute
        mask must still discard it or every vertex mis-strides, and the flag
        must still be readable or the blend derivation loses its only per-draw
        input. Masking alone is what hid it from D263.
        """
        records = effdata.entries(self._data())
        assert sum(1 for e in records if e.translucent) == 211
        assert effgeom.DESCRIPTOR_ATTRIBUTES & effgeom.DESCRIPTOR_TRANSLUCENT == 0
        marked = [e for e in records if e.translucent]
        assert {e.descriptor for e in marked} == {0x8005, 0x8007, 0x800D}
        # ⚠️ The control: the same descriptors without bit 15 exist in the file
        # and must read as ordinary draws, or this is testing the value and not
        # the bit.
        assert all(
            not e.translucent for e in records if e.descriptor in (0x0005, 0x0007, 0x000D)
        )

    def test_the_translucent_bit_does_not_change_how_a_vertex_is_read(self):
        """⛔ The mask stays. A display list read under `0x8009` and under
        `0x0009` is the same geometry: bit 15 takes no index, so leaving it in
        reads two bytes too many per vertex and swallows the next opcode."""
        data = self._data()
        entry = next(e for e in effdata.entries(data) if e.translucent)
        plain = effgeom.mesh_at(
            data, entry.display_list, entry.descriptor & effgeom.DESCRIPTOR_ATTRIBUTES
        )
        marked = effgeom.mesh_at(data, entry.display_list, entry.descriptor)
        assert marked.triangles() == plain.triangles()
        assert marked.strays == 0 and len(marked.primitives) > 0


@pytest.mark.gamedata
class TestTheHeader:
    """The two fields `effSubMain` reads after checking the magic (D201)."""

    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def test_the_texture_count_matches_the_tpl_beside_it(self):
        """🟢 The one hard constraint on the texture-index search.

        The game reads a `u16` at EFDT+0x28 and keeps it at `effsub_wp+0x14`.
        It is 219, and `effdata.tpl` holds exactly 219 images -- which is what
        says any texture index in this file is bounded by that, and why five
        candidate fields reaching 522, 621 and 64,960 are refuted.
        """
        from bleck.formats import tpl  # pylint: disable=import-outside-toplevel

        beside = EFFDATA.with_suffix(".tpl")
        if not beside.is_file():
            pytest.skip("no effdata.tpl beside effdata.dat")
        head = effdata.header(self._data())
        assert head.texture_count == len(tpl.read(beside.read_bytes()))

    def test_the_version_is_two(self):
        assert effdata.header(self._data()).version == 2

    def test_the_records_start_where_the_header_ends(self):
        """⚠️ `EFFECT_STRIDE` doubles as the EFDT block's size, and that is not
        a coincidence worth leaving unstated: the first record name sits at
        +0x2C, immediately past the field the loader reads last."""
        data = self._data()
        offsets = struct.unpack_from(f">{effsections.SECTIONS}I", data, 0)
        first = offsets[0] + effdata.EFFECT_STRIDE
        assert data[first : first + 9] == b"3D_switch"
        assert effdata.EFFECT_STRIDE > effdata.TEXTURE_COUNT_AT


class TestPartDuration:
    """`Part.second` is a frame count, and the evidence is its arithmetic.

    ⚠️ It was twice mistaken for a texture index. What settles it is that the
    values cluster on whole seconds at 60 Hz -- 61, 121, 181 -- which no
    index into a 219-image bank would do (D210).
    """

    def test_durations_land_on_whole_seconds(self):
        path = EFFDATA
        if not path.is_file():
            pytest.skip(f"no {path}")
        parts = [p for e in effdata.read(path.read_bytes()) for p in e.parts]
        assert len(parts) > 500
        whole = sum(1 for p in parts if p.second % 60 == 1)
        assert whole / len(parts) > 0.4, f"only {whole}/{len(parts)} on a second"

    def test_seconds_reads_inclusively(self):
        assert effdata.Part(0, "x", 0, 61).seconds == pytest.approx(1.0)
        assert effdata.Part(0, "x", 0, 121).seconds == pytest.approx(2.0)
        assert effdata.Part(0, "x", 0, 0).seconds == 0.0

    def test_first_is_not_a_texture_index(self):
        """⛔ Pins the refutation so it is not re-proposed a seventh time."""
        path = EFFDATA
        if not path.is_file():
            pytest.skip(f"no {path}")
        for effect in effdata.read(path.read_bytes()):
            if len(effect.parts) >= 3:
                run = [p.first for p in effect.parts[:3]]
                assert run == [run[0], run[0] + 1, run[0] + 2], effect.name
                break


@dataclass(frozen=True)
class Drawn:
    """One part of one effect, and the images it resolves to."""

    effect: str
    part: str
    images: list


@pytest.mark.gamedata
class TestTheImageChain:
    """The five hops from a part to an `effdata.tpl` image (D258).

    ⚠️ Every assertion here is a **bound the file states about itself**, not a
    number copied out of the research that found the chain. Seven earlier
    candidates were all "in range"; what separates this one is that it covers
    the bank exactly and leaves nothing over.
    """

    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def _resolved(self, data: bytes) -> list[Drawn]:
        # pylint: disable=container-return
        return [
            Drawn(
                effect=effect.name,
                part=part.name,
                images=[p.image for p in effdata.artwork(data, effect, part)],
            )
            for effect in effdata.read(data)
            for part in effect.parts
        ]

    def test_every_image_index_is_inside_the_count_the_game_reads(self):
        """The bound that refuted five candidates reaching 522, 621 and 64,960."""
        data = self._data()
        limit = effdata.header(data).texture_count
        assert limit == 219
        for row in self._resolved(data):
            for image in row.images:
                assert 0 <= image < limit, f"{row.effect}{row.part} reached image {image}"

    def test_the_chain_covers_the_bank_exactly_and_orphans_nothing(self):
        """⛔ The discriminating statistic. Being *in range* is cheap -- six
        other offsets at this stride are too, because they are mostly zero.
        Referencing all 219 and no more is not."""
        data = self._data()
        limit = effdata.header(data).texture_count
        seen = {image for row in self._resolved(data) for image in row.images}
        assert seen == set(range(limit))

    def test_a_part_that_draws_nothing_says_so_rather_than_failing_to_walk(self):
        """⚠️ The distinction that matters: 35 parts resolve to no image because
        their materials carry the documented -1, **not** because the traversal
        gave up. A walk that silently found nothing would look identical here,
        so the count is pinned."""
        data = self._data()
        resolved = self._resolved(data)
        assert len(resolved) == 704
        assert sum(1 for row in resolved if not row.images) == 35

    def test_parts_named_after_their_own_textures_land_on_them(self):
        """✅ Semantic ground truth, and the only kind available here.

        `system`'s parts are named for the textures they draw, so the file
        states the answer twice -- once in a name and once through five hops of
        indices -- and the two agree. 216 and 217 are noise fields, 218 a plain
        white square.
        """
        found = {
            (row.effect, row.part): row.images for row in self._resolved(self._data())
        }
        assert found[("system", "IndTexture0")] == [216]
        assert found[("system", "IndTexture2")] == [217]
        assert found[("system", "ClipTexture0")] == [218]

    def test_the_seven_score_digits_share_one_digit_sheet(self):
        """A second independent check: `mini_totalscore` draws a seven-digit
        number, and its seven digit parts all reach the same 0-9 sheet."""
        found = {
            (row.effect, row.part): row.images
            for row in self._resolved(self._data())
            if row.effect == "mini_totalscore"
        }
        digits = [found[("mini_totalscore", f"C{n}")] for n in range(1, 8)]
        assert digits == [[202]] * 7

    def test_a_null_part_reference_resolves_to_nothing(self):
        """0xFFFF is the null, and it must not be walked as node 65,535."""
        data = self._data()
        effects = effdata.read(data)
        empty = effdata.Part(index=0, name="none", first=effdata.NO_PART, second=1)
        assert not effdata.artwork(data, effects[0], empty)


def a_display_list(fans: list[list[int]], attributes: int) -> bytes:
    """One section 3 record: a `u32` size, padding to 32, then triangle fans.

    `fans` gives each primitive's vertex indices; every attribute of a vertex
    takes the same index, which is what makes a test's expected geometry
    readable at a glance.
    """
    body = bytearray()
    for fan in fans:
        body += struct.pack(">BH", effgeom.TRIANGLE_FAN, len(fan))
        for index in fan:
            body += struct.pack(f">{attributes}H", *([index] * attributes))
    record = bytearray(struct.pack(">I", len(body)))
    record += b"\x00" * (effgeom.DISPLAY_ALIGN - len(record))
    record += body
    # ⚠️ The trailing pad matters: a reader that runs past the declared size
    # must stop on the zero rather than read it as an opcode.
    record += b"\x00" * ((-len(record)) % effgeom.DISPLAY_ALIGN)
    return bytes(record)


def a_geometry_file(fans: list[list[int]], descriptor: int) -> bytes:
    """A file holding one display list and the arrays it indexes.

    Position `n` is `(n, 10n, 100n)` and texture coordinate `n` is `(n, -n)`,
    so an index resolved against the wrong section produces a number no
    assertion here would accept.
    """
    mask = effgeom.DESCRIPTOR_ATTRIBUTES
    bits = [b for b in range(15) if descriptor & mask & (1 << b)]
    count = max((i for fan in fans for i in fan), default=0) + 1

    blocks = {
        3: a_display_list(fans, len(bits)),
        11: b"".join(struct.pack(">2f", float(n), float(-n)) for n in range(count)),
        13: b"".join(struct.pack(">3h", n, 10 * n, 100 * n) for n in range(count)),
        14: b"".join(struct.pack(">3b", 127, 0, 0) for _ in range(count)),
        15: b"".join(struct.pack(">4B", n, n, n, 255) for n in range(count)),
    }

    offsets, cursor = [], effdata.HEADER_SIZE
    for section in range(effsections.SECTIONS):
        offsets.append(cursor)
        cursor += len(blocks.get(section, b""))
    out = bytearray(struct.pack(f">{effsections.SECTIONS}I", *offsets))
    for section in range(effsections.SECTIONS):
        out += blocks.get(section, b"")
    return bytes(out)


class TestTheDisplayListReader:
    """`mesh_at`, without a disc. Every array holds a different pattern, so a
    misresolved attribute cannot pass by looking plausible."""

    def test_a_fan_becomes_triangles_sharing_its_first_vertex(self):
        data = a_geometry_file([[0, 1, 2, 3]], 0b1001)
        mesh = effgeom.mesh_at(data, 0, 0b1001)
        assert len(mesh.primitives) == 1
        assert mesh.primitives[0].kind == effgeom.TRIANGLE_FAN
        assert len(mesh.primitives[0].vertices) == 4

        triangles = mesh.triangles()
        assert len(triangles) == 2, "a 4-vertex fan is two triangles"
        assert [(t.a.x, t.b.x, t.c.x) for t in triangles] == [(0, 1, 2), (0, 2, 3)]

    def test_each_descriptor_bit_reads_its_own_array(self):
        """⚠️ The shape of the check that caught the normal stride: every array
        holds a different pattern, so resolving one against another's stride
        gives a value none of these assertions accepts."""
        data = a_geometry_file([[0, 1, 2]], 0b1111)
        vertex = effgeom.mesh_at(data, 0, 0b1111).primitives[0].vertices[2]
        assert (vertex.x, vertex.y, vertex.z) == (2, 20, 200)
        assert (vertex.u, vertex.v) == (2.0, -2.0)
        assert (vertex.nx, vertex.ny, vertex.nz) == (1.0, 0.0, 0.0)
        assert (vertex.red, vertex.green, vertex.blue, vertex.alpha) == (2, 2, 2, 255)

    def test_an_absent_attribute_keeps_a_default_that_does_not_erase_the_art(self):
        """⚠️ White, not black. A vertex colour is modulated against the
        texture, so a zeroed default would black out every untinted draw — and
        2,494 of the file's 2,960 draws name no colour at all."""
        data = a_geometry_file([[0, 1, 2]], 0b1001)
        vertex = effgeom.mesh_at(data, 0, 0b1001).primitives[0].vertices[1]
        assert (vertex.red, vertex.green, vertex.blue, vertex.alpha) == (255,) * 4
        assert (vertex.nx, vertex.ny, vertex.nz) == (0.0, 0.0, 0.0)
        assert (vertex.x, vertex.u) == (1, 1.0)

    def test_the_stride_follows_the_descriptor_rather_than_being_assumed(self):
        """⛔ The 275-of-360 bug in miniature. Bytes holding four attributes,
        read as two, run the reader into the middle of a vertex — so it must
        not report the same geometry as the right descriptor does."""
        four = a_geometry_file([[0, 1, 2, 3], [1, 2, 3, 0]], 0b1111)
        right = effgeom.mesh_at(four, 0, 0b1111)
        assert len(right.primitives) == 2
        assert len(right.triangles()) == 4
        assert len(effgeom.mesh_at(four, 0, 0b1001).triangles()) != 4

    def test_bit_15_takes_no_index(self):
        """✅ It is a flag, not an attribute. Counting it stretches the stride
        by two bytes a vertex and swallows the following opcode."""
        data = a_geometry_file([[0, 1, 2, 3]], 0b1001)
        plain = effgeom.mesh_at(data, 0, 0b1001)
        flagged = effgeom.mesh_at(data, 0, 0x8000 | 0b1001)
        assert len(flagged.triangles()) == len(plain.triangles()) == 2
        assert flagged.triangles()[0].a.x == plain.triangles()[0].a.x

    def test_a_truncated_file_returns_what_it_read_rather_than_raising(self):
        """A damaged `effdata.dat` is not a reason to refuse the 359 display
        lists around the damaged one."""
        data = a_geometry_file([[0, 1, 2, 3], [0, 1, 2]], 0b1001)
        mesh = effgeom.mesh_at(data[: len(data) - 40], 0, 0b1001)
        assert len(mesh.primitives) <= 2

    def test_an_offset_past_the_section_gives_an_empty_mesh(self):
        data = a_geometry_file([[0, 1, 2]], 0b1001)
        assert not effgeom.mesh_at(data, 1 << 20, 0b1001).primitives

    def test_a_descriptor_naming_nothing_gives_an_empty_mesh(self):
        """⚠️ A zero stride would loop forever on a fan of any length."""
        data = a_geometry_file([[0, 1, 2]], 0b1001)
        assert not effgeom.mesh_at(data, 0, 0).primitives

    def test_a_primitive_kind_the_file_never_uses_is_not_triangulated(self):
        """⛔ Fan triangulation applied to a strip produces geometry that
        renders and is wrong. Better to draw nothing."""
        corners = [effgeom.Vertex(x=n) for n in range(4)]
        assert not effgeom.Primitive(0x98, corners).triangles()
        assert len(effgeom.Primitive(effgeom.TRIANGLE_FAN, corners).triangles()) == 2


@pytest.mark.gamedata
class TestTheGeometryAgainstTheRealFile:
    """D263 and D264, re-measured. Every number here was a claim first."""

    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def _offsets(self, data: bytes) -> list[int]:
        # pylint: disable=container-return
        """The section table, with the file's own end appended — section 15 has
        no following offset to bound it."""
        table = struct.unpack_from(f">{effsections.SECTIONS}I", data, 0)
        return [*table, len(data)]

    def test_every_display_list_parses_exactly(self):
        """✅ 360 of 360, 14,648 primitives, 58,381 vertices.

        ⛔ **The near-miss is the danger.** Ignoring the descriptor parses 275
        — three quarters, including the effect that was under examination, with
        the failures confined to effects nobody had opened. Pinning the totals
        is what makes that a visible regression rather than a plausible result.
        """
        shared = effdata.meshes(self._data())
        assert len(shared) == 360
        assert sum(len(m.primitives) for m in shared) == 14648
        assert sum(len(p.vertices) for m in shared for p in m.primitives) == 58381
        assert all(m.primitives for m in shared), "a display list read as empty"

    def test_a_display_list_consumes_its_size_with_only_padding_left_over(self):
        """⛔ The discriminating check. A wrong stride still parses *something*
        — it stops short of the declared size or overruns it, and a reader that
        only counts primitives cannot tell the difference."""
        data = self._data()
        start = self._offsets(data)[effgeom.DISPLAY_SECTION]
        mask = effgeom.DESCRIPTOR_ATTRIBUTES
        for mesh in effdata.meshes(data):
            base = start + mesh.offset
            size = struct.unpack_from(">I", data, base)[0]
            stride = 2 * bin(mesh.descriptor & mask).count("1")
            read = sum(3 + len(p.vertices) * stride for p in mesh.primitives)
            assert read <= size, f"{mesh.offset:#x} overran its declared size"
            body = base + effgeom.DISPLAY_ALIGN
            trailing = data[body + read : body + size]
            assert set(trailing) <= {0}, f"{mesh.offset:#x} left {len(trailing)} unread"

    def test_no_index_ever_falls_outside_the_array_its_bit_names(self):
        """⛔ **The test that refuted D263's normal stride**, and the reason
        `Mesh.strays` exists at all.

        An out-of-range index is not a crash — the attribute keeps its default
        and the geometry parses, renders and looks fine, one attribute short.
        Under the assumed stride-6 reading of section 14 this counted 4,598.
        Zero is the only acceptable answer, and it has to be *counted* to be
        seen.
        """
        shared = effdata.meshes(self._data())
        assert sum(m.strays for m in shared) == 0
        assert any(m.descriptor & (1 << 1) for m in shared), (
            "no display list used a normal, so this proves nothing"
        )

    def test_section_14_divides_by_three_and_not_by_six(self):
        """⛔ The arithmetic underneath it. 4,896 is 1,632 x 3 exactly; at the
        stride-6 reading it would hold 816 normals, and vertices index up to
        1,631."""
        offsets = self._offsets(self._data())
        size = offsets[effgeom.NORMAL_SECTION + 1] - offsets[effgeom.NORMAL_SECTION]
        assert size == 4896
        assert size % effgeom.NORMAL_STRIDE == 0
        assert size // effgeom.NORMAL_STRIDE == 1632

    def test_the_arrays_are_padded_rather_than_ending_on_an_exact_entry(self):
        """⚠️ Not every section divides by its stride, so "it divides exactly"
        is the wrong test to reach for. Section 13 carries **four spare bytes**
        past its 12,250th position — which is why the fit argument below is
        stated in entries, not in bytes."""
        offsets = self._offsets(self._data())
        leftover = {
            section: (offsets[section + 1] - offsets[section]) % stride
            for section, stride in (
                (effgeom.POSITION_SECTION, effgeom.POSITION_STRIDE),
                (effgeom.NORMAL_SECTION, effgeom.NORMAL_STRIDE),
                (effgeom.COLOUR_SECTION, effgeom.COLOUR_STRIDE),
                (effgeom.TEXCOORD_SECTION, effgeom.TEXCOORD_STRIDE),
            )
        }
        assert leftover == {
            effgeom.POSITION_SECTION: 4,
            effgeom.NORMAL_SECTION: 0,
            effgeom.COLOUR_SECTION: 0,
            effgeom.TEXCOORD_SECTION: 0,
        }

    def test_the_position_and_texcoord_arrays_are_filled_to_within_two_entries(self):
        """🟢 The fit that settles the assignment, and the reason it is not
        merely GX convention: POS's largest index is 12,247 against 12,250
        entries and TEX0's is 9,065 against 9,068 — two spare each, where the
        next-best candidate section leaves thousands."""
        data = self._data()
        offsets = self._offsets(data)
        held = {
            effgeom.POSITION_SECTION: effgeom.POSITION_STRIDE,
            effgeom.TEXCOORD_SECTION: effgeom.TEXCOORD_STRIDE,
        }
        counts = {
            section: (offsets[section + 1] - offsets[section]) // stride
            for section, stride in held.items()
        }
        assert counts == {effgeom.POSITION_SECTION: 12250, effgeom.TEXCOORD_SECTION: 9068}

    def test_every_normal_is_a_unit_vector(self):
        """✅ 1,632 of 1,632, which is what says section 14 is `3 x s8`.

        ⚠️ The refuted reading also looked convincing: at stride 6 as `3 x s16`,
        738 of 816 come out unit-length against 1/32767 — 90%, purely from
        where the bytes happen to fall.
        """
        data = self._data()
        offsets = self._offsets(data)
        start = offsets[effgeom.NORMAL_SECTION]
        size = offsets[effgeom.NORMAL_SECTION + 1] - start
        count = size // effgeom.NORMAL_STRIDE
        assert count == 1632

        for n in range(count):
            at = start + n * effgeom.NORMAL_STRIDE
            x, y, z = struct.unpack_from(">3b", data, at)
            length = math.sqrt(x * x + y * y + z * z) / effgeom.NORMAL_SCALE
            assert abs(length - 1.0) < 0.05, f"normal {n} has length {length}"

    def test_dimentios_star_is_four_quads_meeting_at_the_origin(self):
        """🟢 The acceptance test, against a gameplay screenshot (D262, D263).

        `dmen_magic`'s draws point at one display list holding four 320-unit
        quads that meet at the origin, every one carrying the same inset
        texture rect. One concave quadrant mirrored per cell is the
        four-pointed star with concave sides the screenshot shows.
        """
        data = self._data()
        effects = {e.name: e for e in effdata.read(data)}
        magic = effects["dmen_magic"]

        found = [d for part in magic.parts for d in effdata.draws(data, magic, part)]
        star = [d for d in found if d.offset == 0x001C80]
        assert star, f"no draw at 0x001C80 among {sorted({d.offset for d in found})}"
        assert {d.descriptor for d in star} == {0x0009}, "position and texcoord"

        mesh = effgeom.mesh_at(data, 0x001C80, 0x0009)
        assert len(mesh.primitives) == 4
        assert all(len(p.vertices) == 4 for p in mesh.primitives)

        corners = {(v.x, v.y, v.z) for p in mesh.primitives for v in p.vertices}
        grid = {(x, y, 0) for x in (-320, 0, 320) for y in (-320, 0, 320)}
        assert corners == grid, "a 2x2 block of 320-unit cells around the origin"

        centre = [1 for p in mesh.primitives if any(v.x == v.y == 0 for v in p.vertices)]
        assert len(centre) == 4, "every quad touches the shared centre"

        # ⚠️ One inset rect shared by all four cells: the mirroring is in the
        # corner *order*, not in four different sets of coordinates.
        rect = {
            (round(v.u, 3), round(v.v, 3)) for p in mesh.primitives for v in p.vertices
        }
        assert rect == {(0.028, 0.028), (0.977, 0.028), (0.977, 0.977), (0.028, 0.977)}

    def test_every_draw_names_a_mesh_the_shared_table_holds(self):
        """The export refers to geometry by index, so a draw naming a mesh the
        table does not hold would silently paint the wrong shape."""
        data = self._data()
        held = {(m.offset, m.descriptor) for m in effdata.meshes(data)}
        for effect in effdata.read(data):
            for part in effect.parts:
                for draw in effdata.draws(data, effect, part):
                    assert (draw.offset, draw.descriptor) in held

    def test_artwork_is_the_deduplicated_pictures_of_the_draws(self):
        """`artwork` dedupes and `draws` does not, so the one is exactly the
        other's distinct pictures — and no image appears from nowhere."""
        data = self._data()
        for effect in effdata.read(data):
            for part in effect.parts:
                pictures = effdata.artwork(data, effect, part)
                painted = [d.picture for d in effdata.draws(data, effect, part)]
                assert set(pictures) == {p for p in painted if p is not None}
                assert len(pictures) == len(set(pictures)), "artwork must dedupe"


class TestComposingATransform:
    """`Transform`, without a disc."""

    def test_the_identity_leaves_a_transform_alone(self):
        one = effnode.Transform((2.0, 0, 0, 5.0, 0, 3.0, 0, 6.0, 0, 0, 4.0, 7.0))
        assert effnode.IDENTITY.then(one) == one
        assert one.then(effnode.IDENTITY) == one

    def test_a_parent_scale_multiplies_a_child_translation(self):
        """⚠️ The whole point of accumulating: a child's offset is expressed in
        its parent's frame, so a parent that scales moves the child further."""
        parent = effnode.Transform((2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 2.0, 0))
        child = effnode.Transform((1.0, 0, 0, 10.0, 0, 1.0, 0, 0, 0, 0, 1.0, 0))
        got = parent.then(child).values
        assert got[3] == 20.0, "the parent's scale did not reach the child"

    def test_translations_accumulate(self):
        a = effnode.Transform((1.0, 0, 0, 3.0, 0, 1.0, 0, 0, 0, 0, 1.0, 0))
        b = effnode.Transform((1.0, 0, 0, 4.0, 0, 1.0, 0, 0, 0, 0, 1.0, 0))
        assert a.then(b).values[3] == 7.0

    def test_a_zero_scale_is_flat_and_the_identity_is_not(self):
        assert not effnode.IDENTITY.is_flat
        flat = effnode.Transform((0.0, 0, 0, 0, 0, 0.0, 0, 0, 0, 0, 1.0, 0))
        assert flat.is_flat
        # ⚠️ And it stays flat however it is parented: a collapsed axis cannot
        # be recovered downstream, which is why the rest pose loses effects.
        assert effnode.IDENTITY.then(flat).is_flat

    def test_an_index_past_the_section_gives_the_identity(self):
        data = a_file([("fire", 0, 1, 0)], ["A"])
        assert effnode.matrix_at(data, 1 << 20) == effnode.IDENTITY
        assert effnode.matrix_at(data, -1) == effnode.IDENTITY
        assert effnode.vector_at(data, 1 << 20) == (0.0, 0.0, 0.0)


@pytest.mark.gamedata
class TestTheNodeTransforms:
    """D265: section 6's matrix and section 12's TRS are the same transform."""

    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def _nodes(self, data: bytes) -> int:
        offsets = struct.unpack_from(f">{effsections.SECTIONS}I", data, 0)
        span = offsets[effnode.NODE_SECTION + 1] - offsets[effnode.NODE_SECTION]
        return span // effnode.NODE_STRIDE

    def test_the_matrix_array_is_filled_exactly(self):
        """🟢 The fit that settles the stride: the largest index any node
        carries is 1,348 and the section holds exactly 1,349 matrices at 48
        bytes — zero spare, where stride 16 would leave 2,699."""
        data = self._data()
        offsets = struct.unpack_from(f">{effsections.SECTIONS}I", data, 0)
        span = offsets[effnode.MATRIX_SECTION + 1] - offsets[effnode.MATRIX_SECTION]
        held = span // effnode.MATRIX_STRIDE
        biggest = max(effnode.node_at(data, i).matrix for i in range(self._nodes(data)))
        assert held == 1349
        assert biggest == held - 1, "the array is not filled to its last entry"

    def test_matrix_one_is_the_identity(self):
        """The nesting nodes all name matrix 1, so it had better be."""
        assert effnode.matrix_at(self._data(), 1) == effnode.IDENTITY

    def test_every_translation_column_is_the_nodes_own_translate_vector(self):
        """✅ 3,739 of 3,739 — the simplest half of the two-way agreement, and
        the one that needs no rotation order to check."""
        data = self._data()
        for i in range(self._nodes(data)):
            node = effnode.node_at(data, i)
            m = effnode.matrix_at(data, node.matrix).values
            translate = effnode.vector_at(data, node.translate)
            assert (m[3], m[7], m[11]) == pytest.approx(translate, abs=1e-4), f"node {i}"

    def test_the_matrix_is_the_nodes_own_trs_composed(self):
        """✅ **The two-way agreement**, and the strongest thing said about this
        section: section 6's matrix and section 12's translate/rotate/scale are
        the same transform stored twice, and they agree on 3,738 of 3,739 nodes.

        ⚠️ The one exception is node 3738 — the **last** in the file, whose
        matrix, translate, rotate and scale indices are all 0 and whose scale is
        therefore `(0, 0, 0)`. Padding, not a counter-example.
        """
        data = self._data()
        total = self._nodes(data)
        agree = [i for i in range(total) if _matches(data, effnode.node_at(data, i))]
        assert len(agree) == total - 1
        assert total - 1 not in agree, "the exception is not the last node"

    def test_the_rotation_order_is_discriminated_not_merely_consistent(self):
        """⛔ The check that stops `zyx` being a coincidence. 199 nodes rotate
        on more than one axis, which is what makes the six orders tell apart —
        `zyx` matches 3,738 where the next best manages 3,615. Without those 199
        every order would score the same and the claim would be empty."""
        data = self._data()
        total = self._nodes(data)
        multi = sum(
            1
            for i in range(total)
            if sum(
                1
                for v in effnode.vector_at(data, effnode.node_at(data, i).rotate)
                if abs(v) > 1e-6
            )
            > 1
        )
        assert multi > 100, f"only {multi} nodes could tell the orders apart"

        best = max(
            sum(
                1 for i in range(total) if _matches(data, effnode.node_at(data, i), order)
            )
            for order in itertools.permutations("xyz")
            if order != ("z", "y", "x")
        )
        assert best < total - 100, f"another order scored {best}; zyx is not special"

    def test_most_of_the_rest_pose_is_flat_and_that_is_not_a_fault(self):
        """⛔ **The finding that redefined this task** (D265). Applying the rest
        pose without section 10's curves renders *less* than drawing every part
        at the origin: nearly half the drawing nodes have a collapsed scale,
        waiting for a curve to animate it up from zero.
        """
        data = self._data()
        flat = live = 0
        empty = []
        for effect in effdata.read(data):
            alive = 0
            for part in effect.parts:
                for draw in effdata.draws(data, effect, part):
                    if draw.world.is_flat:
                        flat += 1
                    else:
                        live += 1
                        alive += 1
            if not alive and any(
                effdata.draws(data, effect, part) for part in effect.parts
            ):
                empty.append(effect.name)

        # ⚠️ 2,960 draws, not the 2,956 drawing *nodes*: a section 7 group can
        # hold more than one section 8 entry, and eight of them do.
        assert flat + live == 2960
        assert (flat, live) == (1308, 1652)
        assert flat > live // 2, f"only {flat} of {flat + live} are flat"
        assert len(empty) == 26, f"{len(empty)} effects vanish: {sorted(empty)[:6]}"
        # ⚠️ Named, because the handoff cites this one as reeling "as a flame
        # swirl" — posing it from the rest pose alone would lose it entirely.
        assert "item_fire" in empty

    def test_a_draw_carries_where_its_node_landed(self):
        """The accumulation reaches the export, rather than stopping at the
        walk. `dmen_magic`'s nodes nest three deep."""
        data = self._data()
        effects = {e.name: e for e in effdata.read(data)}
        magic = effects["dmen_magic"]
        found = [d for part in magic.parts for d in effdata.draws(data, magic, part)]
        assert found
        assert any(d.world != effnode.IDENTITY for d in found), "nothing accumulated"


def _matches(data: bytes, node, order: tuple = ("z", "y", "x")) -> bool:
    """Whether a node's TRS composes to the matrix it names."""
    got = _compose(
        effnode.vector_at(data, node.translate),
        effnode.vector_at(data, node.rotate),
        effnode.vector_at(data, node.scale),
        order,
    )
    return all(
        abs(a - b) <= 1e-3 * max(1.0, abs(a), abs(b))
        for a, b in zip(got, effnode.matrix_at(data, node.matrix).values, strict=True)
    )


def _compose(translate, rotate, scale, order) -> list[float]:
    """Translate/rotate/scale as a 3x4, rotating in `order`, degrees."""
    turn = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
    for which in order:
        turn = _times(turn, _axis(which, rotate["xyz".index(which)]))
    out: list[float] = []
    for row in range(3):
        out.extend(turn[row * 3 + col] * scale[col] for col in range(3))
        out.append(translate[row])
    return out


def _times(a, b) -> list[float]:
    return [
        sum(a[r * 3 + k] * b[k * 3 + c] for k in range(3))
        for r in range(3)
        for c in range(3)
    ]


def _axis(which: str, degrees: float) -> list[float]:
    turn = math.radians(degrees)
    cos, sin = math.cos(turn), math.sin(turn)
    if which == "x":
        return [1.0, 0, 0, 0, cos, -sin, 0, sin, cos]
    if which == "y":
        return [cos, 0, sin, 0, 1.0, 0, -sin, 0, cos]
    return [cos, -sin, 0, sin, cos, 0, 0, 0, 1.0]
