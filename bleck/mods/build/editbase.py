"""What `edits` and `coins` both need, and neither may own.

`edits` builds a map's enemy list and `coins` its item list; both end up in one
generated `.dat`, so `edits` calls `coins`. That makes the direction one-way,
and anything the callee needs from the caller has to live below both — which is
this: the error they raise, and the one path lookup they share.
"""

from __future__ import annotations

from pathlib import Path

from bleck.common.errors import BleckError
from bleck.mods.manifest import MANIFEST_NAME
from bleck.mods.registry import Mod


class EditError(BleckError):
    """A declared edit could not be applied."""


def table_path(mod: Mod, ref) -> Path:
    """Where a declared table really is, refusing one the mod does not ship."""
    path = mod.root / ref.path
    if not path.is_file():
        raise EditError(
            f"{mod.name}: no table at {ref.path}, declared under "
            f"'tables.{ref.kind}' in {MANIFEST_NAME}"
        )
    return path
