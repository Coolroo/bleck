"""Placed items — `tables/items.csv`, and the inline `setup.<map>.items` block.

Items are not enemies wearing a different column name, and most of these tests
exist to pin the difference. An enemy occupies one of 100 fixed slots; an item
is a position in a counted list, so:

- a row with no `index` **adds** one, where an enemy row with no `slot` says
  nothing at all;
- `clear` needs an `index`, because there is no empty item to clear;
- there is no orphan rule, because a counted array cannot have a hole (D79 is
  an enemy problem);
- only type 0 exists, so anything else is refused rather than written.
"""

from __future__ import annotations

import json
import struct

import pytest

from bleck.formats import setup, tables
from bleck.mods import manifest as mod_manifest
from bleck.mods import registry
from bleck.mods.build import edits as mod_edits
from bleck.mods.manifest import ManifestError

HEADER = "map,index,x,y,z\n"


def rows(text: str, source: str = "tables/items.csv", bound: str = ""):
    return tables.items.parse(text, source, bound).rows


def setup_file(items=(), enemies=0) -> bytes:
    """A synthetic v6 setup file, optionally with an item section."""
    out = bytearray(struct.pack(">HH", 6, 0))
    for index in range(setup.ENEMY_SLOTS):
        entry = bytearray(setup.STRIDE[6])
        if index < enemies:
            struct.pack_into(">3fi", entry, 0, 1.0, 2.0, 3.0, 7)
        out += entry
    if items:
        out += struct.pack(">ii", len(items), setup.ITEM_VERSION)
        for x, y, z in items:
            out += struct.pack(">HH3f", setup.Item.SPAWNS, setup.Item.COIN, x, y, z)
    return bytes(out)


def a_mod(root, body: dict, table: str | None = None) -> registry.Mod:
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.json").write_text(
        json.dumps({"schema": 1, "name": root.name, **body}), encoding="utf-8"
    )
    if table is not None:
        (root / "tables").mkdir(exist_ok=True)
        (root / "tables" / "items.csv").write_text(table, encoding="utf-8")
    return registry.Mod(manifest=mod_manifest.read(root), root=root)


class TestAddingIsTheDefault:
    """213 of the game's 227 maps place no items, so adding is the common case
    and the format should not make it the awkward one."""

    def test_a_row_with_no_index_adds(self):
        found = rows(HEADER + "he1_03,,-300,0,0\n")[0]
        assert found.index is None
        assert found.is_add
        assert found.position == setup.Position(-300.0, 0.0, 0.0)

    def test_an_index_edits_instead(self):
        found = rows(HEADER + "he1_03,2,-300,0,0\n")[0]
        assert found.index == 2
        assert not found.is_add

    def test_an_added_item_must_say_where(self):
        """The origin is off the map in most rooms, and an item nobody can reach
        looks exactly like an item that never spawned."""
        with pytest.raises(tables.TableError, match="added item needs a position"):
            rows("map,flags\nhe1_03,0x11\n")

    def test_a_row_that_says_only_a_map_is_refused(self):
        with pytest.raises(tables.TableError, match="changes nothing"):
            rows("map,index\nhe1_03,\n")


class TestItemsAreNotEnemies:
    def test_slot_is_not_a_column(self):
        """Reusing the word would tell a reader the number means something it
        does not -- an item index is a list position, not a fixed slot."""
        with pytest.raises(tables.TableError, match="unknown column 'slot'"):
            rows("map,slot\nhe1_03,3\n")
        assert "slot" not in tables.items.COLUMNS
        assert "index" not in tables.enemies.COLUMNS

    def test_clear_needs_an_index(self):
        with pytest.raises(tables.TableError, match="'clear' needs an 'index'"):
            rows("map,clear\nhe1_03,true\n")

    def test_clear_is_still_exclusive(self):
        with pytest.raises(tables.TableError, match="both clears and sets"):
            rows("map,index,x,y,z,clear\nhe1_03,1,0,0,0,true\n")

    def test_an_unbound_item_table_needs_only_a_map_column(self):
        """An enemy table also requires `slot`; here every other column is
        optional, because a position alone is a complete row."""
        assert tables.items.REQUIRED == ("map",)
        # A bound table needs no columns at all: the manifest said the map.
        assert not tables.items.REQUIRED_BOUND

    def test_a_bound_table_needs_no_columns_but_x_y_z(self):
        found = rows("x,y,z\n1,2,3\n", bound="he1_03")
        assert found[0].map_name == "he1_03"
        assert found[0].is_add


class TestOnlyCoinsExist:
    def test_a_non_zero_type_is_refused_with_the_reason(self):
        with pytest.raises(tables.TableError) as caught:
            rows("map,type,x,y,z\nhe1_03,1,0,0,0\n")
        message = str(caught.value)
        assert "setupItemTemplates" in message
        assert "exactly one entry" in message

    def test_type_zero_is_accepted(self):
        assert rows("map,type,x,y,z\nhe1_03,0,1,2,3\n")[0].type == setup.Item.COIN

    def test_flags_read_as_a_bit_pattern(self):
        """`0x11`, not 17: these are bits, and a table that silently read them
        as decimal would place items that never spawn."""
        assert rows("map,flags,x,y,z\nhe1_03,0x11,1,2,3\n")[0].flags == 0x11
        assert rows("map,flags,x,y,z\nhe1_03,17,1,2,3\n")[0].flags == 17

    def test_flags_must_fit_in_16_bits(self):
        with pytest.raises(tables.TableError, match="does not fit in 16 bits"):
            rows("map,flags,x,y,z\nhe1_03,0x10000,1,2,3\n")


class TestApplying:
    """What the generated `.dat` actually holds."""

    def build(self, tmp_path, body, table=None, base_items=((0, 0, 0),), enemies=0):
        """⚠️ `base_items` defaults to a map that already ships one, because a
        map with none refuses every addition (D127)."""
        mod = a_mod(tmp_path / "m", body, table)
        data = setup.parse(setup_file(base_items, enemies), origin="t.dat")
        placement = mod_edits.placements_for(mod)[0]
        return mod_edits._apply_items(  # pylint: disable=protected-access
            mod, placement, data
        )

    def test_an_added_item_lands_with_spawning_flags(self, tmp_path):
        every = self.build(
            tmp_path,
            {"tables": {"items": "tables/items.csv"}},
            HEADER + "m1,,-300,50,0\n",
        )
        # One shipped item from `base_items`, plus the added one.
        assert len(every) == 2
        found = every[1:]
        assert found[0].position == setup.Position(-300.0, 50.0, 0.0)
        # Defaulted rather than left at zero: 0x10 and 0x1 are required to
        # spawn, so a zeroed item is one that silently never appears.
        assert found[0].flags == setup.Item.SPAWNS
        assert found[0].type == setup.Item.COIN
        assert found[0].spawns

    def test_edits_resolve_against_the_shipped_list_not_a_partly_edited_one(
        self, tmp_path
    ):
        """⚠️ The property that makes row order irrelevant: removing item 0 must
        not renumber the item that another row calls item 1."""
        found = self.build(
            tmp_path,
            {"tables": {"items": "tables/items.csv"}},
            "map,index,x,y,z,clear\nm1,0,,,,true\nm1,1,999,0,0,\n",
            base_items=((1, 1, 1), (2, 2, 2), (3, 3, 3)),
        )
        assert [item.position.as_tuple() for item in found] == [
            (999.0, 0.0, 0.0),
            (3.0, 3.0, 3.0),
        ]

    def test_additions_land_after_survivors_whatever_the_row_order(self, tmp_path):
        found = self.build(
            tmp_path,
            {"tables": {"items": "tables/items.csv"}},
            "map,index,x,y,z\nm1,,-1,-1,-1\nm1,0,9,9,9\n",
            base_items=((1, 1, 1), (2, 2, 2)),
        )
        assert [item.position.as_tuple() for item in found] == [
            (9.0, 9.0, 9.0),
            (2.0, 2.0, 2.0),
            (-1.0, -1.0, -1.0),
        ]

    def test_an_index_past_the_end_says_how_many_there_are(self, tmp_path):
        with pytest.raises(mod_edits.EditError, match=r"places 2 item\(s\)"):
            self.build(
                tmp_path,
                {"tables": {"items": "tables/items.csv"}},
                HEADER + "m1,5,1,2,3\n",
                base_items=((1, 1, 1), (2, 2, 2)),
            )

    def test_editing_keeps_the_fields_a_row_does_not_mention(self, tmp_path):
        found = self.build(
            tmp_path,
            {"setup": {"m1": {"items": [{"index": 0, "flags": 0}]}}},
            base_items=((7, 8, 9),),
        )
        assert found[0].position.as_tuple() == (7.0, 8.0, 9.0)
        assert not found[0].spawns


class TestCreatingASectionIsRefused:
    """⛔ **It hangs the game** (D127), measured on `he1_01`.

    D126 argued it should work: the game reads `itemCount` at 0x2BC4 whatever
    the file's length, and for the 213 maps ending exactly there it lands on
    zeroed padding, so a real count should read the same way. Three coins were
    written -- a section byte-for-byte the shape `he1_03` ships -- and the map
    never rendered. The reasoning was sound and the conclusion was wrong.

    Refused rather than warned, because the artifact is a disc that hangs.
    """

    def test_a_map_with_no_section_refuses_an_addition(self, tmp_path):
        mod = a_mod(
            tmp_path / "m",
            {"tables": {"items": "tables/items.csv"}},
            HEADER + "m1,,-300,50,0\n",
        )
        data = setup.parse(setup_file(), origin="t.dat")
        assert not data.has_item_section

        placement = mod_edits.placements_for(mod)[0]
        with pytest.raises(mod_edits.EditError) as caught:
            mod_edits._apply_items(mod, placement, data)  # pylint: disable=protected-access
        message = str(caught.value)
        assert "ships no item section" in message
        # Says how to find out whether a map is one of the 14 that can.
        assert "bleck setup show" in message

    def test_a_map_that_ships_items_still_accepts_them(self, tmp_path):
        """The refusal is about *creating* a section, not about items."""
        mod = a_mod(
            tmp_path / "m",
            {"tables": {"items": "tables/items.csv"}},
            HEADER + "m1,,-300,50,0\n",
        )
        data = setup.parse(setup_file(items=((1, 1, 1),)), origin="t.dat")
        placement = mod_edits.placements_for(mod)[0]
        found = mod_edits._apply_items(mod, placement, data)  # pylint: disable=protected-access
        assert len(found) == 2

    def test_growing_an_existing_section_is_allowed_and_silent(self, tmp_path):
        """✅ D129 measured it: `he1_03` ships 5 coins, was given 7, and reached
        gameplay. It warned until then; a warning on every legitimate edit is
        noise once the answer is known."""
        mod = a_mod(
            tmp_path / "m",
            {"tables": {"items": "tables/items.csv"}},
            HEADER + "m1,,-300,50,0\n",
        )
        data = setup.parse(setup_file(items=((1, 1, 1),)), origin="t.dat")
        build = mod_edits.PlacementBuild(
            mod=mod.name,
            map_name="m1",
            output=tmp_path,
            also_wrote=tmp_path,
            applied=0,
            used_before=0,
            used_after=0,
        )
        assert not build.warnings
        placement = mod_edits.placements_for(mod)[0]
        found = mod_edits._apply_items(mod, placement, data)  # pylint: disable=protected-access
        assert len(found) == 2

    def test_more_than_the_game_can_load_is_refused(self, tmp_path):
        """⚠️ 512 is a hard ceiling read out of the DOL (D128): the loader
        allocates 8192 bytes and memcpys the file's own count into it with
        nothing clamping it, so a longer list overruns rather than truncates."""
        rows = "".join(f"m1,,{n},0,0\n" for n in range(setup.MAX_ITEMS + 1))
        mod = a_mod(
            tmp_path / "m", {"tables": {"items": "tables/items.csv"}}, HEADER + rows
        )
        data = setup.parse(setup_file(items=((1, 1, 1),)), origin="t.dat")
        placement = mod_edits.placements_for(mod)[0]
        with pytest.raises(mod_edits.EditError, match="at most 512"):
            mod_edits._apply_items(mod, placement, data)  # pylint: disable=protected-access

    def test_exactly_the_ceiling_is_allowed(self, tmp_path):
        """Off-by-one guard: 512 fits the allocation exactly."""
        rows = "".join(f"m1,,{n},0,0\n" for n in range(setup.MAX_ITEMS - 1))
        mod = a_mod(
            tmp_path / "m", {"tables": {"items": "tables/items.csv"}}, HEADER + rows
        )
        data = setup.parse(setup_file(items=((1, 1, 1),)), origin="t.dat")
        placement = mod_edits.placements_for(mod)[0]
        found = mod_edits._apply_items(mod, placement, data)  # pylint: disable=protected-access
        assert len(found) == setup.MAX_ITEMS

    def test_a_size_preserving_edit_moves_the_item(self, tmp_path):
        mod = a_mod(
            tmp_path / "m",
            {"tables": {"items": "tables/items.csv"}},
            "map,index,x,y,z\nm1,0,-300,50,0\n",
        )
        data = setup.parse(setup_file(items=((1, 1, 1),)), origin="t.dat")
        placement = mod_edits.placements_for(mod)[0]
        found = mod_edits._apply_items(mod, placement, data)  # pylint: disable=protected-access
        assert len(found) == 1
        assert found[0].position == setup.Position(-300.0, 50.0, 0.0)


class TestTheManifestSide:
    def parse(self, body: dict) -> mod_manifest.Manifest:
        return mod_manifest.Manifest.from_json(
            json.dumps({"schema": 1, "name": "m", **body}), source="test"
        )

    def test_an_items_only_mod_counts_as_declaring_placements(self):
        """⛔ The D126 bug: `has_placements` gates the whole placement build, so
        a kind missing from it generated nothing while still reporting
        "chain OK" -- a silent no-op, not a failure."""
        assert self.parse({"tables": {"items": "tables/items.csv"}}).has_placements

    def test_every_placement_kind_is_covered(self):
        """Guards the enumeration itself: a new placement kind that nobody adds
        to `PLACEMENT_KINDS` is skipped silently, so failing here is the point."""
        for kind in mod_manifest.PLACEMENT_KINDS:
            manifest = self.parse({"tables": {str(kind): "t.csv"}})
            assert manifest.has_placements, kind

    def test_the_short_setup_form_still_means_enemies(self):
        found = self.parse({"setup": {"m1": [{"slot": 3, "template": 2}]}})
        assert found.setup[0].edits[0].slot == 3
        assert found.setup[0].items == []

    def test_the_long_form_carries_both(self):
        found = self.parse(
            {
                "setup": {
                    "m1": {
                        "enemies": [{"slot": 3, "template": 2}],
                        "items": [{"index": 0, "clear": True}],
                    }
                }
            }
        )
        assert found.setup[0].edits[0].slot == 3
        assert found.setup[0].items[0].clear

    def test_a_map_with_no_items_round_trips_as_a_bare_list(self):
        """The long form is not an upgrade: promoting every map to it would
        rewrite manifests that never mention items."""
        original = self.parse({"setup": {"m1": [{"slot": 3, "template": 2}]}})
        assert json.loads(original.to_json())["setup"]["m1"] == [
            {"slot": 3, "template": 2}
        ]

    def test_a_map_with_items_round_trips_as_the_long_form(self):
        original = self.parse(
            {"setup": {"m1": {"enemies": [], "items": [{"index": 1, "clear": True}]}}}
        )
        again = mod_manifest.Manifest.from_json(original.to_json())
        assert again.setup == original.setup
        assert json.loads(original.to_json())["setup"]["m1"]["items"] == [
            {"index": 1, "clear": True}
        ]

    def test_a_typo_in_the_long_form_is_named(self):
        with pytest.raises(ManifestError, match=r"unknown key\(s\) enemys"):
            self.parse({"setup": {"m1": {"enemys": []}}})

    def test_inline_and_table_refuse_the_same_things(self):
        with pytest.raises(ManifestError, match="setupItemTemplates"):
            self.parse({"setup": {"m1": {"items": [{"index": 0, "type": 1}]}}})
        with pytest.raises(ManifestError, match="'clear' needs an 'index'"):
            self.parse({"setup": {"m1": {"items": [{"clear": True}]}}})


class TestMergingWithEnemies:
    def test_both_kinds_of_table_reach_one_map(self, tmp_path):
        """⚠️ Both end up in a single generated `.dat`, so they must merge into
        one `MapPlacements` -- two would mean the second file overwrote the
        first."""
        root = tmp_path / "both"
        root.mkdir(parents=True)
        (root / "tables").mkdir()
        (root / "tables" / "items.csv").write_text(HEADER + "m1,,1,2,3\n")
        (root / "tables" / "enemies.csv").write_text("map,slot,template\nm1,3,2\n")
        (root / "mod.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": "both",
                    "tables": {
                        "items": "tables/items.csv",
                        "enemies": "tables/enemies.csv",
                    },
                }
            )
        )
        mod = registry.Mod(manifest=mod_manifest.read(root), root=root)
        found = mod_edits.placements_for(mod)
        assert len(found) == 1
        assert found[0].map_name == "m1"
        assert len(found[0].edits) == 1
        assert len(found[0].items) == 1

    def test_the_same_item_declared_twice_is_refused_naming_both(self, tmp_path):
        mod = a_mod(
            tmp_path / "clash",
            {
                "setup": {"m1": {"items": [{"index": 0, "flags": 0}]}},
                "tables": {"items": "tables/items.csv"},
            },
            HEADER + "m1,0,1,2,3\n",
        )
        with pytest.raises(mod_edits.EditError) as caught:
            mod_edits.placements_for(mod)
        message = str(caught.value)
        assert "item 0 of m1 is declared twice" in message
        assert "mod.json setup.m1" in message
        assert "tables/items.csv:2" in message

    def test_two_added_items_are_two_items_not_a_collision(self, tmp_path):
        """Deduplicating adds would make a table of thirty coins place fewer."""
        mod = a_mod(
            tmp_path / "many",
            {"tables": {"items": "tables/items.csv"}},
            HEADER + "m1,,1,2,3\nm1,,4,5,6\n",
        )
        assert len(mod_edits.placements_for(mod)[0].items) == 2
