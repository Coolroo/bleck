"""Shared fixtures.

Two constraints shape this suite:

1. The LZ77 compressor runs ~12 s/MB, so tests compress only small synthetic
   inputs. Anything that compresses real game data is marked `slow`.
2. Game data is not in the repo. Tests needing it skip cleanly when absent, so a
   fresh clone still runs green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GAME_DATA = REPO / "work" / "extracted" / "eu0" / "files"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: compresses real game data (minutes)")
    config.addinivalue_line("markers", "gamedata: needs an extracted disc")


@pytest.fixture(scope="session")
def game_data() -> Path:
    if not GAME_DATA.is_dir():
        pytest.skip(f"no extracted disc at {GAME_DATA}")
    return GAME_DATA


@pytest.fixture(scope="session")
def map_archive(game_data: Path) -> bytes:
    """A real LZ77+U8 map archive, read once per session."""
    path = game_data / "map" / "aa1_01.bin"
    if not path.exists():
        pytest.skip(f"missing {path}")
    return path.read_bytes()


@pytest.fixture
def compressible() -> bytes:
    """Small, highly repetitive — exercises long matches cheaply."""
    return (b"SuperPaperMario" * 40) + (b"\x00" * 200) + (b"ABCABCABC" * 30)


@pytest.fixture
def incompressible() -> bytes:
    """Deterministic pseudo-random: forces the literal path."""
    state = 0x12345678
    out = bytearray()
    for _ in range(1000):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        out.append(state >> 16 & 0xFF)
    return bytes(out)
