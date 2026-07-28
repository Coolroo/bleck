"""What the shipped package is not allowed to contain.

`bleck` is installed on other people's machines; `scripts/` is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "bleck"

#: Input synthesis is fine in a local harness but must not ship to strangers.
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
