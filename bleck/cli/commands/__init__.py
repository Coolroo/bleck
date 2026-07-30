"""Command modules. Each exposes `CATEGORY` and a `register(add)` hook, where
`add` builds a subparser carrying the shared flags.
"""

from __future__ import annotations

from . import (
    archive,
    disc,
    emulate,
    inspect,
    mods,
    placement,
    scripts,
    stream,
    symbols,
    texture,
)

# Order determines how commands appear in `bleck --help`.
MODULES = [
    inspect,
    placement,
    symbols,
    texture,
    archive,
    mods,
    scripts,
    disc,
    emulate,
    stream,
]

__all__ = [
    "MODULES",
    "archive",
    "disc",
    "emulate",
    "inspect",
    "mods",
    "placement",
    "scripts",
    "stream",
    "symbols",
    "texture",
]
