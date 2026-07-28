"""CLI behaviour — argument handling, exit codes, and the unpack/pack contract."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import pytest

from bleck.backends import maps
from bleck.cli import app as cli
from bleck.cli.commands import mods
from bleck.common import manifest
from bleck.common.errors import UserError
from bleck.formats import detect as formats
from bleck.formats import u8


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    """An uncompressed U8 archive on disk."""
    path = tmp_path / "sample.bin"
    path.write_bytes(
        u8.write(
            [
                u8.U8Item("dvd", None),
                u8.U8Item("dvd/map", None),
                u8.U8Item("dvd/map/a.bin", b"contents of a"),
                u8.U8Item(
                    "dvd/tex.tpl", struct.pack(">I", formats.TPL_MAGIC) + b"\x00" * 16
                ),
            ]
        )
    )
    return path


class TestInvocation:
    def test_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == 0

    def test_missing_subcommand_errors(self):
        with pytest.raises(SystemExit) as exc:
            cli.main([])
        assert exc.value.code != 0

    def test_force_accepted_after_subcommand(self, archive: Path, tmp_path: Path):
        """The form users actually type: flags trailing the arguments."""
        out = tmp_path / "out"
        assert cli.main(["unpack", str(archive), str(out)]) == 0
        assert cli.main(["unpack", str(archive), str(out), "--force"]) == 0


class TestInfoAndLs:
    def test_info_reports_nested_formats(self, archive: Path, capsys):
        assert cli.main(["info", str(archive)]) == 0
        out = capsys.readouterr().out
        assert "U8" in out and "TPL" in out

    def test_ls_lists_entries(self, archive: Path, capsys):
        assert cli.main(["ls", str(archive)]) == 0
        assert "dvd/map/a.bin" in capsys.readouterr().out

    def test_ls_rejects_non_archive(self, tmp_path: Path, capsys):
        bad = tmp_path / "bad.bin"
        bad.write_bytes(b"\x99" * 64)
        assert cli.main(["ls", str(bad)]) == 1
        assert "not a U8 archive" in capsys.readouterr().err

    def test_missing_file_exits_one(self, capsys):
        assert cli.main(["info", "/nonexistent/file.bin"]) == 1
        assert "no such file" in capsys.readouterr().err


class TestUnpackPack:
    def test_unpack_writes_files_and_manifest(self, archive: Path, tmp_path: Path):
        dest = tmp_path / "out"
        assert cli.main(["unpack", str(archive), str(dest)]) == 0
        assert (dest / "dvd/map/a.bin").read_bytes() == b"contents of a"
        found = manifest.read(dest)
        assert found is not None
        assert found.order[0] == "dvd"
        assert found.compressed is False

    def test_round_trip_is_byte_identical(self, archive: Path, tmp_path: Path):
        dest, out = tmp_path / "out", tmp_path / "repacked.bin"
        cli.main(["unpack", str(archive), str(dest)])
        assert cli.main(["pack", str(dest), str(out), "--raw"]) == 0
        assert out.read_bytes() == archive.read_bytes()

    def test_pack_without_manifest_warns(self, archive: Path, tmp_path: Path, capsys):
        dest, out = tmp_path / "out", tmp_path / "repacked.bin"
        cli.main(["unpack", str(archive), str(dest)])
        (dest / manifest.MANIFEST_NAME).unlink()
        assert cli.main(["pack", str(dest), str(out), "--raw"]) == 0
        assert "byte-exact output is not guaranteed" in capsys.readouterr().err

    def test_pack_reports_missing_member(self, archive: Path, tmp_path: Path, capsys):
        dest, out = tmp_path / "out", tmp_path / "repacked.bin"
        cli.main(["unpack", str(archive), str(dest)])
        (dest / "dvd/map/a.bin").unlink()
        assert cli.main(["pack", str(dest), str(out), "--raw"]) == 1
        assert "missing from" in capsys.readouterr().err

    def test_refuses_to_clobber(self, archive: Path, tmp_path: Path, capsys):
        dest, out = tmp_path / "out", tmp_path / "repacked.bin"
        cli.main(["unpack", str(archive), str(dest)])
        cli.main(["pack", str(dest), str(out), "--raw"])
        assert cli.main(["pack", str(dest), str(out), "--raw"]) == 1
        assert "--force" in capsys.readouterr().err

    def test_store_mode_is_larger_but_valid(self, archive: Path, tmp_path: Path):
        dest = tmp_path / "out"
        stored, raw = tmp_path / "s.bin", tmp_path / "r.bin"
        cli.main(["unpack", str(archive), str(dest)])
        cli.main(["pack", str(dest), str(stored), "--store"])
        cli.main(["pack", str(dest), str(raw), "--raw"])
        assert stored.stat().st_size > raw.stat().st_size
        assert cli.main(["verify", str(stored)]) == 0


class TestVerify:
    def test_passes_on_good_archive(self, archive: Path, capsys):
        assert cli.main(["verify", str(archive)]) == 0
        assert "1 identical" in capsys.readouterr().out

    def test_skips_non_archives(self, tmp_path: Path, capsys):
        bad = tmp_path / "x.bin"
        bad.write_bytes(b"\x99" * 64)
        assert cli.main(["verify", str(bad)]) == 0
        assert "1 skipped" in capsys.readouterr().out

    def test_errors_on_empty_directory(self, tmp_path: Path, capsys):
        assert cli.main(["verify", str(tmp_path)]) == 1
        assert "no .bin files" in capsys.readouterr().err


class TestLz:
    def test_decompress_round_trip(self, tmp_path: Path):
        source, packed, out = (
            tmp_path / "a.bin",
            tmp_path / "a.lz",
            tmp_path / "a.out",
        )
        source.write_bytes(b"repeat " * 100)
        assert cli.main(["lz", "compress", str(source), str(packed)]) == 0
        assert cli.main(["lz", "decompress", str(packed), str(out)]) == 0
        assert out.read_bytes() == source.read_bytes()

    def test_reports_sizes_without_output_file(self, tmp_path: Path, capsys):
        source = tmp_path / "a.bin"
        source.write_bytes(b"x" * 100)
        assert cli.main(["lz", "compress", str(source)]) == 0
        assert "->" in capsys.readouterr().out


class TestBootMapFlag:
    """`--map` resolves against the game's real map list before anything builds.

    A name that does not exist would otherwise compile fine, boot fine, and then
    sit on the attract demo forever — the failure mode looks identical to the
    feature not working at all.
    """

    def _resolve(self, value):
        return mods.boot_override(argparse.Namespace(map=value), Path("base"))

    @pytest.fixture(autouse=True)
    def _index(self, monkeypatch):
        entries = [
            maps.MapEntry(name="he1_01", archive=Path("he1_01.bin"), map_id=42),
            maps.MapEntry(name="he1_02", archive=Path("he1_02.bin"), map_id=43),
            maps.MapEntry(name="mac_01", archive=Path("mac_01.bin"), map_id=7),
        ]
        index = maps.MapIndex(entries=entries, source=Path())
        monkeypatch.setattr(mods.maps, "load", lambda _base: index)

    def test_no_flag_means_no_override(self):
        assert self._resolve(None).is_empty

    def test_a_name_is_taken_as_given(self):
        assert self._resolve("he1_01").boot_map == "he1_01"

    def test_a_numeric_id_resolves_to_its_name(self):
        """`bleck maps` prints both columns and neither is more memorable."""
        assert self._resolve("7").boot_map == "mac_01"

    def test_an_unknown_id_says_so(self):
        with pytest.raises(UserError, match="no map with id 999"):
            self._resolve("999")

    def test_a_typo_gets_a_suggestion(self):
        with pytest.raises(UserError) as caught:
            self._resolve("he1_O1")
        assert "he1_01" in str(caught.value)
