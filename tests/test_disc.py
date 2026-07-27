"""Disc backend behaviour, independent of platform.

The external tools are stubbed throughout: these assert how `bleck` *invokes*
wit and DolphinTool, not what those tools do with the bytes.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from bleck.backends import disc, gecko


@pytest.fixture(name="stub_tools")
def fixture_stub_tools(monkeypatch):
    """Pretend both external tools are installed."""
    monkeypatch.setattr(disc, "find_tool", lambda name: f"/fake/{name}")


def _parent_existed_at_call(monkeypatch, dest: Path) -> list[bool]:
    """Record whether `dest`'s parent existed at the moment the tool ran.

    Checking after the fact would pass even if the directory were created too
    late; the ordering is the thing under test.
    """
    seen: list[bool] = []
    monkeypatch.setattr(disc, "_run", lambda _args: seen.append(dest.parent.is_dir()))
    return seen


@pytest.mark.usefixtures("stub_tools")
class TestOutputParentDirectories:
    """Neither wit nor DolphinTool creates a missing parent directory.

    DolphinTool in particular fails with only "Conversion failed" — no path, no
    reason — so this is expensive to diagnose in the field. It bit on the
    documented fresh-machine command `bleck extract disc.rvz extracted/eu0`,
    where `extracted/` does not exist yet.
    """

    def test_convert_rvz_creates_parent(self, monkeypatch, tmp_path: Path):
        dest = tmp_path / "missing" / "out.iso"
        seen = _parent_existed_at_call(monkeypatch, dest)

        disc.convert_rvz(tmp_path / "in.rvz", dest)

        assert seen == [True]

    def test_convert_to_rvz_creates_parent(self, monkeypatch, tmp_path: Path):
        dest = tmp_path / "missing" / "out.rvz"
        seen = _parent_existed_at_call(monkeypatch, dest)

        disc.convert_to_rvz(tmp_path / "in.iso", dest)

        assert seen == [True]

    def test_build_creates_parent(self, monkeypatch, tmp_path: Path):
        out = tmp_path / "missing" / "out.iso"
        seen = _parent_existed_at_call(monkeypatch, out)

        disc.build(tmp_path / "extracted", out)

        assert seen == [True]

    def test_existing_parent_is_left_alone(self, monkeypatch, tmp_path: Path):
        """exist_ok, and the directory's contents must survive."""
        dest = tmp_path / "already" / "out.iso"
        dest.parent.mkdir()
        neighbour = dest.parent / "keep.txt"
        neighbour.write_text("untouched")

        _parent_existed_at_call(monkeypatch, dest)
        disc.convert_rvz(tmp_path / "in.rvz", dest)

        assert neighbour.read_text() == "untouched"


@pytest.mark.usefixtures("stub_tools")
class TestAlignFiles:
    def test_build_always_passes_align_files(self, monkeypatch, tmp_path: Path):
        """--align-files is mandatory; omitting it fails subtly, not loudly."""
        captured: list[list[str]] = []
        monkeypatch.setattr(disc, "_run", captured.append)

        disc.build(tmp_path / "extracted", tmp_path / "out.iso")

        assert "--align-files" in captured[0]

    def test_build_always_passes_overwrite(self, monkeypatch, tmp_path: Path):
        """`--force` must reach wit, not just satisfy bleck's own guard.

        Without this, rebuilding over an existing image staged the whole build
        and then failed at the last step with wit's ERROR #64.
        """
        captured: list[list[str]] = []
        monkeypatch.setattr(disc, "_run", captured.append)

        disc.build(tmp_path / "extracted", tmp_path / "out.iso")

        assert "--overwrite" in captured[0]


class TestGeckoCodelist:
    """Assembling a Gecko codelist into a GCT. Pure logic, no external tool."""

    def test_wraps_codes_in_header_and_terminator(self):
        out = gecko.build_gct("0423E45C 88030009\n0423E5E4 98030009\n")
        assert out.startswith(gecko.GCT_HEADER)
        assert out.endswith(gecko.GCT_TERMINATOR)
        assert len(out) == 8 + 4 * 4 + 8

    def test_words_are_big_endian(self):
        # The Wii is big-endian; a byte-swapped code list is silently wrong.
        out = gecko.build_gct("0423E45C 88030009\n")
        assert out[8:16] == bytes.fromhex("0423E45C88030009")

    def test_comments_and_blank_lines_are_ignored(self):
        source = "# a comment\n\n0423E45C 88030009\n// another\n0423E5E4 98030009\n"
        assert len(gecko.build_gct(source)) == 8 + 4 * 4 + 8

    def test_rejects_a_file_that_is_not_a_codelist(self):
        # wstrt's own message for this is "Invalid WCH header", which says
        # nothing about what the user actually handed it.
        with pytest.raises(gecko.GeckoError, match=r"expected 8-digit hex words"):
            gecko.build_gct("this is not a gecko code")

    def test_rejects_an_odd_number_of_words(self):
        with pytest.raises(gecko.GeckoError, match=r"come in pairs"):
            gecko.build_gct("0423E45C 88030009\n0423E5E4\n")

    def test_rejects_an_empty_file(self):
        with pytest.raises(gecko.GeckoError, match=r"no code words"):
            gecko.build_gct("# nothing but comments\n")

    def test_missing_codelist_names_the_path_and_the_reason(self, tmp_path: Path):
        with pytest.raises(gecko.GeckoError) as caught:
            gecko.codelist("eu0", tmp_path)
        message = str(caught.value)
        assert "loader.eu0.txt" in message
        assert "GPLv3" in message  # why bleck does not simply bundle it


@pytest.mark.usefixtures("stub_tools")
class TestGeckoEmbedding:
    def test_detaches_the_dol_before_patching(self, monkeypatch, tmp_path: Path):
        """The staged DOL is a hardlink to the base; wstrt rewrites in place.

        Patching without detaching would edit the pristine base — the one
        failure the whole build design exists to prevent.
        """
        base = tmp_path / "base.dol"
        base.write_bytes(b"original")
        staged = tmp_path / "staged.dol"
        os.link(base, staged)

        def fake_run(args, **_kwargs):
            Path(args[2]).write_bytes(b"patched and longer")
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(gecko.subprocess, "run", fake_run)
        monkeypatch.setattr(gecko, "find_tool", lambda _name: "/fake/wstrt")

        gecko.embed(staged, gecko.build_gct("0423E45C 88030009\n"), tmp_path / "work")

        assert base.read_bytes() == b"original"
        assert staged.read_bytes() == b"patched and longer"

    def test_unchanged_dol_is_an_error(self, monkeypatch, tmp_path: Path):
        # wstrt reports a dropped section as a warning and still exits 0.
        dol = tmp_path / "main.dol"
        dol.write_bytes(b"unchanged")
        monkeypatch.setattr(
            gecko.subprocess,
            "run",
            lambda args, **_k: subprocess.CompletedProcess(args, 0, "", ""),
        )
        monkeypatch.setattr(gecko, "find_tool", lambda _name: "/fake/wstrt")

        with pytest.raises(gecko.GeckoError, match=r"left the DOL unchanged"):
            gecko.embed(dol, gecko.build_gct("0423E45C 88030009\n"), tmp_path / "w")
