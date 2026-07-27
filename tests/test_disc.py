"""Disc backend behaviour, independent of platform.

The external tools are stubbed throughout: these assert how `bleck` *invokes*
wit and DolphinTool, not what those tools do with the bytes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bleck.backends import disc


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
