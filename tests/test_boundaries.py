"""What the shipped package is not allowed to contain.

`bleck` is installed on other people's machines. `scripts/` is not — it is a
test harness for whoever is working on this repo, and `pyproject.toml` exposes
exactly one entry point, `bleck.cli.app:main`.

That distinction is doing real work, so it is checked rather than remembered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "bleck"

#: Synthesising keystrokes is fine for a harness driving an emulator on the
#: machine of the person who launched it. It is not something a modding toolkit
#: should ship to strangers, whatever the intent — the capability reads the
#: same either way, and a tool that can drive other applications' input is a
#: different kind of program from one that repacks disc images.
#:
#: `scripts/keys.py` does this deliberately and is excluded from the package.
INPUT_INJECTION = (
    "SendInput",
    "keybd_event",
    "mouse_event",
    "SetForegroundWindow",
    "SetWindowsHookEx",
    "BlockInput",
)


def _sources() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_there_are_sources_to_check():
    """Guard the guard: a bad glob would make every test below vacuous."""
    assert len(_sources()) > 10


@pytest.mark.parametrize("symbol", INPUT_INJECTION)
def test_the_package_does_not_synthesise_input(symbol: str):
    offenders = [
        path.relative_to(PACKAGE.parent)
        for path in _sources()
        if symbol in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"{symbol} appears in the shipped package: {offenders}.\n"
        "Input synthesis belongs in scripts/, which is not installed."
    )
