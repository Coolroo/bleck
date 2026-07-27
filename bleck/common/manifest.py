"""Archive manifests.

U8 node order is a flat depth-first listing, and repacking byte-identically
depends on preserving it. A directory on disk does not preserve that order, so
unpacking records it here and packing reads it back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = ".bleck.json"


@dataclass
class Manifest:
    """What `unpack` learned about an archive, so `pack` can reproduce it."""

    order: list[str]
    """Every entry path in node order, directories included."""

    dirs: list[str]
    """Which of those paths are directories."""

    compressed: bool
    """Whether the archive was LZ77-wrapped on disc."""

    source: str = ""
    """Original filename, for diagnostics only."""

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": 1,
                "source": self.source,
                "compressed": self.compressed,
                "order": self.order,
                "dirs": self.dirs,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        raw = json.loads(text)
        version = raw.get("version")
        if version != 1:
            raise ValueError(f"unsupported manifest version {version!r}")
        return cls(
            order=raw["order"],
            dirs=raw["dirs"],
            compressed=raw.get("compressed", True),
            source=raw.get("source", ""),
        )


def write(directory: Path, manifest: Manifest) -> None:
    (directory / MANIFEST_NAME).write_text(manifest.to_json())


def read(directory: Path) -> Manifest | None:
    path = directory / MANIFEST_NAME
    if not path.exists():
        return None
    return Manifest.from_json(path.read_text())
