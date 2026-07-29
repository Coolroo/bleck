"""CSV placement tables — `tables/enemies.csv` as an alternative to inline JSON.

Two properties carry the weight:

- a table and an inline `setup` block mean **exactly** the same thing, so the
  bytes a build produces must not depend on which one an author wrote;
- every refusal names the file and the line, because a table is only worth
  having once there are more rows than anyone wants to count.
"""

from __future__ import annotations

import argparse
import json
import struct

import pytest

from bleck.cli.commands import mods as mods_cli
from bleck.cli.commands import placement as placement_cli
from bleck.formats import setup, tables
from bleck.mods import manifest as mod_manifest
from bleck.mods import registry
from bleck.mods.build import edits as mod_edits
from bleck.mods.manifest import ManifestError

# --- fixtures ---------------------------------------------------------------

#: Offsets a shipped enemy sets and a bare one does not (D122, D123).
UNDOCUMENTED = {0x14: 0xDC, 0x18: 0x12C, 0x68: 2}


def shipped(template: int, position=(1.0, 2.0, 3.0)) -> bytes:
    """A v6 entry as the disc writes one: the documented fields *and* the three
    undocumented values every used slot on `he1_01` carries."""
    raw = bytearray(setup.STRIDE[6])
    struct.pack_into(">3fi", raw, 0, *position, template)
    for offset, value in UNDOCUMENTED.items():
        struct.pack_into(">i", raw, offset, value)
    return bytes(raw)


def setup_file(slots) -> bytes:
    """A synthetic v6 setup file. `slots` is {index: 112-byte entry}."""
    out = bytearray(struct.pack(">HH", 6, 0))
    for index in range(setup.ENEMY_SLOTS):
        out += slots.get(index, bytes(setup.STRIDE[6]))
    return bytes(out)


def parse(text: str, source: str = "tables/enemies.csv") -> tables.Table:
    return tables.parse(text, source)


def rows(text: str) -> list[tables.TableRow]:
    return parse(text).rows


HEADER = "map,slot,template,x,y,z\n"


def a_mod(root, body: dict, table: str | None = None) -> registry.Mod:
    """A mod on disk: a manifest, and optionally the table it declares."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.json").write_text(
        json.dumps({"schema": 1, "name": root.name, **body}), encoding="utf-8"
    )
    if table is not None:
        (root / "tables").mkdir(exist_ok=True)
        (root / "tables" / "enemies.csv").write_text(table, encoding="utf-8")
    return registry.Mod(manifest=mod_manifest.read(root), root=root)


class TestBoundToOneMap:
    """A mod reworking one level wants a file per map and no column repeating
    the filename. `"tables": {"n": {"path": ..., "map": ...}}` is that."""

    def test_a_bound_table_needs_no_map_column(self):
        found = tables.parse(
            "slot,template,x,y,z\n3,7,-300,0,0\n", "tables/he1_01.csv", "he1_01"
        )
        assert found.map_name == "he1_01"
        assert [row.map_name for row in found.rows] == ["he1_01"]

    def test_a_bound_table_may_not_also_carry_one(self):
        with pytest.raises(tables.TableError) as caught:
            tables.parse(HEADER + "he1_01,3,7,0,0,0\n", "t.csv", "he1_01")
        message = str(caught.value)
        assert "bound to 'he1_01'" in message
        # Says both ways out, since either is a reasonable thing to have meant.
        assert "Drop the column" in message

    def test_an_unbound_table_still_requires_the_column(self):
        with pytest.raises(tables.TableError, match="missing required column"):
            tables.parse("slot,template\n3,7\n", "t.csv")

    def test_the_two_forms_declare_the_same_edits(self, tmp_path):
        loose = a_mod(
            tmp_path / "loose",
            {"tables": {"enemies": "tables/enemies.csv"}},
            HEADER + "he1_01,3,2,-300,0,0\n",
        )
        bound = a_mod(
            tmp_path / "bound",
            {"tables": {"enemies": {"path": "tables/enemies.csv", "map": "he1_01"}}},
            "slot,template,x,y,z\n3,2,-300,0,0\n",
        )
        assert mod_edits.placements_for(bound) == mod_edits.placements_for(loose)

    def test_two_bound_tables_cover_two_maps(self, tmp_path):
        root = tmp_path / "two"
        mod = a_mod(
            root,
            {
                "tables": {
                    "enemies": [
                        {"path": "tables/he1_01.csv", "map": "he1_01"},
                        {"path": "tables/he2_01.csv", "map": "he2_01"},
                    ]
                }
            },
        )
        (root / "tables").mkdir(exist_ok=True)
        for name in ("he1_01", "he2_01"):
            (root / "tables" / f"{name}.csv").write_text(
                "slot,template\n3,2\n", encoding="utf-8"
            )
        found = mod_edits.placements_for(mod)
        assert sorted(place.map_name for place in found) == ["he1_01", "he2_01"]

    def test_the_binding_round_trips_through_the_manifest(self):
        original = mod_manifest.Manifest.from_json(
            json.dumps(
                {
                    "schema": 1,
                    "name": "m",
                    "tables": {"enemies": {"path": "tables/he1_01.csv", "map": "he1_01"}},
                }
            )
        )
        again = mod_manifest.Manifest.from_json(original.to_json())
        assert again.tables == original.tables
        assert again.tables[0].map_name == "he1_01"

    def test_an_unbound_table_stays_a_bare_string(self):
        manifest = mod_manifest.Manifest(
            name="m",
            tables=[
                mod_manifest.TableRef(kind=mod_manifest.TableKind.ENEMIES, path="t.csv")
            ],
        )
        assert json.loads(manifest.to_json())["tables"] == {"enemies": "t.csv"}

    def test_a_typo_in_the_declaration_is_named(self):
        with pytest.raises(ManifestError, match="unknown key\\(s\\) mapp"):
            mod_manifest.Manifest.from_json(
                json.dumps(
                    {
                        "schema": 1,
                        "name": "m",
                        "tables": {"enemies": {"path": "t.csv", "mapp": "he1_01"}},
                    }
                )
            )


class TestTheKeyIsAKind:
    """The key says what a table's rows describe. It was briefly a free label,
    and every declared table was read as enemy placements whatever it was
    called -- so `"items"` would have spawned enemies (D125)."""

    def parse(self, body: dict) -> mod_manifest.Manifest:
        return mod_manifest.Manifest.from_json(
            json.dumps({"schema": 1, "name": "m", **body}), source="test"
        )

    def test_a_label_is_refused_and_told_what_the_key_means(self):
        with pytest.raises(ManifestError) as caught:
            self.parse({"tables": {"lineland": "tables/he1_01.csv"}})
        message = str(caught.value)
        assert "unknown table kind 'lineland'" in message
        # The fix an author reaching for a label actually wants is the bound
        # form, so the message spells it rather than only saying no.
        assert '"map": "he1_01"' in message

    def test_a_planned_kind_says_unbuilt_rather_than_misspelled(self):
        """`items` and `doors` are the design, so "unknown" would read as a typo
        and send someone hunting for the right spelling of a thing that is not
        there."""
        for kind in mod_manifest.PLANNED_KINDS:
            with pytest.raises(ManifestError, match="not built yet"):
                self.parse({"tables": {kind: "tables/x.csv"}})

    def test_several_tables_share_one_kind(self):
        found = self.parse({"tables": {"enemies": ["a.csv", "b.csv"]}})
        assert [ref.path for ref in found.tables] == ["a.csv", "b.csv"]
        assert {ref.kind for ref in found.tables} == {mod_manifest.TableKind.ENEMIES}

    def test_a_list_round_trips_as_a_list_and_a_lone_table_as_a_scalar(self):
        """A one-element list would rewrite a hand-edited `mod.json`, and
        `bleck setup apply` writes that file back."""
        many = self.parse({"tables": {"enemies": ["a.csv", "b.csv"]}})
        assert json.loads(many.to_json())["tables"] == {"enemies": ["a.csv", "b.csv"]}
        one = self.parse({"tables": {"enemies": ["a.csv"]}})
        assert json.loads(one.to_json())["tables"] == {"enemies": "a.csv"}

    def test_the_kind_prints_as_itself_in_a_message(self):
        """`StrEnum`, so an error says `tables.enemies`, not
        `tables.TableKind.ENEMIES` (D99)."""
        kind = mod_manifest.TableKind.ENEMIES
        assert f"tables.{kind}" == "tables.enemies"

    def test_only_enemy_tables_become_placements(self, tmp_path):
        """The seam items and doors plug into. `tables_of` is what `edits.py`
        asks; iterating `tables` is the bug this replaced."""
        mod = a_mod(
            tmp_path / "kinds",
            {"tables": {"enemies": "tables/enemies.csv"}},
            HEADER + "he1_01,3,2,-300,0,0\n",
        )
        enemies = mod.manifest.tables_of(mod_manifest.TableKind.ENEMIES)
        assert [ref.path for ref in enemies] == ["tables/enemies.csv"]
        assert (
            mod.manifest.tables_of(mod_manifest.TableKind.ENEMIES) == mod.manifest.tables
        )


# --- the file's shape -------------------------------------------------------


class TestHeader:
    def test_the_header_names_the_columns_in_any_order(self):
        found = rows("slot,map,template\n3,he1_01,7\n")
        assert found[0].map_name == "he1_01"
        assert found[0].slot == 3 and found[0].template == 7

    def test_an_unknown_column_names_itself_and_the_known_ones(self):
        with pytest.raises(tables.TableError) as caught:
            parse("map,slot,tempalte\n")
        message = str(caught.value)
        assert "unknown column 'tempalte'" in message
        # And says what it could have been, rather than only that it is wrong.
        assert "template" in message and "copy_from" in message

    def test_a_missing_required_column_is_refused(self):
        with pytest.raises(tables.TableError, match="missing required column"):
            parse("map,template\nhe1_01,7\n")

    def test_a_repeated_column_is_refused(self):
        with pytest.raises(tables.TableError, match="appears twice"):
            parse("map,slot,slot\n")

    def test_a_trailing_comma_is_a_nameless_column_not_a_mystery(self):
        with pytest.raises(tables.TableError, match="column 3 has no name"):
            parse("map,slot,\n")

    def test_a_file_with_no_header_says_so(self):
        with pytest.raises(tables.TableError, match="no header row"):
            parse("# nothing but a comment\n\n")

    def test_the_header_reports_its_own_line_number(self):
        with pytest.raises(tables.TableError, match=r"enemies\.csv:3:"):
            parse("# a comment\n\nmap,slot,nope\n")


class TestCommentsAndBlanks:
    """CSV has no comments. Skipping `#` lines is an extension, and the reason
    the line numbers are tracked separately from the parsed records."""

    def test_comments_and_blank_lines_are_skipped(self):
        found = rows("# why\n\nmap,slot,template\n\n# and\nhe1_01,3,7\n")
        assert len(found) == 1 and found[0].template == 7

    def test_a_row_reports_its_line_in_the_file_not_among_the_records(self):
        found = rows("# one\n# two\nmap,slot,template\n\nhe1_01,3,7\n")
        assert found[0].line == 5

    def test_an_error_names_the_file_and_the_line(self):
        with pytest.raises(tables.TableError, match=r"enemies\.csv:4:"):
            parse("map,slot,template\nhe1_01,3,7\n\nhe1_01,900,7\n")


# --- the columns ------------------------------------------------------------


class TestPosition:
    def test_all_three_axes_land(self):
        found = rows(HEADER + "he1_01,3,7,-300,0,12.5\n")
        assert found[0].position.as_tuple() == (-300.0, 0.0, 12.5)

    def test_two_axes_is_an_error_not_a_silent_zero(self):
        with pytest.raises(tables.TableError) as caught:
            parse(HEADER + "he1_01,3,7,-300,0,\n")
        assert "all three of x, y and z" in str(caught.value)
        assert "z is empty" in str(caught.value)

    def test_no_axes_at_all_leaves_the_slot_where_it_is(self):
        assert rows(HEADER + "he1_01,3,7,,,\n")[0].position is None

    def test_a_table_that_names_only_two_axes_is_refused_at_the_header(self):
        # Caught before any row, so an empty table cannot hide it.
        with pytest.raises(tables.TableError, match="has no z column"):
            parse("map,slot,x,y\n")

    def test_a_position_that_is_not_a_number_says_which_column(self):
        with pytest.raises(tables.TableError, match=r"'y' must be a number"):
            parse(HEADER + "he1_01,3,7,-300,over there,0\n")


class TestRows:
    def test_a_row_that_changes_nothing_is_refused(self):
        with pytest.raises(tables.TableError, match="changes nothing"):
            parse(HEADER + "he1_01,3,,,,\n")

    def test_a_slot_outside_the_array_is_refused(self):
        with pytest.raises(tables.TableError, match="out of range"):
            parse(HEADER + "he1_01,100,7,,,\n")

    def test_a_row_without_a_map_is_refused(self):
        with pytest.raises(tables.TableError, match="'map' is empty"):
            parse(HEADER + ",3,7,,,\n")

    def test_clear_is_exclusive(self):
        with pytest.raises(tables.TableError, match="both clears and sets"):
            parse("map,slot,template,clear\nhe1_01,3,7,true\n")

    def test_clear_reads_as_a_flag(self):
        assert rows("map,slot,clear\nhe1_01,3,yes\n")[0].clear
        with pytest.raises(tables.TableError, match="must be true or false"):
            parse("map,slot,clear\nhe1_01,3,maybe\n")

    def test_a_short_row_omits_optional_columns(self):
        # Trailing cells left off is ordinary hand-editing.
        assert rows(HEADER + "he1_01,3,7\n")[0].position is None

    def test_a_long_row_is_refused_rather_than_truncated(self):
        with pytest.raises(tables.TableError, match="7 values for 6 columns"):
            parse(HEADER + "he1_01,3,7,0,0,0,extra\n")

    def test_copying_a_slot_onto_itself_is_refused(self):
        with pytest.raises(tables.TableError, match="this row's own"):
            parse("map,slot,copy_from\nhe1_01,3,3\n")


# --- naming an enemy --------------------------------------------------------


class TestTemplateNames:
    """A number always works. A name is the readable form, and resolves through
    the committed NPC catalog exactly as `item:` names do."""

    def catalog(self, monkeypatch, templates, tribes):
        names = setup.NpcNames(templates=templates, tribes=tribes)
        monkeypatch.setattr(setup, "catalog", lambda: names)
        return names

    def test_a_number_needs_no_catalog(self, monkeypatch):
        self.catalog(monkeypatch, [], [])
        assert rows(HEADER + "he1_01,3,7,,,\n")[0].template == 7

    def test_a_unique_name_resolves(self, monkeypatch):
        self.catalog(
            monkeypatch,
            [{"id": 0, "tribe": 0}, {"id": 1, "tribe": 1}],
            [
                {"name": "e_kuribo", "english": "Goomba"},
                {"name": "e_octa2", "english": "Squiglet"},
            ],
        )
        assert rows(HEADER + "he1_01,3,Squiglet,,,\n")[0].template == 1

    def test_case_dashes_and_spaces_do_not_matter(self, monkeypatch):
        self.catalog(
            monkeypatch,
            [{"id": 0, "tribe": 0}],
            [{"name": "e_dokan", "english": "Koopa Troopa"}],
        )
        assert rows(HEADER + "he1_01,3,koopa-troopa,,,\n")[0].template == 0

    def test_the_model_name_is_a_second_tier(self, monkeypatch):
        self.catalog(
            monkeypatch,
            [{"id": 0, "tribe": 0}],
            [{"name": "e_octa2", "english": "Squiglet"}],
        )
        assert rows(HEADER + "he1_01,3,e_octa2,,,\n")[0].template == 0

    def test_an_ambiguous_name_refuses_and_lists_the_candidates(self, monkeypatch):
        self.catalog(
            monkeypatch,
            [{"id": 0, "tribe": 0}, {"id": 1, "tribe": 0}],
            [{"name": "e_kuribo", "english": "Goomba"}],
        )
        with pytest.raises(tables.TableError) as caught:
            parse(HEADER + "he1_01,3,Goomba,,,\n")
        message = str(caught.value)
        assert "names 2 templates (0, 1)" in message
        # Refuses rather than picking, and says how to be specific.
        assert "Write the number instead" in message
        assert "bleck setup show" in message

    def test_an_unknown_name_suggests_the_near_misses(self, monkeypatch):
        self.catalog(
            monkeypatch,
            [{"id": 0, "tribe": 0}],
            [{"name": "e_kuribo", "english": "Goomba"}],
        )
        with pytest.raises(tables.TableError) as caught:
            parse(HEADER + "he1_01,3,Gooba,,,\n")
        message = str(caught.value)
        assert "no enemy named 'Gooba'" in message
        assert "Did you mean: goomba?" in message

    def test_a_build_with_no_catalog_says_to_use_a_number(self, monkeypatch):
        self.catalog(monkeypatch, [], [])
        with pytest.raises(tables.TableError, match="no NPC catalog"):
            parse(HEADER + "he1_01,3,Goomba,,,\n")


@pytest.mark.skipif(not setup.NPC_CATALOG.is_file(), reason="no NPC catalog")
class TestAgainstTheCommittedCatalog:
    """The measured shape of the name space, pinned so a regenerated catalog
    that changes it is noticed rather than absorbed."""

    def test_a_unique_name_resolves_to_its_template(self):
        assert setup.catalog().resolve("Squiglet").species.template == 250

    def test_goomba_is_ambiguous_across_35_templates(self):
        # 386 distinct English names cover 423 named templates; 382 are unique.
        match = setup.catalog().resolve("goomba")
        assert not match.found
        assert len(match.ambiguous) == 35
        assert match.candidates.startswith("0, 1, 2, 7,")

    def test_only_four_names_are_ambiguous_at_all(self):
        found = [
            name
            for name in ("goomba", "koopa troopa", "mimi stg2", "gloomba")
            if setup.catalog().resolve(name).ambiguous
        ]
        assert found == ["goomba", "koopa troopa", "mimi stg2", "gloomba"]

    def test_a_nonsense_name_resolves_to_nothing(self):
        assert not setup.catalog().resolve("zzz not an enemy").found


# --- the manifest side ------------------------------------------------------


class TestManifest:
    def parse(self, body: dict) -> mod_manifest.Manifest:
        return mod_manifest.Manifest.from_json(
            json.dumps({"schema": 1, "name": "m", **body}), source="test"
        )

    def test_declared_tables_round_trip(self):
        original = self.parse({"tables": {"enemies": "tables/enemies.csv"}})
        again = mod_manifest.Manifest.from_json(original.to_json())
        assert again.tables == original.tables
        assert again.tables[0].kind is mod_manifest.TableKind.ENEMIES
        assert again.tables[0].path == "tables/enemies.csv"

    def test_a_mod_with_no_tables_omits_the_key(self):
        # Like `code` and `setup`: absent, not an empty object.
        assert "tables" not in json.loads(self.parse({}).to_json())

    def test_a_windows_path_is_stored_posix_style(self):
        found = self.parse({"tables": {"enemies": "tables\\enemies.csv"}})
        assert found.tables[0].path == "tables/enemies.csv"

    def test_a_table_outside_the_mod_is_refused(self):
        with pytest.raises(ManifestError, match="stay inside the mod"):
            self.parse({"tables": {"enemies": "../elsewhere.csv"}})

    def test_tables_alone_counts_as_declaring_placements(self):
        assert self.parse({"tables": {"enemies": "tables/enemies.csv"}}).has_placements

    def test_copy_from_round_trips_inline_too(self):
        """Inline and table say the same things, so `copy_from` is spellable in
        both -- otherwise exporting a mod would quietly drop it."""
        original = self.parse(
            {"setup": {"he1_01": [{"slot": 3, "copy_from": 0, "template": 2}]}}
        )
        again = mod_manifest.Manifest.from_json(original.to_json())
        assert again.setup == original.setup
        assert again.setup[0].edits[0].copy_from == 0

    def test_copying_the_edited_slot_is_refused_inline(self):
        with pytest.raises(ManifestError, match="copies nothing"):
            self.parse({"setup": {"he1_01": [{"slot": 3, "copy_from": 3}]}})


# --- merging the two sources ------------------------------------------------


class TestMergingSources:
    def test_a_table_produces_the_same_placements_as_inline(self, tmp_path):
        inline = a_mod(
            tmp_path / "inline",
            {"setup": {"he1_01": [{"slot": 3, "template": 2, "position": [-300, 0, 0]}]}},
        )
        tabled = a_mod(
            tmp_path / "tabled",
            {"tables": {"enemies": "tables/enemies.csv"}},
            HEADER + "he1_01,3,2,-300,0,0\n",
        )
        assert mod_edits.placements_for(tabled) == mod_edits.placements_for(inline)

    def test_both_sources_merge_into_one_map(self, tmp_path):
        mod = a_mod(
            tmp_path / "both",
            {
                "setup": {"he1_01": [{"slot": 0, "template": 9}]},
                "tables": {"enemies": "tables/enemies.csv"},
            },
            HEADER + "he1_01,3,2,-300,0,0\n",
        )
        found = mod_edits.placements_for(mod)
        assert len(found) == 1
        assert sorted(edit.slot for edit in found[0].edits) == [0, 3]

    def test_the_same_slot_in_both_sources_is_refused_naming_both(self, tmp_path):
        mod = a_mod(
            tmp_path / "clash",
            {
                "setup": {"he1_01": [{"slot": 3, "template": 9}]},
                "tables": {"enemies": "tables/enemies.csv"},
            },
            HEADER + "he1_01,3,2,-300,0,0\n",
        )
        with pytest.raises(mod_edits.EditError) as caught:
            mod_edits.placements_for(mod)
        message = str(caught.value)
        assert "slot 3 of he1_01 is declared twice" in message
        assert "mod.json setup.he1_01" in message
        assert "tables/enemies.csv:2" in message

    def test_a_declared_table_that_is_missing_says_where_it_was_declared(self, tmp_path):
        mod = a_mod(tmp_path / "absent", {"tables": {"enemies": "tables/enemies.csv"}})
        with pytest.raises(mod_edits.EditError, match=r"no table at tables/enemies\.csv"):
            mod_edits.placements_for(mod)


class TestTheEditingLoop:
    """`bleck setup edits` reads the inline block; a table is a file. Saying so
    is the whole point -- a mod that declares only tables would otherwise print
    "declares no placement changes" while declaring plenty."""

    def test_a_mod_with_only_tables_is_not_reported_as_declaring_nothing(
        self, monkeypatch, tmp_path, capsys
    ):
        mod = a_mod(
            tmp_path / "tabled",
            {"tables": {"enemies": {"path": "tables/enemies.csv", "map": "he1_01"}}},
            "slot,template\n3,2\n",
        )
        monkeypatch.setattr(registry, "load", lambda: registry.Registry(tmp_path, [mod]))
        assert placement_cli.cmd_edits(argparse.Namespace(name="tabled", json=False)) == 0
        printed = capsys.readouterr().out
        assert "declares no placement changes" not in printed
        assert "tables/enemies.csv (map he1_01)" in printed


class TestScaffolding:
    """`bleck mod new` writes the table and the line in `mod.json` that points
    at it, so the feature is discoverable without reading the docs first."""

    def create(self, monkeypatch, tmp_path, name="fresh"):
        base = tmp_path / "eu0"
        base.mkdir()
        monkeypatch.setattr(registry, "mods_root", lambda: tmp_path / "mods")
        monkeypatch.setattr(mods_cli, "_base", lambda: base)
        assert (
            mods_cli.cmd_new(
                argparse.Namespace(name=name, description="", author="", force=False)
            )
            == 0
        )
        return tmp_path / "mods" / name

    def test_it_writes_a_table_and_points_the_manifest_at_it(self, monkeypatch, tmp_path):
        root = self.create(monkeypatch, tmp_path)
        assert (root / mods_cli.ENEMY_TABLE).is_file()
        assert mod_manifest.read(root).tables[0].path == mods_cli.ENEMY_TABLE

    def test_the_scaffold_is_a_comment_and_a_header_and_nothing_else(
        self, monkeypatch, tmp_path
    ):
        root = self.create(monkeypatch, tmp_path)
        text = (root / mods_cli.ENEMY_TABLE).read_text(encoding="utf-8")
        assert text.splitlines()[0].startswith("#")
        assert not tables.parse(text, mods_cli.ENEMY_TABLE).rows

    def test_the_scaffolded_header_names_every_column(self, monkeypatch, tmp_path):
        root = self.create(monkeypatch, tmp_path)
        text = (root / mods_cli.ENEMY_TABLE).read_text(encoding="utf-8")
        assert text.splitlines()[1] == ",".join(tables.COLUMNS)


# --- applying a table to a real setup file ----------------------------------


class TestApplyingATable:
    """Through `_apply_map`, so the orphan guard and `copy_from` are exercised
    where a build would exercise them rather than in isolation."""

    def apply(self, monkeypatch, tmp_path, body, table, base_slots):
        mod = a_mod(tmp_path / "m", body, table)
        raw = setup_file(base_slots)
        monkeypatch.setattr(mod_edits, "_archive_member", lambda _base, _map: raw)
        placement = mod_edits.placements_for(mod)[0]
        built = mod_edits._apply_map(  # pylint: disable=protected-access
            mod, placement, tmp_path
        )
        return setup.parse(built.also_wrote.read_bytes())

    def test_a_table_row_adds_an_enemy(self, monkeypatch, tmp_path):
        found = self.apply(
            monkeypatch,
            tmp_path,
            {"tables": {"enemies": "tables/enemies.csv"}},
            HEADER + "he1_01,3,2,-300,0,0\n",
            {index: shipped(1) for index in range(3)},
        )
        assert len(found.used) == 4
        assert found.enemies[3].template == 2
        assert found.enemies[3].position.x == -300.0

    def test_copy_from_carries_the_undocumented_bytes(self, monkeypatch, tmp_path):
        """✅ D123: a bare added enemy has zeros where every shipped one has
        `0xDC`, `0x12C` and `2`, and those reach the live NPC."""
        found = self.apply(
            monkeypatch,
            tmp_path,
            {"tables": {"enemies": "tables/enemies.csv"}},
            "map,slot,template,x,y,z,copy_from\n"
            "he1_01,3,2,-300,0,0,\n"
            "he1_01,4,2,-450,0,0,0\n",
            {index: shipped(1) for index in range(3)},
        )
        bare, copied = found.enemies[3].raw, found.enemies[4].raw
        for offset, value in UNDOCUMENTED.items():
            assert struct.unpack_from(">i", bare, offset)[0] == 0
            assert struct.unpack_from(">i", copied, offset)[0] == value
        # And the declared fields still win over the copy.
        assert found.enemies[4].template == 2
        assert found.enemies[4].position.x == -450.0

    def test_copy_from_reads_the_base_not_a_slot_this_table_already_changed(
        self, monkeypatch, tmp_path
    ):
        """Row order must not change what a table means."""
        found = self.apply(
            monkeypatch,
            tmp_path,
            {"tables": {"enemies": "tables/enemies.csv"}},
            "map,slot,template,x,y,z,copy_from\nhe1_01,0,9,,,,\nhe1_01,3,,,,,0\n",
            {index: shipped(1) for index in range(3)},
        )
        assert found.enemies[0].template == 9
        assert found.enemies[3].template == 1  # the base's value, not 9

    def test_copying_an_empty_slot_is_refused(self, monkeypatch, tmp_path):
        with pytest.raises(mod_edits.EditError) as caught:
            self.apply(
                monkeypatch,
                tmp_path,
                {"tables": {"enemies": "tables/enemies.csv"}},
                "map,slot,template,x,y,z,copy_from\nhe1_01,3,2,-300,0,0,50\n",
                {index: shipped(1) for index in range(3)},
            )
        message = str(caught.value)
        assert "copies from slot 50, which is empty" in message
        assert "bleck setup show he1_01" in message

    def test_a_table_that_declares_nothing_builds_nothing(self, tmp_path):
        """What `bleck mod new` scaffolds: a header and no rows. It must be a
        legal state, or a fresh mod would not build."""
        mod = a_mod(
            tmp_path / "fresh",
            {"tables": {"enemies": mods_cli.ENEMY_TABLE}},
            f"# a comment\n{','.join(tables.COLUMNS)}\n",
        )
        assert mod.manifest.has_placements
        assert mod_edits.placements_for(mod) == []

    def test_a_table_row_cannot_orphan_later_slots_either(self, monkeypatch, tmp_path):
        """⛔ The game stops reading setup entries at the first empty one (D79).
        The guard runs on the merged result, so a table row is not a way past it."""
        with pytest.raises(mod_edits.EditError) as caught:
            self.apply(
                monkeypatch,
                tmp_path,
                {"tables": {"enemies": "tables/enemies.csv"}},
                "map,slot,clear\nhe1_01,1,true\n",
                {index: shipped(1) for index in range(3)},
            )
        message = str(caught.value)
        assert "orphan slot(s) 2" in message
        assert "Clear the last used slot" in message
