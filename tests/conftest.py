"""Shared fixtures.

LZ77 runs ~12 s/MB, so only small synthetic inputs are compressed here; real
game data is absent from a fresh clone, so tests needing it skip cleanly.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from bleck.formats import items
from tests import synthetic_msg

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


@pytest.fixture(scope="session", name="invented_base")
def _invented_base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A base build carrying nothing but the invented message table.

    Session-scoped: the table is the same for every test that wants it, and
    writing it reads the 78 KB catalog once rather than once per test.
    """
    return synthetic_msg.write(tmp_path_factory.mktemp("invented-msg"))


@pytest.fixture(name="invented_item_names")
def _invented_item_names(
    invented_base: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Resolve English item names against invented words, on any machine.

    ⚠️ **Set, never inherited.** An item's English name is looked up at run time
    in `files/msg/<lang>/` under `BLECK_BASE_DIR` (D194), so a developer with a
    disc extracted would otherwise test against different words from CI -- and
    CI, having no disc, against none at all. Pointing both at one synthetic
    table is what makes the English tier testable everywhere.

    ⚠️ `items.catalog` is `lru_cache`d, so the cache is cleared on the way in
    *and* on the way out: a table read under this fixture must not survive it.
    """
    monkeypatch.setenv("BLECK_BASE_DIR", str(invented_base))
    items.catalog.cache_clear()
    yield invented_base
    items.catalog.cache_clear()


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
