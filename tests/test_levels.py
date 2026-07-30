"""`levels` — one directory per map, holding that map's tables (D145).

Sugar over `tables`, so most of these check that it *is* sugar: a level expands
into exactly the `TableRef`s the long form would have declared, bound the same
way. The rest guard the silent-no-op shapes, because a level that contributes
nothing while the build says "chain OK" is D126 for the third time.
"""

from __future__ import annotations

import json

import pytest

from bleck.mods import manifest as mod_manifest
from bleck.mods import registry
from bleck.mods.manifest import ManifestError, TableKind

ENEMIES = "map,slot,template\nhe1_01,3,2\n"
BOUND_ENEMIES = "slot,template\n3,2\n"


def a_mod(root, body: dict, files: dict[str, str] | None = None) -> registry.Mod:
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.json").write_text(
        json.dumps({"schema": 1, "name": root.name, **body}), encoding="utf-8"
    )
    for relative, text in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return registry.Mod(manifest=mod_manifest.read(root), root=root)


class TestTheDirectoryNameIsTheMapName:
    def test_a_bare_path_binds_to_its_own_directory(self):
        found = mod_manifest.Manifest.from_json(
            json.dumps({"schema": 1, "name": "m", "levels": ["levels/he1_01"]})
        )
        assert found.levels[0].map_name == "he1_01"

    def test_a_directory_not_named_after_a_map_is_refused(self):
        """⚠️ Otherwise every table binds to a map that does not exist, and the
        failure surfaces later as a confusing per-table error."""
        with pytest.raises(ManifestError) as caught:
            mod_manifest.Manifest.from_json(
                json.dumps({"schema": 1, "name": "m", "levels": ["levels/lineland"]})
            )
        message = str(caught.value)
        assert "is not one" in message
        # Says the way out rather than only refusing.
        assert '"map": "he1_01"' in message

    def test_an_explicit_map_allows_any_directory_name(self):
        found = mod_manifest.Manifest.from_json(
            json.dumps(
                {
                    "schema": 1,
                    "name": "m",
                    "levels": [{"path": "levels/lineland", "map": "he1_01"}],
                }
            )
        )
        assert found.levels[0].map_name == "he1_01"

    def test_round_trip_keeps_the_shorthand(self):
        """A directory named after its map stays a bare string; writing the long
        form back would churn a hand-edited manifest for nothing."""
        body = {"schema": 1, "name": "m", "levels": ["levels/he1_01"]}
        again = mod_manifest.Manifest.from_json(
            mod_manifest.Manifest.from_json(json.dumps(body)).to_json()
        )
        assert json.loads(again.to_json())["levels"] == ["levels/he1_01"]


class TestItIsSugarOverTables:
    def test_a_level_expands_into_bound_tables(self, tmp_path):
        mod = a_mod(
            tmp_path / "m",
            {"levels": ["levels/he1_01"]},
            {"levels/he1_01/enemies.csv": BOUND_ENEMIES},
        )
        found = mod.tables_of(TableKind.ENEMIES)
        assert len(found) == 1
        assert found[0].path == "levels/he1_01/enemies.csv"
        assert found[0].map_name == "he1_01"

    def test_declared_tables_and_levels_both_arrive(self, tmp_path):
        mod = a_mod(
            tmp_path / "m",
            {
                "levels": ["levels/he1_01"],
                "tables": {"enemies": "tables/extra.csv"},
            },
            {
                "levels/he1_01/enemies.csv": BOUND_ENEMIES,
                "tables/extra.csv": ENEMIES,
            },
        )
        assert len(mod.tables_of(TableKind.ENEMIES)) == 2

    def test_only_the_kind_asked_for_comes_back(self, tmp_path):
        mod = a_mod(
            tmp_path / "m",
            {"levels": ["levels/he1_01"]},
            {
                "levels/he1_01/enemies.csv": BOUND_ENEMIES,
                "levels/he1_01/coins.csv": "x,y,z\n1,2,3\n",
            },
        )
        assert len(mod.tables_of(TableKind.ENEMIES)) == 1
        assert len(mod.tables_of(TableKind.COINS)) == 1
        assert not mod.tables_of(TableKind.DOORS)

    def test_the_manifest_alone_cannot_see_a_level(self, tmp_path):
        """⚠️ The reason `Mod.tables_of` exists. A caller asking the manifest
        sees a level-organised mod as empty."""
        mod = a_mod(
            tmp_path / "m",
            {"levels": ["levels/he1_01"]},
            {"levels/he1_01/enemies.csv": BOUND_ENEMIES},
        )
        assert not mod.manifest.tables_of(TableKind.ENEMIES)
        assert mod.tables_of(TableKind.ENEMIES)


class TestNothingSilentlyDoesNothing:
    """⛔ D126's shape, hit three times now: a mod that generates nothing while
    the build reports "chain OK"."""

    def test_a_levels_only_mod_counts_as_having_placements(self, tmp_path):
        """`mods_with_placements` gates the whole placement build on this."""
        mod = a_mod(
            tmp_path / "m",
            {"levels": ["levels/he1_01"]},
            {"levels/he1_01/enemies.csv": BOUND_ENEMIES},
        )
        assert mod.has_placements
        # And the manifest cannot answer it, which is why the property moved.
        assert not mod.manifest.has_placements

    def test_a_missing_directory_is_refused(self, tmp_path):
        mod = a_mod(tmp_path / "m", {"levels": ["levels/he1_01"]})
        with pytest.raises(ManifestError, match="no such directory"):
            mod.tables_of(TableKind.ENEMIES)

    def test_an_empty_level_is_refused(self, tmp_path):
        mod = a_mod(
            tmp_path / "m", {"levels": ["levels/he1_01"]}, {"levels/he1_01/notes.txt": ""}
        )
        with pytest.raises(ManifestError, match="contributes nothing"):
            mod.tables_of(TableKind.ENEMIES)

    def test_a_misspelled_table_is_refused_not_ignored(self, tmp_path):
        """`enemys.csv` would be read by nothing and the build would pass."""
        mod = a_mod(
            tmp_path / "m",
            {"levels": ["levels/he1_01"]},
            {"levels/he1_01/enemys.csv": BOUND_ENEMIES},
        )
        with pytest.raises(ManifestError, match="is not a level table"):
            mod.tables_of(TableKind.ENEMIES)

    def test_a_level_doors_table_still_needs_code(self, tmp_path):
        """⚠️ `Manifest.__post_init__` enforces this for a *declared* doors
        table but cannot see a level's, so the rule is applied here too."""
        mod = a_mod(
            tmp_path / "m",
            {"levels": ["levels/he1_01"]},
            {"levels/he1_01/doors.csv": "map,index,at,expect,call\nhe1_01,0,0,MULF,f\n"},
        )
        with pytest.raises(ManifestError, match="needs a 'code' block"):
            mod.tables_of(TableKind.DOORS)

    def test_a_non_csv_file_is_left_alone(self, tmp_path):
        """A README beside the tables is not a typo."""
        mod = a_mod(
            tmp_path / "m",
            {"levels": ["levels/he1_01"]},
            {
                "levels/he1_01/enemies.csv": BOUND_ENEMIES,
                "levels/he1_01/README.md": "why these enemies",
            },
        )
        assert len(mod.tables_of(TableKind.ENEMIES)) == 1
