"""Launching Dolphin.

The emulator is stubbed throughout: these assert how `bleck` *invokes* Dolphin,
not that a game boots (verified by hand — D25, D36).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bleck.backends import emulator
from bleck.backends.disc import DiscError

FAKE_DOLPHIN = "/fake/Dolphin"


class FakeProcess:
    """Stands in for a Popen handle."""

    def __init__(self, returncode: int = 0):
        self.pid = 4242
        self._returncode = returncode
        self.waited = False

    def wait(self) -> int:
        self.waited = True
        return self._returncode


@pytest.fixture(name="image")
def fixture_image(tmp_path: Path) -> Path:
    path = tmp_path / "my-mod.wbfs"
    path.write_bytes(b"not really a disc")
    return path


@pytest.fixture(name="spawned")
def fixture_spawned(monkeypatch) -> list[list[str]]:
    """Capture the argument list Dolphin would have been started with."""
    calls: list[list[str]] = []
    monkeypatch.setattr(emulator, "find_tool", lambda _name: FAKE_DOLPHIN)
    monkeypatch.setattr(
        emulator.subprocess, "Popen", lambda args: calls.append(args) or FakeProcess()
    )
    return calls


class TestArguments:
    def test_boots_the_image(self, spawned, image: Path):
        emulator.launch(image)

        assert spawned == [[FAKE_DOLPHIN, "-e", str(image.resolve())]]

    def test_batch_skips_the_game_list(self, spawned, image: Path):
        emulator.launch(image, batch=True)

        assert spawned[0] == [FAKE_DOLPHIN, "-b", "-e", str(image.resolve())]

    def test_path_is_absolute(self, spawned, image: Path, monkeypatch, tmp_path: Path):
        """Dolphin resolves a relative path against its own working directory."""
        monkeypatch.chdir(tmp_path)

        emulator.launch(Path(image.name))

        assert Path(spawned[0][-1]).is_absolute()

    def test_exec_flag_and_path_stay_separate_tokens(self, spawned, image: Path):
        """Never the joined `--exec=<path>` form: two tokens cannot be misquoted,
        and Dolphin blames permissions when a quoted path reaches it."""
        emulator.launch(image)

        assert "-e" in spawned[0]
        assert not any(arg.startswith("--exec") for arg in spawned[0])
        assert not any('"' in arg for arg in spawned[0])


class TestWaiting:
    def test_returns_immediately_by_default(self, spawned, image: Path):
        """A build-and-boot loop wants its shell back."""
        result = emulator.launch(image)

        assert not result.finished
        assert result.exit_code is None
        assert result.pid == 4242
        assert spawned  # it really did start

    def test_wait_reports_the_exit_code(self, monkeypatch, image: Path):
        process = FakeProcess(returncode=3)
        monkeypatch.setattr(emulator, "find_tool", lambda _name: FAKE_DOLPHIN)
        monkeypatch.setattr(emulator.subprocess, "Popen", lambda _args: process)

        result = emulator.launch(image, wait=True)

        assert process.waited
        assert result.finished
        assert result.exit_code == 3


class TestFailures:
    def test_missing_image_is_reported_before_starting_anything(
        self, spawned, tmp_path: Path
    ):
        with pytest.raises(DiscError, match="no such image"):
            emulator.launch(tmp_path / "absent.wbfs")

        assert not spawned, "should not have tried to start Dolphin"

    def test_unstartable_emulator_names_the_binary(self, monkeypatch, image: Path):
        monkeypatch.setattr(emulator, "find_tool", lambda _name: FAKE_DOLPHIN)

        def refuse(_args):
            raise OSError("Exec format error")

        monkeypatch.setattr(emulator.subprocess, "Popen", refuse)

        with pytest.raises(DiscError, match="Dolphin"):
            emulator.launch(image)

    def test_missing_emulator_propagates_the_search_hint(self, monkeypatch, image: Path):
        def not_found(_name):
            raise DiscError("dolphin not found (looked for: Dolphin.exe)")

        monkeypatch.setattr(emulator, "find_tool", not_found)

        with pytest.raises(DiscError, match="looked for"):
            emulator.launch(image)


class TestPopenUsage:
    def test_the_emulator_is_not_waited_on_implicitly(self, image: Path, monkeypatch):
        """`with Popen(...)` waits on exit, pinning the terminal until Dolphin quits."""
        entered: list[str] = []

        class Tracking(FakeProcess):
            def __enter__(self):
                entered.append("entered")
                return self

            def __exit__(self, *_args):
                return False

        monkeypatch.setattr(emulator, "find_tool", lambda _name: FAKE_DOLPHIN)
        monkeypatch.setattr(emulator.subprocess, "Popen", lambda _args: Tracking())

        emulator.launch(image)

        assert not entered


def test_real_popen_is_what_gets_patched():
    """Guard the tests above: they are meaningless if the name moved."""
    assert emulator.subprocess is subprocess
    assert hasattr(subprocess, "Popen")


class TestFastBoot:
    """~2,100 frames of logos precede gameplay: ~45 s capped, ~6 s uncapped (D63)."""

    def test_uncapping_passes_dolphins_config_override(self, spawned, image: Path):
        emulator.launch(image, unlimited=True)
        assert "Dolphin.Core.EmulationSpeed=0" in spawned[0]

    def test_the_cap_is_left_alone_by_default(self, spawned, image: Path):
        emulator.launch(image)
        assert not any("EmulationSpeed" in arg for arg in spawned[0])

    def test_a_save_state_is_passed_through(self, spawned, image: Path, tmp_path):
        state = tmp_path / "spm.s01"
        state.write_bytes(b"state")
        emulator.launch(image, state=state)
        assert spawned[0][-2:] == ["-s", str(state.resolve())]

    def test_a_missing_save_state_is_refused(self, monkeypatch, image: Path, tmp_path):
        # Silently booting cold would look like the state simply not working.
        monkeypatch.setattr(emulator, "find_tool", lambda _name: FAKE_DOLPHIN)
        with pytest.raises(DiscError, match="no save state"):
            emulator.launch(image, state=tmp_path / "absent.sav")
