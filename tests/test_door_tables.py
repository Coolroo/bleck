"""Door tables — `tables/doors.csv`, which are **code**, not placement.

Enemy and coin tables become bytes in a map's setup file. A door row becomes a
`code.patches` entry: one instruction of a script the game already ships,
replaced by a call into the mod. Everything here pins that difference, because
the two look alike in `mod.json` and behave nothing alike.
"""

from __future__ import annotations

import json

import pytest

from bleck.formats import tables
from bleck.mods import manifest as mod_manifest
from bleck.mods import registry
from bleck.mods.code import parts as code_parts
from bleck.mods.manifest import ManifestError

HEADER = "map,index,script,at,expect,call\n"


def rows(text: str, source: str = "tables/doors.csv", bound: str = ""):
    return tables.doors.parse(text, source, bound).rows


def a_mod(root, body: dict, table: str | None = None) -> registry.Mod:
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.json").write_text(
        json.dumps({"schema": 1, "name": root.name, **body}), encoding="utf-8"
    )
    if table is not None:
        (root / "tables").mkdir(exist_ok=True)
        (root / "tables" / "doors.csv").write_text(table, encoding="utf-8")
    return registry.Mod(manifest=mod_manifest.read(root), root=root)


WITH_CODE = {
    "tables": {"doors": "tables/doors.csv"},
    "code": {"sources": ["src"], "target": "eu0"},
}


class TestTheSelectorIsSplitAcrossColumns:
    """`door:he1_01:0:interact` is four things, and an author varies two of
    them. The columns are those, not the string."""

    def test_a_row_rebuilds_the_selector(self):
        found = rows(HEADER + "he1_01,0,interact,0,MULF,on_door\n")[0]
        assert found.selector == "door:he1_01:0:interact"

    def test_script_defaults_to_interact(self):
        """Matching the selector's own default -- the one the player triggers."""
        found = rows("map,index,at,expect,call\nhe1_01,3,0,MULF,f\n")[0]
        assert found.script == "interact"
        assert found.selector == "door:he1_01:3:interact"

    def test_a_bound_table_drops_the_map_column(self):
        found = rows("index,at,expect,call\n3,0,MULF,f\n", bound="he2_08")[0]
        assert found.selector == "door:he2_08:3:interact"

    def test_only_a_doors_three_scripts_are_accepted(self):
        for script in tables.doors.SCRIPTS:
            assert rows(HEADER + f"he1_01,0,{script},0,MULF,f\n")[0].script == script
        with pytest.raises(tables.TableError, match="not one of a door's scripts"):
            rows(HEADER + "he1_01,0,wobble,0,MULF,f\n")


class TestEveryFieldIsLoadBearing:
    """A patch with a missing field is not a partial patch, it is a broken one."""

    @pytest.mark.parametrize("column", ["map", "index", "at", "expect", "call"])
    def test_a_missing_required_column_is_refused(self, column):
        names = [c for c in tables.doors.COLUMNS if c != column]
        header = ",".join(names)
        cells = ",".join("0" if n in ("index", "at") else "x" for n in names)
        with pytest.raises(tables.TableError, match="missing required column"):
            rows(f"{header}\n{cells}\n")

    def test_script_is_the_only_optional_column(self):
        assert tables.doors.OPTIONAL == ("script",)
        # Dropping it parses; every other column is in REQUIRED.
        assert rows("map,index,at,expect,call\nhe1_01,0,0,MULF,f\n")

    def test_an_empty_call_is_refused(self):
        with pytest.raises(tables.TableError, match="'call' is empty"):
            rows(HEADER + "he1_01,0,interact,0,MULF,\n")

    def test_a_negative_index_is_refused(self):
        with pytest.raises(tables.TableError, match="'index' -1 cannot be negative"):
            rows(HEADER + "he1_01,-1,interact,0,MULF,f\n")

    def test_a_negative_offset_is_refused(self):
        with pytest.raises(tables.TableError, match="'at' -4 cannot be negative"):
            rows(HEADER + "he1_01,0,interact,-4,MULF,f\n")

    def test_expect_is_carried_verbatim(self):
        """It is the guard word, in any of the three spellings `build_patch`
        takes -- an opcode name, a name with its argc, or a raw header word."""
        for text in ("MULF", "USER_FUNC 4", "0x0002001A"):
            assert rows(HEADER + f"he1_01,0,interact,0,{text},f\n")[0].expect == text


class TestDoorsAreCodeNotPlacement:
    def test_doors_is_not_a_placement_kind(self):
        """⛔ It must not be: `PLACEMENT_KINDS` drives the setup-file build, and
        a door row produces no setup bytes at all."""
        assert mod_manifest.TableKind.DOORS not in mod_manifest.PLACEMENT_KINDS

    def test_a_doors_table_alone_is_not_a_placement_mod(self, tmp_path):
        mod = a_mod(tmp_path / "d", WITH_CODE, HEADER + "he1_01,0,interact,0,MULF,f\n")
        assert not mod.manifest.has_placements
        assert mod.manifest.has_code

    def test_a_doors_table_without_code_is_refused(self, tmp_path):
        """⚠️ D126's failure shape: `mods_with_code` gates the compile on
        `has_code`, so this would build cleanly and patch nothing."""
        with pytest.raises(ManifestError, match="needs a 'code' block"):
            a_mod(
                tmp_path / "d",
                {"tables": {"doors": "tables/doors.csv"}},
                HEADER + "he1_01,0,interact,0,MULF,f\n",
            )

    def test_doors_is_no_longer_a_planned_kind(self):
        assert "doors" not in mod_manifest.PLANNED_KINDS
        assert mod_manifest.TableKind("doors") is mod_manifest.TableKind.DOORS


class TestBecomingPatches:
    """`door_patches` turns rows back into the same objects an inline
    `code.patches` entry produces, through the same validator."""

    def test_rows_become_patches_with_the_same_target(self, tmp_path):
        mod = a_mod(
            tmp_path / "d",
            WITH_CODE,
            HEADER + "he1_01,0,interact,0,MULF,on_a\nhe1_01,9,init,4,MULF,on_b\n",
        )
        found = code_parts.door_patches(mod)
        assert [item.patch.call for item in found] == ["on_a", "on_b"]
        # `door:` resolves to the MAP whose init script registers the
        # descriptors, with the door itself carried as an index.
        assert found[0].patch.emit_target == "he1_01"
        assert found[0].patch.index == 0
        assert found[1].patch.index == 9

    def test_a_bad_selector_is_refused_by_the_shared_validator(self, tmp_path):
        mod = a_mod(tmp_path / "d", WITH_CODE, HEADER + "he1_01,0,interact,0,NOPE,f\n")
        with pytest.raises(ManifestError):
            code_parts.door_patches(mod)

    def test_an_error_names_the_file_and_line_not_a_patch_index(self, tmp_path):
        """⚠️ "code.patches[3]" is a lie when the patch came from row 4 of a
        CSV, which is what `SourcedPatch` exists to prevent."""
        mod = a_mod(
            tmp_path / "d",
            WITH_CODE,
            HEADER + "he1_01,0,interact,0,MULF,ok\nhe1_01,1,interact,0,BAD_OP,f\n",
        )
        with pytest.raises(ManifestError) as caught:
            code_parts.door_patches(mod)
        assert "tables/doors.csv:3" in str(caught.value)

    def test_a_declared_table_that_is_missing_says_so(self, tmp_path):
        mod = a_mod(tmp_path / "d", WITH_CODE)
        with pytest.raises(code_parts.CodeError, match=r"no table at tables/doors\.csv"):
            code_parts.door_patches(mod)

    def test_no_doors_table_means_no_patches(self, tmp_path):
        mod = a_mod(tmp_path / "d", {"code": {"sources": ["src"], "target": "eu0"}})
        assert not code_parts.door_patches(mod)
