"""Manifest serialisation — the record of U8 node order."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bleck.common import manifest


@pytest.fixture
def sample() -> manifest.Manifest:
    return manifest.Manifest(
        order=["dvd", "dvd/map", "dvd/map/a.bin"],
        dirs=["dvd", "dvd/map"],
        compressed=True,
        source="aa1_01.bin",
    )


def test_round_trips(sample: manifest.Manifest):
    assert manifest.Manifest.from_json(sample.to_json()) == sample


def test_writes_and_reads_from_disk(tmp_path: Path, sample: manifest.Manifest):
    manifest.write(tmp_path, sample)
    assert (tmp_path / manifest.MANIFEST_NAME).exists()
    assert manifest.read(tmp_path) == sample


def test_missing_manifest_returns_none(tmp_path: Path):
    assert manifest.read(tmp_path) is None


def test_rejects_unknown_version(tmp_path: Path, sample: manifest.Manifest):
    raw = json.loads(sample.to_json())
    raw["version"] = 99
    (tmp_path / manifest.MANIFEST_NAME).write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="unsupported manifest version"):
        manifest.read(tmp_path)


def test_order_survives_exactly():
    """Order is the whole point — it must not be sorted or deduplicated."""
    scrambled = manifest.Manifest(order=["z", "a", "m", "a"], dirs=[], compressed=False)
    assert manifest.Manifest.from_json(scrambled.to_json()).order == ["z", "a", "m", "a"]
