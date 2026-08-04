"""Sections 5 and 4, and the two curve evaluators D266 counted and D278 found.

⚠️ **The teeth here are the exact fill.** Section 10's 4,752 commands are
claimed by three readers — nodes, materials and textures — and the claim is only
a reading if every command belongs to exactly one of them and none is left over.
Anything short of that is a plausible partial answer, which is what seven
refuted image-index candidates all were (D210, D218).
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import pytest

from bleck.cli.commands import effect
from bleck.formats import effcurve, effdata, effnode, effpaint, effsections

REPO = Path(__file__).resolve().parent.parent
EFFDATA = REPO / "work" / "extracted" / "eu0" / "files" / "eff" / "effdata.dat"

#: Where the synthetic file puts each section it needs. Section 2 holds curve
#: samples, 4 the texture records, 5 the materials, 10 the commands.
CURVE, TEXTURE, MATERIAL, COMMAND = 2, 4, 5, 10


def a_file(
    materials: list[bytes], textures: list[bytes], commands: list, curves: bytes
) -> bytes:
    # pylint: disable=container-return
    """A minimal `effdata.dat` holding only the four sections this reads.

    ⚠️ **Every one of the sixteen offsets is laid out in order**, because a
    section's size is the distance to the *next* one — leaving an unused section
    pointing past the ones after it makes each of them read as empty, and the
    reader then answers `None` for records that are really there.
    """
    content = {
        CURVE: curves,
        TEXTURE: b"".join(textures),
        MATERIAL: b"".join(materials),
        COMMAND: b"".join(struct.pack(">II", tag, at) for tag, at in commands),
    }
    body = bytearray()
    offsets = []
    base = effsections.SECTIONS * 4
    for index in range(effsections.SECTIONS):
        offsets.append(base + len(body))
        body.extend(content.get(index, b""))
    out = bytearray(struct.pack(f">{effsections.SECTIONS}I", *offsets))
    out.extend(body)
    return bytes(out)


def a_material(rgba: tuple, texture: int, first: int = 0, count: int = 0) -> bytes:
    out = bytearray(16)
    out[0:4] = bytes(rgba)
    struct.pack_into(">2h", out, 4, first, count)
    struct.pack_into(">h", out, 12, texture)
    return bytes(out)


def a_texture(  # pylint: disable=too-many-positional-arguments
    image: int,
    wrap: int = 3,
    flags: int = 0,
    uv: tuple = (0.0, 0.0, 1.0, 1.0, 0.0),
    first: int = 0,
    count: int = 0,
) -> bytes:
    out = bytearray(28)
    struct.pack_into(">hBB", out, 0, image, wrap, flags)
    struct.pack_into(">5f", out, 4, *uv)
    struct.pack_into(">2h", out, 0x18, first, count)
    return bytes(out)


def a_curve(samples: list, *, first: int = 0, byte_samples: int = 1) -> bytes:
    """One section 2 record: header then samples, `u8` unless told otherwise."""
    last = first + len(samples) - 1
    head = struct.pack(">IHHHH", last + 1, first, last, 0, byte_samples)
    if byte_samples:
        return head + bytes(int(v) for v in samples)
    return head + struct.pack(f">{len(samples)}f", *samples)


class TestTheRecords:
    """What the two records hold, read at the offsets the game loads."""

    def test_a_material_is_its_colour_register_its_texture_and_its_curve_run(self):
        data = a_file([a_material((1, 2, 3, 4), 0, first=7, count=2)], [], [], b"")
        material = effpaint.material_at(data, 0)
        assert material is not None
        assert (material.colour.red, material.colour.alpha) == (1, 4)
        assert material.texture == 0
        assert material.run == effpaint.Run(7, 2)

    def test_a_material_naming_no_texture_still_reads(self):
        """⚠️ 20 of the file's 524 carry the documented `-1`, and they still
        have a colour register and a curve run."""
        data = a_file([a_material((9, 9, 9, 9), -1)], [], [], b"")
        material = effpaint.material_at(data, 0)
        assert material is not None and material.texture == -1
        assert effpaint.sampler_at(data, material.texture) is None

    def test_a_texture_record_is_read_whole_rather_than_its_first_two_fields(self):
        uv = (0.25, 0.5, 2.0, 4.0, 90.0)
        data = a_file(
            [], [a_texture(17, wrap=12, flags=5, uv=uv, first=3, count=1)], [], b""
        )
        sampler = effpaint.sampler_at(data, 0)
        assert sampler is not None
        assert (sampler.image, sampler.wrap, sampler.flags) == (17, 12, 5)
        assert sampler.uv.translate_u == 0.25
        assert sampler.uv.translate_v == 0.5
        assert sampler.uv.scale_u == 2.0
        assert sampler.uv.scale_v == 4.0
        assert sampler.uv.rotation == 90.0
        assert sampler.run == effpaint.Run(3, 1)

    def test_an_index_outside_the_section_is_none_rather_than_a_wrong_record(self):
        data = a_file([a_material((0, 0, 0, 0), 0)], [a_texture(0)], [], b"")
        assert effpaint.material_at(data, 1) is None
        assert effpaint.material_at(data, -1) is None
        assert effpaint.sampler_at(data, 1) is None


class TestTheWrapByte:
    """Two bits per axis, mirror winning over the repeat bit (`0x8004cb54`).

    ⛔ Reading the byte as one mode for both axes gets 3 of the file's 350
    records right and the rest wrong in a way that only shows outside the unit
    square.
    """

    def _wrap(self, byte: int) -> tuple:
        # pylint: disable=container-return
        data = a_file([], [a_texture(0, wrap=byte)], [], b"")
        sampler = effpaint.sampler_at(data, 0)
        assert sampler is not None
        return (sampler.wrap_s, sampler.wrap_t)

    def test_each_bit_selects_one_axis(self):
        assert self._wrap(0) == (effpaint.WRAP_CLAMP, effpaint.WRAP_CLAMP)
        assert self._wrap(1) == (effpaint.WRAP_REPEAT, effpaint.WRAP_CLAMP)
        assert self._wrap(2) == (effpaint.WRAP_CLAMP, effpaint.WRAP_REPEAT)
        assert self._wrap(3) == (effpaint.WRAP_REPEAT, effpaint.WRAP_REPEAT)

    def test_the_mirror_bit_wins_over_the_repeat_bit(self):
        """⚠️ The game tests bit 2 *first* and only falls back to bit 0, so a
        byte with both set mirrors rather than repeating."""
        assert self._wrap(4) == (effpaint.WRAP_MIRROR, effpaint.WRAP_CLAMP)
        assert self._wrap(5) == (effpaint.WRAP_MIRROR, effpaint.WRAP_CLAMP)
        assert self._wrap(8) == (effpaint.WRAP_CLAMP, effpaint.WRAP_MIRROR)
        assert self._wrap(15) == (effpaint.WRAP_MIRROR, effpaint.WRAP_MIRROR)


class TestTheEvaluators:
    """A curve overrides one slot and leaves the record's other values alone."""

    def _one_material(self, rgba: tuple, tag: int, samples: list) -> bytes:
        return a_file(
            [a_material(rgba, 0, first=0, count=1)],
            [],
            [(tag, 0)],
            a_curve(samples),
        )

    def test_a_colour_curve_overrides_one_channel_and_keeps_the_rest(self):
        """⛔ **The composition the game's own evaluator uses.** It stores the
        four register bytes into a slot array before the loop and a curve
        overwrites one by tag, so this composes rather than replacing."""
        data = self._one_material((10, 20, 30, 40), 1, [200, 201])
        every = effpaint.command_list(data)
        composed = effpaint.colour_at(data, 0, 0.0, every)
        assert composed.green == 200
        assert (composed.red, composed.blue, composed.alpha) == (10, 30, 40)
        assert effpaint.colour_at(data, 0, 1.0, every).green == 201

    def test_a_material_with_no_run_is_its_register(self):
        data = a_file([a_material((10, 20, 30, 40), 0)], [], [], b"")
        composed = effpaint.colour_at(data, 0, 5.0, effpaint.command_list(data))
        assert (composed.red, composed.green, composed.blue, composed.alpha) == (
            10,
            20,
            30,
            40,
        )

    def test_a_curve_that_has_not_started_leaves_the_register_alone(self):
        """⚠️ `spindash` depends on exactly this: register alpha 0, and a curve
        that begins at frame 1 (D281)."""
        data = a_file(
            [a_material((255, 255, 255, 0), 0, first=0, count=1)],
            [],
            [(3, 0)],
            a_curve([100, 200], first=1),
        )
        every = effpaint.command_list(data)
        assert effpaint.colour_at(data, 0, 0.0, every).alpha == 0
        assert effpaint.colour_at(data, 0, 1.0, every).alpha == 100

    def test_a_uv_curve_overrides_one_scalar_and_keeps_the_rest(self):
        data = a_file(
            [],
            [a_texture(0, uv=(0.1, 0.2, 2.0, 3.0, 45.0), first=0, count=1)],
            [(1, 0)],
            a_curve([-0.5, -1.0], byte_samples=0),
        )
        every = effpaint.command_list(data)
        moved = effpaint.uv_at(data, 0, 0.0, every)
        assert moved.translate_v == -0.5
        assert moved.translate_u == pytest.approx(0.1)
        assert moved.scale_u == 2.0
        assert moved.scale_v == 3.0
        assert moved.rotation == 45.0
        assert effpaint.uv_at(data, 0, 1.0, every).translate_v == -1.0

    def test_a_tag_the_record_has_no_slot_for_is_dropped_not_clamped(self):
        """⚠️ A texture has five slots and a material four. Folding a stray tag
        onto the last one would drive a scalar the game never touches."""
        data = self._one_material((10, 20, 30, 40), 9, [200])
        every = effpaint.command_list(data)
        composed = effpaint.colour_at(data, 0, 0.0, every)
        assert (composed.red, composed.green, composed.blue, composed.alpha) == (
            10,
            20,
            30,
            40,
        )

    def test_a_run_past_the_end_of_the_command_table_is_skipped(self):
        data = a_file([a_material((1, 2, 3, 4), 0, first=50, count=3)], [], [], b"")
        assert not effpaint.run_of(effpaint.Run(50, 3), effpaint.command_list(data))


@pytest.mark.gamedata
class TestAgainstTheRealFile:
    """The exact-fill argument, and the counts D278 measured."""

    def _data(self) -> bytes:
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        return EFFDATA.read_bytes()

    def test_the_sections_hold_the_record_counts_the_strides_imply(self):
        data = self._data()
        assert effpaint.material_count(data) == 524
        assert effpaint.sampler_count(data) == 350

    def test_every_curve_command_is_claimed_exactly_once(self):
        """⛔ **The whole reading rests on this.** Nodes, materials and textures
        each name a run of section 10; if the three overlapped, or left
        commands over, one of the three record layouts would be wrong."""
        data = self._data()
        every = effpaint.command_list(data)
        assert len(every) == 4752

        def claimed(runs) -> set:
            found = set()
            for run in runs:
                for step in range(max(run.count, 0)):
                    at = run.first + step
                    if 0 <= at < len(every):
                        found.add(at)
            return found

        nodes = claimed(
            effpaint.Run(node.curves, node.count)
            for node in (
                effnode.node_at(data, index) for index in range(effnode.node_count(data))
            )
        )
        materials = claimed(m.run for m in effpaint.materials(data))
        textures = claimed(s.run for s in effpaint.samplers(data))

        assert len(nodes) == 4447
        assert len(materials) == 212
        assert len(textures) == 93
        assert not nodes & materials
        assert not nodes & textures
        assert not materials & textures
        assert len(nodes | materials | textures) == len(every)

    def test_the_two_runs_are_told_apart_by_their_sample_format(self):
        """✅ 212 of 212 material curves are `u8` in 0..255 — colour channels —
        and 93 of 93 texture curves are `f32`. Two independent discriminators
        agreeing is what makes the split a reading rather than a partition.

        ⚠️ Counted over the **distinct commands**, not over the references and
        not over the curve records either. 97 materials reference 229 commands,
        212 of which are different, and those 212 land on only 190 distinct
        section 2 offsets — several commands share a curve. Any one of those
        three numbers can be made to look like an overrun by counting the wrong
        one."""
        data = self._data()
        every = effpaint.command_list(data)

        def curves_of(runs) -> list:
            wanted = set()
            for run in runs:
                for step in range(max(run.count, 0)):
                    if 0 <= run.first + step < len(every):
                        wanted.add(run.first + step)
            return [
                effcurve.curve_at(data, every[index].offset) for index in sorted(wanted)
            ]

        colours = curves_of([m.run for m in effpaint.materials(data)])
        assert len(colours) == 212
        assert all(curve.byte_samples for curve in colours)
        assert all(0.0 <= v <= 255.0 for curve in colours for v in curve.samples)

        uvs = curves_of([s.run for s in effpaint.samplers(data)])
        assert len(uvs) == 93
        assert all(not curve.byte_samples for curve in uvs)
        every_sample = [v for curve in uvs for v in curve.samples]
        assert min(every_sample) >= -18.0 and max(every_sample) <= 360.0

    def test_the_records_that_animate_are_the_minority_that_d278_counted(self):
        data = self._data()
        animated = [m for m in effpaint.materials(data) if not m.run.is_empty]
        assert len(animated) == 97
        moving = [s for s in effpaint.samplers(data) if not s.run.is_empty]
        assert len(moving) == 103

    def test_the_static_uv_transform_is_not_the_identity_everywhere(self):
        """⚠️ Reading `+0x04`..`+0x14` as padding would pass every other test
        here. 58 records carry a transform before any curve runs."""
        data = self._data()
        moved = [s for s in effpaint.samplers(data) if not s.uv.is_identity]
        assert len(moved) == 58
        turned = [s for s in moved if s.uv.rotation]
        assert len(turned) == 26
        assert {round(s.uv.rotation) for s in turned} == {90, -90}

    def test_the_wrap_byte_is_not_one_mode_for_both_axes(self):
        data = self._data()
        every = effpaint.samplers(data)
        mixed = [s for s in every if s.wrap_s != s.wrap_t]
        assert len(mixed) == 3, "an axis-per-bit reading is what makes these 3"
        mirrored = [s for s in every if effpaint.WRAP_MIRROR in (s.wrap_s, s.wrap_t)]
        assert len(mirrored) == 16


@pytest.mark.gamedata
class TestTheExport:
    """What `bleck effect export` writes, read back.

    ⚠️ **Re-exported here rather than reading `work/export`.** A stale manifest
    has been mistaken for a renderer bug three times in this repo (D267, D271),
    and a test that reads whatever is on disk cannot tell the two apart.
    """

    def _manifest(self, tmp_path) -> dict:
        # pylint: disable=container-return
        if not EFFDATA.is_file():
            pytest.skip(f"no extracted disc at {EFFDATA}")
        args = argparse.Namespace(out=str(tmp_path))
        assert effect.cmd_export(args) == 0
        return json.loads((tmp_path / effect.MANIFEST).read_text(encoding="utf-8"))

    def test_the_schema_names_the_two_new_tables(self, tmp_path):
        written = self._manifest(tmp_path)
        assert written["schema"] == 4
        assert len(written["materials"]) == 524
        assert len(written["samplers"]) == 350

    def test_the_three_evaluators_share_one_curve_table(self, tmp_path):
        """⛔ **One table, not three.** A curve named by a node and by a
        material is the same record, and writing it twice would inflate the
        manifest while telling a reader nothing extra."""
        written = self._manifest(tmp_path)
        reached = {
            slot
            for row in written["nodes"] + written["materials"] + written["samplers"]
            for _, slot in row["curves"]
        }
        assert len(written["curves"]) == 3221
        assert reached == set(range(len(written["curves"]))), (
            "the curve table holds rows nothing names, or names rows it does not hold"
        )
        from_nodes = {slot for row in written["nodes"] for _, slot in row["curves"]}
        from_paint = reached - from_nodes
        assert len(from_paint) == 281, "the two new evaluators added no curves"

    def test_every_draw_names_a_row_of_both_tables(self, tmp_path):
        written = self._manifest(tmp_path)
        draws = [
            draw
            for entry in written["effects"]
            for part in entry["parts"]
            for draw in part["draws"]
        ]
        assert len(draws) == 2960
        for draw in draws:
            assert 0 <= draw["material"] < len(written["materials"])
            if draw["image"] == effect.NO_IMAGE:
                assert draw["sampler"] == effdata.NO_RECORD
            else:
                assert written["samplers"][draw["sampler"]]["image"] == draw["image"]

    def test_the_static_channels_stay_beside_the_table(self, tmp_path):
        """⚠️ A reader written before the tables landed uses these, so removing
        them would make this export render every draw white in it."""
        written = self._manifest(tmp_path)
        draw = written["effects"][0]["parts"][0]["draws"][0]
        row = written["materials"][draw["material"]]
        assert row["rgba"] == [
            draw["red"],
            draw["green"],
            draw["blue"],
            draw["alpha"],
        ]

    def test_the_wrap_byte_is_decoded_into_the_two_axes(self, tmp_path):
        written = self._manifest(tmp_path)
        for row in written["samplers"]:
            assert row["wrap_s"] in (0, 1, 2)
            assert row["wrap_t"] in (0, 1, 2)
        mixed = [r for r in written["samplers"] if r["wrap_s"] != r["wrap_t"]]
        assert len(mixed) == 3
