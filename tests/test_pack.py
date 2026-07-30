"""`.bleck` archives — what they carry, and what they must never carry.

⚠️ The load-bearing property is a **negative**: no game bytes leave the machine
that owns the disc. Most of these tests assert absence, which is exactly the
kind of assertion that passes when the code under test does nothing. So each one
pairs with a positive: the source file that *should* be there.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from bleck.mods import pack, registry
from bleck.mods.errors import ManifestError


def a_mod(
    root: Path,
    name: str,
    overlay: dict[str, bytes] | None = None,
    assets: str | None = None,
):
    """A mod on disk, with whatever overlay files the test needs."""
    where = root / name
    (where / "tables").mkdir(parents=True)
    body = {
        "schema": 1,
        "name": name,
        "version": "0.1.0",
        "description": name,
        "base": "eu0",
        "tables": {"enemies": "tables/enemies.csv"},
    }
    if assets is not None:
        body["assets"] = assets
    (where / "mod.json").write_text(json.dumps(body), encoding="utf-8")
    (where / "tables" / "enemies.csv").write_text(
        "map,slot,template,x,y,z,copy_from\nhe1_01,3,2,0,0,0,0\n", encoding="utf-8"
    )
    for relative, data in (overlay or {}).items():
        target = where / "overlay" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return registry.load(root).require(name)


class TestClassification:
    def test_authored_files_are_sources(self, tmp_path: Path):
        plan = pack.plan(a_mod(tmp_path, "m"))
        assert "mod.json" in plan.sources
        assert "tables/enemies.csv" in plan.sources

    def test_the_compiled_rel_is_generated_not_an_asset(self, tmp_path: Path):
        """⚠️ Always, even for a mod with no `code` block: a stale mod.rel is
        build output, and calling it game-derived would be alarming nonsense."""
        mod = a_mod(tmp_path, "m", {"files/mod/mod.rel": b"REL"})
        plan = pack.plan(mod)
        assert "overlay/files/mod/mod.rel" in plan.generated
        assert not plan.assets

    def test_a_generated_setup_file_is_not_an_asset(self, tmp_path: Path):
        """The mod declares he1_01, so both setup copies are its own output."""
        mod = a_mod(
            tmp_path,
            "m",
            {
                "files/setup/he1_01.dat": b"SETUP",
                "files/map/he1_01.bin/dvd/setup/he1_01.dat": b"SETUP",
            },
        )
        plan = pack.plan(mod)
        assert len(plan.generated) == 2
        assert not plan.assets

    def test_an_unrecognised_overlay_file_is_an_asset(self, tmp_path: Path):
        """A texture replaces disc content, so it is game-derived by
        construction. ⚠️ Unknown paths must fall this way, not the other."""
        mod = a_mod(tmp_path, "m", {"files/lyt/title.bin.uk/arc/timg/x.tpl": b"TPL"})
        plan = pack.plan(mod)
        assert plan.assets == ["overlay/files/lyt/title.bin.uk/arc/timg/x.tpl"]
        assert plan.needs_consent

    def test_a_setup_file_for_an_undeclared_map_is_an_asset(self, tmp_path: Path):
        """he1_01 is declared; an1_02 is not, so its setup file is game data the
        mod cannot regenerate."""
        mod = a_mod(tmp_path, "m", {"files/setup/an1_02.dat": b"SETUP"})
        plan = pack.plan(mod)
        assert plan.assets == ["overlay/files/setup/an1_02.dat"]

    def test_a_clean_mod_needs_no_consent(self, tmp_path: Path):
        assert not pack.plan(a_mod(tmp_path, "m")).needs_consent


class TestWhatGetsWritten:
    def test_assets_are_left_out_unless_allowed(self, tmp_path: Path):
        mod = a_mod(tmp_path, "m", {"files/lyt/x.tpl": b"TPL"})
        out = tmp_path / "m.bleck"
        result = pack.write(mod, pack.plan(mod), out)

        assert not result.assets_included
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
        assert "overlay/files/lyt/x.tpl" not in names
        assert "mod.json" in names, "the source should still be packed"

    def test_assets_are_included_when_allowed(self, tmp_path: Path):
        mod = a_mod(tmp_path, "m", {"files/lyt/x.tpl": b"TPL"})
        out = tmp_path / "m.bleck"
        result = pack.write(mod, pack.plan(mod), out, include_assets=True)

        assert result.assets_included
        with zipfile.ZipFile(out) as archive:
            assert archive.read("overlay/files/lyt/x.tpl") == b"TPL"

    def test_the_toc_records_the_base_and_hashes_every_file(self, tmp_path: Path):
        mod = a_mod(tmp_path, "m")
        out = tmp_path / "m.bleck"
        pack.write(mod, pack.plan(mod), out)

        toc = pack.read_toc(out)
        assert toc["base"] == "eu0"
        assert toc["mod"] == "m"
        assert set(toc["files"]) == {"mod.json", "tables/enemies.csv"}
        assert all(len(h) == 64 for h in toc["files"].values())

    def test_the_version_survives_json(self, tmp_path: Path):
        """`Version` is not JSON-serialisable; it has to be stringified."""
        mod = a_mod(tmp_path, "m")
        out = tmp_path / "m.bleck"
        pack.write(mod, pack.plan(mod), out)
        assert pack.read_toc(out)["version"] == "0.1.0"


class TestInstall:
    def test_a_round_trip_restores_every_source(self, tmp_path: Path):
        mod = a_mod(tmp_path / "from", "m", {"files/mod/mod.rel": b"REL"})
        out = tmp_path / "m.bleck"
        pack.write(mod, pack.plan(mod), out)

        into = tmp_path / "into"
        into.mkdir()
        done = pack.install(out, into)

        assert done.name == "m"
        assert (into / "m" / "mod.json").exists()
        assert (into / "m" / "tables" / "enemies.csv").exists()
        # The generated REL is NOT restored -- the recipient rebuilds it.
        assert not (into / "m" / "overlay" / "files" / "mod" / "mod.rel").exists()

    def test_it_refuses_to_overwrite_without_force(self, tmp_path: Path):
        mod = a_mod(tmp_path / "from", "m")
        out = tmp_path / "m.bleck"
        pack.write(mod, pack.plan(mod), out)
        into = tmp_path / "into"
        into.mkdir()
        pack.install(out, into)
        with pytest.raises(ManifestError, match="already exists"):
            pack.install(out, into)
        pack.install(out, into, force=True)

    def test_a_tampered_file_is_refused(self, tmp_path: Path):
        """⚠️ The hash is checked on the way in, so an edited archive fails
        loudly rather than installing something the author did not write."""
        mod = a_mod(tmp_path / "from", "m")
        out = tmp_path / "m.bleck"
        pack.write(mod, pack.plan(mod), out)

        toc = pack.read_toc(out)
        rebuilt = tmp_path / "bad.bleck"
        with zipfile.ZipFile(out) as source, zipfile.ZipFile(rebuilt, "w") as target:
            for name in source.namelist():
                data = source.read(name)
                if name == "tables/enemies.csv":
                    data = data + b"# edited\n"
                target.writestr(name, data)
        assert toc["files"]["tables/enemies.csv"]

        into = tmp_path / "into"
        into.mkdir()
        with pytest.raises(ManifestError, match="does not match the hash"):
            pack.install(rebuilt, into)

    def test_a_non_archive_is_refused_clearly(self, tmp_path: Path):
        bogus = tmp_path / "x.bleck"
        bogus.write_text("not a zip", encoding="utf-8")
        with pytest.raises(ManifestError, match="not even a zip"):
            pack.read_toc(bogus)

    def test_a_zip_without_a_toc_is_refused(self, tmp_path: Path):
        bogus = tmp_path / "x.bleck"
        with zipfile.ZipFile(bogus, "w") as archive:
            archive.writestr("mod.json", "{}")
        with pytest.raises(ManifestError, match="not written by bleck"):
            pack.read_toc(bogus)


class TestAssetOrigin:
    """Who decides whether an overlay file is game data.

    ⛔ **Not `bleck`.** It classified by path and called every overlay file
    game-derived, which is true of a vendored-and-edited texture and false of
    one somebody drew. The tool cannot tell them apart; the author can (D186).
    """

    def test_unstated_still_asks(self, tmp_path: Path):
        mod = a_mod(tmp_path, "m", overlay={"files/map/a.tpl": b"art"})
        assert pack.plan(mod).needs_consent

    def test_original_does_not_ask(self, tmp_path: Path):
        """An author shipping their own artwork is not confessing to anything."""
        mod = a_mod(tmp_path, "m", overlay={"files/map/a.tpl": b"art"}, assets="original")
        assert not pack.plan(mod).needs_consent

    def test_derived_does_not_ask_either_but_still_withholds(self, tmp_path: Path):
        """⚠️ Already answered, so asking again is noise -- but the answer was
        'this is game data', so it takes the flag."""
        mod = a_mod(tmp_path, "m", overlay={"files/map/a.tpl": b"x"}, assets="derived")
        plan_ = pack.plan(mod)
        assert not plan_.needs_consent
        assert not pack.packs_assets(plan_, include_assets=False)

    def test_original_assets_are_packed_without_a_flag(self, tmp_path: Path):
        mod = a_mod(tmp_path, "m", overlay={"files/map/a.tpl": b"art"}, assets="original")
        out = tmp_path / "m.bleck"
        result = pack.write(mod, pack.plan(mod), out)
        assert "overlay/files/map/a.tpl" in result.packed
        assert result.assets_included
        with zipfile.ZipFile(out) as archive:
            assert archive.read("overlay/files/map/a.tpl") == b"art"

    def test_derived_assets_need_the_flag(self, tmp_path: Path):
        mod = a_mod(tmp_path, "m", overlay={"files/map/a.tpl": b"x"}, assets="derived")
        without = pack.write(mod, pack.plan(mod), tmp_path / "a.bleck")
        assert "overlay/files/map/a.tpl" not in without.packed
        assert "overlay/files/map/a.tpl" in without.skipped

        withflag = pack.write(
            mod, pack.plan(mod), tmp_path / "b.bleck", include_assets=True
        )
        assert "overlay/files/map/a.tpl" in withflag.packed

    def test_a_mod_with_no_overlay_never_asks_whatever_it_declares(self, tmp_path: Path):
        for stated in (None, "original", "derived"):
            mod = a_mod(tmp_path / str(stated), "m", assets=stated)
            assert not pack.plan(mod).needs_consent

    def test_the_prompt_does_not_assert_what_it_cannot_know(self, tmp_path: Path):
        """⛔ It used to say the files *are* derived from the game."""
        mod = a_mod(tmp_path, "m", overlay={"files/map/a.tpl": b"art"})
        text = pack.plan(mod).describe_assets()
        assert "so they are derived from the game" not in text
        assert "If you made them" in text
        # And it says how to stop being asked.
        assert '"assets": "original"' in text

    def test_an_unknown_value_is_refused_by_name(self, tmp_path: Path):
        with pytest.raises(ManifestError, match="unknown 'assets' value"):
            a_mod(tmp_path, "m", assets="mine-i-swear")
