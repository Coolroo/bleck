"""Command modules. Each exposes `CATEGORY` and a `register(add)` hook, where
`add` builds a subparser carrying the shared flags.
"""

from __future__ import annotations

from . import (
    archive,
    disc,
    doctor,
    effect,
    emulate,
    inspect,
    model,
    mods,
    placement,
    scripts,
    sound,
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
    model,
    effect,
    sound,
    archive,
    mods,
    scripts,
    disc,
    emulate,
    stream,
    doctor,
]

__all__ = [
    "MODULES",
    "archive",
    "disc",
    "doctor",
    "effect",
    "emulate",
    "inspect",
    "model",
    "mods",
    "placement",
    "scripts",
    "sound",
    "stream",
    "symbols",
    "texture",
]
