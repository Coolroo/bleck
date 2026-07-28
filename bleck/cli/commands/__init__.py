"""Command modules, grouped by the layer they operate on.

Each module exposes `CATEGORY` and a `register(add)` hook, where `add` builds a
subparser carrying the shared flags. Adding a command means adding a module here
and listing it in `MODULES` — nothing in the CLI core needs to change.
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
)

# Order determines how commands appear in `bleck --help`: inspection first
# (what most people reach for), then containers, then mods and the scripts they
# are built from, then discs, then launching what came out of them, then raw
# streams.
MODULES = [inspect, placement, symbols, archive, mods, scripts, disc, emulate, stream]

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
]
