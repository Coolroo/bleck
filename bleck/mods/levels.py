"""Organising a mod by level: one directory per map, tables inside it.

A mod that touches one map is fine flat. A mod that reworks ten is not — ten
enemy tables, ten coin tables and ten door tables all in one `tables` block,
each needing an explicit `map`, with nothing grouping the three that belong
together:

```json
"tables": {
  "enemies": [{"path": "tables/he1_01-enemies.csv", "map": "he1_01"}, ...],
  "coins":   [{"path": "tables/he1_01-coins.csv",   "map": "he1_01"}, ...],
  "doors":   [{"path": "tables/he1_01-doors.csv",   "map": "he1_01"}, ...]
}
```

A level directory says the same thing once:

```json
"levels": ["levels/he1_01", "levels/mac_02"]
```

```
levels/he1_01/enemies.csv     bound to he1_01
levels/he1_01/coins.csv       bound to he1_01
levels/he1_01/doors.csv       bound to he1_01
```

⚠️ **The directory name is the map name**, so the binding is visible in the
path rather than repeated in JSON. A directory that wants a friendlier name
says the map explicitly: `{"path": "levels/lineland", "map": "he1_01"}`.

⚠️ **This is sugar over `tables`, not a second mechanism.** A level expands into
exactly the `TableRef`s the long form would have declared, bound the same way,
read by the same readers. Anything a table can do a level table can do, and
nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck.mods.errors import ManifestError
from bleck.mods.manifest import TableKind, TableRef

#: ⚠️ Typed loosely on purpose. This needs a mod's `manifest` and `root` and
#: nothing else, and importing `registry.Mod` would make a cycle -- registry
#: calls straight into here.

#: What a level directory may contain, by kind. A file named anything else is a
#: typo worth naming -- silently ignoring `enemys.csv` is how a mod ships doing
#: nothing.
FILENAMES = {
    TableKind.ENEMIES: "enemies.csv",
    TableKind.COINS: "coins.csv",
    TableKind.DOORS: "doors.csv",
}


@dataclass(frozen=True)
class LevelTables:
    """One level directory, expanded into the tables it holds."""

    map_name: str
    directory: Path
    tables: list[TableRef]


def expand(mod) -> list[LevelTables]:
    """Every level this mod declares, as the tables each contributes.

    Raises rather than skipping: a level directory that is absent, empty, or
    holding a misspelled filename is a mod that silently does less than it says.
    """
    found: list[LevelTables] = []
    for level in mod.manifest.levels:
        directory = mod.root / level.path
        where = f"levels: {level.path}"
        if not directory.is_dir():
            raise ManifestError(f"{where}: no such directory")

        tables = [
            TableRef(kind=kind, path=f"{level.path}/{name}", map_name=level.map_name)
            for kind, name in FILENAMES.items()
            if (directory / name).is_file()
        ]
        _refuse_strays(directory, where)
        _refuse_doors_without_code(mod, tables, where)
        if not tables:
            listed = ", ".join(FILENAMES.values())
            raise ManifestError(
                f"{where}: holds none of {listed}, so the level contributes "
                f"nothing.\n"
                f"  Remove it from 'levels', or add one of those files."
            )
        found.append(
            LevelTables(map_name=level.map_name, directory=directory, tables=tables)
        )
    return found


def _refuse_doors_without_code(mod, tables: list[TableRef], where: str) -> None:
    """⚠️ The same rule `Manifest.__post_init__` enforces for a declared doors
    table, applied where a level supplies one.

    The manifest check cannot see a level's tables, so without this a level
    holding `doors.csv` and a mod with no `code` block would compile nothing and
    report success (D134, D145).
    """
    if mod.manifest.code is not None:
        return
    if any(ref.kind is TableKind.DOORS for ref in tables):
        raise ManifestError(
            f"{where}: holds {FILENAMES[TableKind.DOORS]}, which patches "
            f"scripts, so this mod needs a 'code' block whose sources define "
            f"the functions its 'call' column names.\n"
            f"  Without one the table would be read by nothing and the build "
            f"would report success having patched nothing."
        )


def _refuse_strays(directory: Path, where: str) -> None:
    """⚠️ A `.csv` that is not a known kind is a typo, and a silent one.

    `enemys.csv` in a level directory would be read by nothing and the build
    would report success -- D126's shape exactly, which is why this is an error
    rather than a warning.
    """
    known = set(FILENAMES.values())
    strays = sorted(
        entry.name
        for entry in directory.iterdir()
        if entry.is_file() and entry.suffix.lower() == ".csv" and entry.name not in known
    )
    if strays:
        raise ManifestError(
            f"{where}: {', '.join(strays)} is not a level table.\n"
            f"  A level directory holds {', '.join(sorted(known))}; anything "
            f"else would be read by nothing."
        )


def tables_for(mod, kind: TableKind) -> list[TableRef]:
    """Every table of one kind this mod declares, from both `tables` and `levels`.

    ⚠️ **Call this, not `manifest.tables_of`.** The manifest holds only what was
    written literally; a level's tables exist on disk and are discovered here,
    where the mod's directory is known.
    """
    return mod.manifest.tables_of(kind) + [
        ref for level in expand(mod) for ref in level.tables if ref.kind is kind
    ]
