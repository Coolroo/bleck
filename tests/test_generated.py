"""Generated overlay files are owned by the build that wrote them.

⛔ The load-bearing test is `TestTheStaleControl`, which is D156 reproduced: a
boss's CSV row was deleted, the rebuild left the previously generated setup
file, and the disc shipped the old placement. The control **passed while being
wrong**, and two plausible readings were written down before anyone checked the
file's timestamp.
"""

from __future__ import annotations

import json
from pathlib import Path

from bleck.mods import manifest as mod_manifest
from bleck.mods import registry
from bleck.mods.build import generated


def a_mod(root: Path, name: str = "m") -> registry.Mod:
    where = root / name
    (where / "overlay").mkdir(parents=True, exist_ok=True)
    (where / "mod.json").write_text(
        json.dumps({"schema": 1, "name": name, "version": "0.1.0", "base": "eu0"}),
        encoding="utf-8",
    )
    return registry.Mod(manifest=mod_manifest.Manifest(name=name, base="eu0"), root=where)


def put(mod: registry.Mod, relative: str, text: str = "x") -> Path:
    path = mod.overlay / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestTheStaleControl:
    """D156, as a test."""

    def test_a_declaration_that_goes_away_takes_its_output_with_it(self, tmp_path: Path):
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        setup = put(mod, "files/setup/an1_02.dat")
        generated.record(mod, [setup], work)

        # The next build declares nothing, so it writes nothing.
        swept = generated.sweep(mod, work)

        assert not setup.exists()
        assert swept.removed == ["files/setup/an1_02.dat"]

    def test_a_declaration_that_stays_is_rewritten_not_lost(self, tmp_path: Path):
        """⚠️ The sweep runs before the build, so removal is not the last word."""
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        setup = put(mod, "files/setup/an1_02.dat")
        generated.record(mod, [setup], work)

        generated.sweep(mod, work)
        rewritten = put(mod, "files/setup/an1_02.dat", "new contents")
        generated.record(mod, [rewritten], work)

        assert rewritten.read_text(encoding="utf-8") == "new contents"
        assert generated.read(mod, work) == ["files/setup/an1_02.dat"]


class TestWhatIsNeverTouched:
    """⛔ The sweep must not be able to eat somebody's work."""

    def test_an_unrecorded_file_survives(self, tmp_path: Path):
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        hand_written = put(mod, "files/setup/aa1_01.dat", "authored")
        generated.record(mod, [], work)

        generated.sweep(mod, work)

        assert hand_written.exists()

    def test_a_vendored_asset_survives_even_at_a_generated_shaped_path(
        self, tmp_path: Path
    ):
        """Vendoring and editing a setup file by hand is supported (D62)."""
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        put(mod, "files/setup/he1_01.dat", "authored")

        swept = generated.sweep(mod, work)

        assert (mod.overlay / "files/setup/he1_01.dat").exists()
        assert not swept.notes, "a supported workflow must not warn"

    def test_no_ledger_removes_nothing(self, tmp_path: Path):
        """A wiped `work/` means nothing is *known* owned, so nothing goes."""
        mod = a_mod(tmp_path / "mods")
        put(mod, "files/setup/an1_02.dat")

        swept = generated.sweep(mod, tmp_path / "work")

        assert not swept.removed
        assert (mod.overlay / "files/setup/an1_02.dat").exists()

    def test_a_corrupt_ledger_removes_nothing(self, tmp_path: Path):
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        generated.ledger_path(mod, work).parent.mkdir(parents=True)
        generated.ledger_path(mod, work).write_text("{not json", encoding="utf-8")
        put(mod, "files/setup/an1_02.dat")

        assert not generated.sweep(mod, work).removed
        assert (mod.overlay / "files/setup/an1_02.dat").exists()


class TestEmptyDirectories:
    def test_an_emptied_archive_directory_goes_too(self, tmp_path: Path):
        """An empty `files/map/x.bin/` is an archive with no members, which the
        plan would carry as an edit to nothing."""
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        member = put(mod, "files/map/an1_02.bin/dvd/setup/an1_02.dat")
        generated.record(mod, [member], work)

        generated.sweep(mod, work)

        assert not (mod.overlay / "files/map/an1_02.bin").exists()
        assert mod.overlay.is_dir(), "the overlay root itself must stay"

    def test_a_directory_with_anything_left_in_it_stays(self, tmp_path: Path):
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        member = put(mod, "files/map/an1_02.bin/dvd/setup/an1_02.dat")
        put(mod, "files/map/an1_02.bin/dvd/other.dat", "keep me")
        generated.record(mod, [member], work)

        generated.sweep(mod, work)

        assert (mod.overlay / "files/map/an1_02.bin/dvd/other.dat").exists()


class TestTheLedger:
    def test_it_lives_outside_the_mod(self, tmp_path: Path):
        """⚠️ Inside `overlay/` it would ship on the disc; inside the mod root
        `mod pack` would carry it as a source."""
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        generated.record(mod, [], work)

        assert generated.ledger_path(mod, work).is_file()
        assert mod.root not in generated.ledger_path(mod, work).parents

    def test_paths_outside_the_overlay_are_dropped(self, tmp_path: Path):
        """A build result may name intermediates; only overlay content can go
        stale on a disc."""
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        generated.record(mod, [tmp_path / "elsewhere" / "mod.o"], work)

        assert generated.read(mod, work) == []

    def test_it_is_stored_posix_style(self, tmp_path: Path):
        """Manifests and ledgers must survive a Windows/Linux round trip."""
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        generated.record(mod, [put(mod, "files/map/an1_02.bin/dvd/x.dat")], work)

        assert generated.read(mod, work) == ["files/map/an1_02.bin/dvd/x.dat"]

    def test_a_rel_nobody_recorded_is_reported_not_removed(self, tmp_path: Path):
        """Nobody writes a REL by hand, but deleting it is still not this
        function's call -- the ledger may simply predate this feature."""
        mod = a_mod(tmp_path / "mods")
        work = tmp_path / "work"
        put(mod, "files/mod/mod.rel")

        swept = generated.sweep(mod, work)

        assert (mod.overlay / "files/mod/mod.rel").exists()
        assert len(swept.notes) == 1
        assert "files/mod/mod.rel" in swept.notes[0]
