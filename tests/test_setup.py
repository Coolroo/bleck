"""Reading and writing `setup/*.dat` — enemy and item placement.

The load-bearing property is **byte-exact round-tripping**. Roughly 70 of an
entry's 112 bytes are undocumented, so a writer that rebuilds an entry from the
fields it understands would quietly discard the rest. Everything here is really
in service of "changing one thing changes exactly one thing".
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from bleck.formats import setup
from bleck.mods import manifest as mod_manifest
from bleck.mods import registry
from bleck.mods.build import edits as mod_edits
from bleck.mods.manifest import ManifestError, PlacementEdit

DISC_SETUP = Path("work/extracted/eu0/files/setup")


def build(version: int = 6, slots=(), items=None, item_version=setup.ITEM_VERSION):
    """A synthetic setup file. `slots` is {index: bytes-to-place-at-offset-0}."""
    stride = setup.STRIDE[version]
    out = bytearray(struct.pack(">HH", version, 0))
    for index in range(setup.ENEMY_SLOTS):
        entry = bytearray(stride)
        if index in dict(slots):
            payload = dict(slots)[index]
            entry[: len(payload)] = payload
        out += entry
    if items is not None:
        out += struct.pack(">ii", len(items), item_version)
        for flags, kind, pos in items:
            out += struct.pack(">HH3f", flags, kind, *pos)
    return bytes(out)


def entry(template: int, position=(1.0, 2.0, 3.0), tail: bytes = b"") -> bytes:
    """A v6 entry: Vec3 pos, s32 type, then whatever else."""
    return struct.pack(">3fi", *position, template) + tail


class TestRoundTrip:
    @pytest.mark.parametrize("version", sorted(setup.STRIDE))
    def test_every_version_round_trips(self, version):
        raw = build(version, slots={0: b"\x11\x22\x33\x44"})
        assert setup.parse(raw).to_bytes() == raw

    def test_undocumented_bytes_survive_an_edit(self):
        """The point of the whole design.

        An entry has ~70 bytes nobody has decoded. Editing the template must
        carry them through untouched, or a one-field change silently rewrites
        most of the entry.
        """
        noise = bytes(range(0x10, 0x10 + 112 - 16))
        raw = build(6, slots={0: entry(5, tail=noise)})
        data = setup.parse(raw)

        edited = data.enemies[0].with_template(42)
        assert edited.template == 42
        # Everything after the type field is identical.
        assert edited.raw[16:] == data.enemies[0].raw[16:]
        # ...and so is the position before it.
        assert edited.position.as_tuple() == (1.0, 2.0, 3.0)

    def test_an_item_section_round_trips(self):
        raw = build(6, items=[(0x11, 0, (1.0, 2.0, 3.0)), (0x00, 0, (4.0, 5.0, 6.0))])
        data = setup.parse(raw)
        assert len(data.items) == 2
        assert data.to_bytes() == raw

    def test_a_file_without_items_stays_without_them(self):
        raw = build(6)
        assert setup.parse(raw).to_bytes() == raw
        assert not setup.parse(raw).has_item_section


class TestParsing:
    def test_the_slot_count_is_always_a_hundred(self):
        # Fixed regardless of how many are used -- which is why a nearly empty
        # map still produces an 11 KB file.
        assert len(setup.parse(build(6)).enemies) == 100

    def test_an_unknown_version_is_rejected_with_the_known_ones(self):
        raw = bytearray(build(6))
        raw[0:2] = struct.pack(">H", 99)
        with pytest.raises(setup.SetupError, match="known: 1, 2, 3, 4, 5, 6"):
            setup.parse(bytes(raw))

    def test_a_truncated_file_says_what_it_expected(self):
        with pytest.raises(setup.SetupError, match="needs at least"):
            setup.parse(build(6)[:500])

    def test_a_lying_item_count_is_rejected(self):
        raw = build(6, items=[]) + b""
        raw = raw[:-8] + struct.pack(">ii", 9999, setup.ITEM_VERSION)
        with pytest.raises(setup.SetupError, match="item section claims"):
            setup.parse(raw)

    def test_empty_slots_are_judged_by_template_not_by_blankness(self):
        """Unused slots are not blank -- they carry a default in an
        undocumented field, so an any-non-zero test counts 6,438 slots where
        only ~1,328 place anything."""
        raw = build(
            6,
            slots={0: entry(0, position=(0, 0, 0), tail=bytes([0] * 4 + [0, 0, 1, 44]))},
        )
        data = setup.parse(raw)
        assert any(data.enemies[0].raw)  # not blank...
        assert data.enemies[0].is_empty  # ...but places nothing
        assert data.used == []


class TestUndocumentedVersions:
    """Only version 6 has a documented entry layout; 198 of 227 files are v6."""

    def test_fields_are_refused_rather_than_guessed(self):
        data = setup.parse(build(3, slots={0: b"\x01\x02\x03\x04"}))
        with pytest.raises(setup.SetupError, match="undocumented"):
            _ = data.enemies[0].template

    def test_editing_is_refused_rather_than_corrupting(self):
        data = setup.parse(build(3, slots={0: b"\x01\x02\x03\x04"}))
        with pytest.raises(setup.SetupError, match="would corrupt"):
            data.enemies[0].with_template(1)

    def test_they_still_round_trip(self):
        raw = build(3, slots={0: b"\x01\x02\x03\x04"})
        assert setup.parse(raw).to_bytes() == raw


class TestItems:
    def test_spawning_needs_both_documented_flags(self):
        # Upstream: "0x10 and 0x1 required to spawn, others unused".
        assert setup.Item(0x11, 0, setup.Position(0, 0, 0)).spawns
        assert not setup.Item(0x10, 0, setup.Position(0, 0, 0)).spawns
        assert not setup.Item(0x01, 0, setup.Position(0, 0, 0)).spawns
        assert setup.Item(0xFF, 0, setup.Position(0, 0, 0)).spawns


@pytest.mark.skipif(not DISC_SETUP.is_dir(), reason="no extracted disc")
class TestAgainstTheRealDisc:
    """The claims in disc-layout.md, checked rather than trusted."""

    def test_every_file_round_trips_byte_exactly(self):
        for path in sorted(DISC_SETUP.glob("*.dat")):
            assert setup.read(path).to_bytes() == path.read_bytes(), path.name

    def test_the_base_size_formula_holds(self):
        # base size = 4 + 100 * stride, for every version on the disc.
        for path in sorted(DISC_SETUP.glob("*.dat")):
            data = setup.read(path)
            base = setup.HEADER_SIZE + setup.ENEMY_SLOTS * data.stride
            assert len(path.read_bytes()) >= base, path.name

    def test_every_item_section_carries_the_same_version_constant(self):
        found = 0
        for path in sorted(DISC_SETUP.glob("*.dat")):
            data = setup.read(path)
            if data.items:
                assert data.item_version == setup.ITEM_VERSION, path.name
                found += 1
        assert found == 14, "disc-layout.md records 14 files with items"


class TestNames:
    """Turning `template 250` into `Squiglet (e_octa2)`.

    Two hops, and the middle one is the easy thing to get wrong: a setup entry
    names a *template*, templates name a *tribe*, and only the tribe has a name.
    """

    def test_a_template_resolves_through_its_tribe(self):
        names = setup.NpcNames(
            templates=[{"id": 0, "tribe": 7}],
            tribes=[{}] * 7 + [{"name": "e_kuribo", "english": "Goomba"}],
        )
        species = names.lookup(0)
        assert species.tribe == 7
        assert species.describe() == "Goomba (e_kuribo)"

    def test_an_unknown_template_is_not_invented(self):
        assert setup.NpcNames(templates=[{"id": 0, "tribe": 0}]).lookup(99) is None

    def test_a_tribe_with_no_english_name_still_describes(self):
        names = setup.NpcNames(
            templates=[{"id": 0, "tribe": 0}], tribes=[{"name": "e_mystery"}]
        )
        assert names.lookup(0).describe() == "e_mystery"

    def test_a_nameless_species_falls_back_to_its_number(self):
        names = setup.NpcNames(templates=[{"id": 0, "tribe": -1}], tribes=[])
        assert names.lookup(0).describe() == "template 0"

    def test_a_missing_catalog_is_not_an_error(self, tmp_path):
        # Names are a convenience; everything else must work without them.
        empty = setup.load_names(tmp_path / "absent.json")
        assert not empty
        assert empty.lookup(0) is None


@pytest.mark.skipif(not setup.NPC_CATALOG.is_file(), reason="no NPC catalog")
class TestTheCommittedNpcCatalog:
    def test_it_covers_every_template(self):
        names = setup.load_names()
        assert names
        # spm-headers: NPCTEMPLATE_MAX is 435.
        assert names.lookup(434) is not None
        assert names.lookup(435) is None

    def test_goomba_survives_the_enum_collision(self):
        """`npcdrv.h` has several `NPC_` enums, and `NPCMoveMode` also starts at
        0. Parsing them all named tribe 0 "Move Walk No Hit"."""
        assert setup.load_names().lookup(2).describe() == "Goomba (e_kuribo)"


class TestDeclaredEdits:
    """Edits live in `mod.json` and the bytes are derived at build time.

    A mod could ship a patched `.dat` instead. It would work and be a dead end:
    a blob cannot be reviewed, undone, or re-applied to a corrected base. See
    `docs/vision.md`.
    """

    def parse(self, body: dict):

        return mod_manifest.Manifest.from_json(
            json.dumps({"schema": 1, "name": "m", **body}), source="test"
        )

    def test_edits_round_trip_through_the_manifest(self):
        original = self.parse(
            {
                "setup": {
                    "he1_01": [
                        {"slot": 0, "template": 42},
                        {"slot": 1, "position": [100, 0, -50]},
                        {"slot": 2, "clear": True},
                    ]
                }
            }
        )
        again = self.parse(json.loads(original.to_json()))
        assert again.setup == original.setup
        assert again.setup[0].map_name == "he1_01"

    def test_a_slot_outside_the_array_is_rejected(self):

        with pytest.raises(ManifestError, match="out of range"):
            self.parse({"setup": {"he1_01": [{"slot": 100, "template": 1}]}})

    def test_an_edit_that_changes_nothing_is_rejected(self):
        # Silently doing nothing is the failure mode this whole area has.

        with pytest.raises(ManifestError, match="changes nothing"):
            self.parse({"setup": {"he1_01": [{"slot": 0}]}})

    def test_clearing_and_setting_at_once_is_rejected(self):

        with pytest.raises(ManifestError, match="both clears and sets"):
            self.parse({"setup": {"he1_01": [{"slot": 0, "clear": True, "template": 5}]}})

    def test_a_malformed_position_says_the_shape(self):

        with pytest.raises(ManifestError, match="three numbers"):
            self.parse({"setup": {"he1_01": [{"slot": 0, "position": [1, 2]}]}})


class TestApplyingEdits:
    def test_each_kind_of_edit_lands(self):

        base = setup.parse(build(6, slots={0: entry(5), 1: entry(9)}))

        retyped = mod_edits._apply_edit(  # pylint: disable=protected-access
            base.enemies[0], PlacementEdit(slot=0, template=77), "m"
        )
        assert retyped.template == 77

        moved = mod_edits._apply_edit(  # pylint: disable=protected-access
            base.enemies[1],
            PlacementEdit(slot=1, position=setup.Position(1, 2, 3)),
            "m",
        )
        assert moved.position.as_tuple() == (1.0, 2.0, 3.0)
        assert moved.template == 9  # untouched

        gone = mod_edits._apply_edit(  # pylint: disable=protected-access
            base.enemies[0], PlacementEdit(slot=0, clear=True), "m"
        )
        assert gone.is_empty
        assert len(gone.raw) == len(base.enemies[0].raw)

    def test_the_generated_file_is_the_same_size_as_the_original(self):
        # The array is fixed at 100 slots; an edit must not resize anything.
        raw = build(6, slots={0: entry(5)})
        data = setup.parse(raw)
        slots = list(data.enemies)
        slots[0] = slots[0].with_template(99)
        rebuilt = setup.SetupFile(version=6, enemies=slots, items=[])
        assert len(rebuilt.to_bytes()) == len(raw)


class TestOrphanedSlots:
    """The game stops reading setup entries at the first empty one (D79).

    A cleared slot in the middle silently discards everything past it. That was
    open for a day as "an enemy did not appear", with two plausible and entirely
    wrong explanations, because the file `bleck` wrote looked perfectly fine.
    """

    def _file(self, used):
        """A parsed setup file whose listed slots are occupied, rest empty."""
        return setup.parse(build(6, slots={index: entry(250) for index in used}))

    def _check(self, used):
        mod = registry.Mod(manifest=mod_manifest.Manifest(name="m"), root=Path("m"))
        placement = mod_manifest.MapPlacements(map_name="he1_01", edits=[])
        mod_edits._refuse_orphans(  # pylint: disable=protected-access
            mod, placement, self._file(used)
        )

    def test_a_gap_before_a_used_slot_is_refused(self):
        with pytest.raises(mod_edits.EditError) as caught:
            self._check([0, 2])
        message = str(caught.value)
        assert "slot 1" in message and "slot(s) 2" in message
        # And says what to do instead, not merely that it is wrong.
        assert "Clear the last used slot" in message

    def test_contiguous_slots_are_fine(self):
        self._check([0, 1, 2])

    def test_clearing_the_last_slot_is_fine(self):
        """The supported way to remove an enemy: nothing is left stranded."""
        self._check([0, 1])

    def test_an_entirely_empty_file_is_fine(self):
        self._check([])

    def test_several_orphans_are_all_named(self):
        with pytest.raises(mod_edits.EditError, match=r"slot\(s\) 2, 3"):
            self._check([0, 2, 3])
