"""CSV tables: placements declared in a file rather than inline in `mod.json`.

A mod can say what a map places two ways, and they mean exactly the same thing:

    "setup":  { "he1_01": [ { "slot": 3, "template": 2 } ] }     inline
    "tables": { "enemies": "tables/enemies.csv" }                a table

Inline is right for a handful of rows. Past that, JSON stops being readable and
starts being punctuation, so a table takes over (D124).

**One module per kind of table**, because the kinds are not variations on each
other -- an enemy has a fixed slot and an item has a position in a counted list,
so they validate differently and say so in different words:

    tables.enemies    map, slot, template, x, y, z, copy_from, clear
    tables.coins      map, index, x, y, z, flags, clear
    tables.doors      map, index, script, at, expect, call

`common` holds what is genuinely shared: comment stripping, the header, and
cell access. Column *lists* are data (`common.Schema`); column *meanings* are
not, and live with their kind.

⚠️ **The `tables` key in `mod.json` is the kind, not a label** (D125), and
`bleck` refuses anything outside that closed set rather than guessing.

⚠️ **A bound table may not also carry a `map` column.** Two places to say the
same thing is two places for them to disagree, and the disagreement would be
invisible; the column is refused rather than checked.
"""

from __future__ import annotations

# Re-exported: the error type and the file-shape vocabulary are shared, so
# callers catch one exception rather than one per kind.
from bleck.formats.tables import coins, doors, enemies
from bleck.formats.tables.common import (
    AXES,
    COMMENT,
    Header,
    Schema,
    TableError,
)

__all__ = [
    "AXES",
    "COMMENT",
    "Header",
    "Schema",
    "TableError",
    "coins",
    "doors",
    "enemies",
]
