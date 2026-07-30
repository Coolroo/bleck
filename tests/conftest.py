"""Shared fixtures.

LZ77 runs ~12 s/MB, so only small synthetic inputs are compressed here; real
game data is absent from a fresh clone, so tests needing it skip cleanly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GAME_DATA = REPO / "work" / "extracted" / "eu0" / "files"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: compresses real game data (minutes)")
    config.addinivalue_line("markers", "gamedata: needs an extracted disc")


@pytest.fixture(autouse=True)
def isolated_build_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `BLECK_BUILD_DIR` at a scratch directory for every test.

    ⚠️ Autouse, because a build writes there whether or not the test is *about*
    building. `builder.produce` records which overlay files it generated under
    the build root, and without this a run of the suite left a dozen ledgers
    named after test fixtures (`edit`, `tex`, `one`) in the real `work/build/`
    -- where a real mod of the same name would then inherit one.
    """
    root = tmp_path / "build"
    root.mkdir()
    monkeypatch.setenv("BLECK_BUILD_DIR", str(root))
    return root


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
