"""Turning declared edits into the files a build ships.

A mod says "slot 3 is template 42 at (100, 0, 0)" and this derives the bytes
(`docs/vision.md`). It can say it inline under `setup` in `mod.json` or in a CSV
table under `tables`; the two merge here, and declaring the same slot in both is
refused (D124).

⚠️ **Both copies of a setup file are written** — which one drives spawning is
unestablished (D53, D59), so writing both is correct either way.

⚠️ Runs before the overlay is planned: the plan comes from walking `overlay/`,
so a generated file must exist by then.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck.common.errors import BleckError
from bleck.formats import lz77, setup, tables, u8
from bleck.mods.manifest import MANIFEST_NAME, MapPlacements, PlacementEdit, TableKind
from bleck.mods.registry import Mod
from bleck.mods.resolver import Chain


class EditError(BleckError):
    """A declared edit could not be applied."""


#: Where a map keeps its setup file, inside its own archive. Stored as
#: `./dvd/...`; the overlay drops the `./`, which `u8.member_key` reconciles
#: (D57).
MEMBER = "dvd/setup/{map_name}.dat"
ARCHIVE = "files/map/{map_name}.bin"

#: The other copy. Written too -- see the note in `_apply_map`.
STANDALONE = "files/setup/{map_name}.dat"


@dataclass(frozen=True)
class PlacementBuild:
    """One map's generated setup file, and what went into it."""

    mod: str
    map_name: str
    output: Path
    also_wrote: Path
    applied: int
    used_before: int
    used_after: int

    def describe(self) -> str:
        return (
            f"{self.mod}: {self.map_name} setup, {self.applied} edit(s) "
            f"-> {self.used_before} enemies becomes {self.used_after}"
        )


@dataclass(frozen=True)
class SourcedEdit:
    """One edit and where it was written, so a collision can name both.

    A `PlacementEdit` deliberately does not carry a filename -- it is what a mod
    *declares*, not where. Provenance is needed for exactly one message, so it
    rides alongside for exactly as long as that message might be needed.
    """

    edit: PlacementEdit
    source: str


def mods_with_placements(chain: Chain) -> list[Mod]:
    return [mod for mod in chain.mods if mod.manifest.has_placements]


def apply_chain(chain: Chain, base: Path) -> list[PlacementBuild]:
    """Generate every declared setup file in the chain, newest last."""
    built = []
    for mod in mods_with_placements(chain):
        for placement in placements_for(mod):
            built.append(_apply_map(mod, placement, base))
    return built


def placements_for(mod: Mod) -> list[MapPlacements]:
    """Everything this mod declares about placement, from both sources.

    Inline `setup` and CSV `tables` say the same thing in different shapes, so
    they merge here rather than in the manifest: this is the first point that
    has the mod's *directory*, and a table is a path until then.
    """
    declared: dict[str, list[SourcedEdit]] = {}
    for placement in mod.manifest.setup:
        found = declared.setdefault(placement.map_name, [])
        found += [
            SourcedEdit(edit=edit, source=f"{MANIFEST_NAME} setup.{placement.map_name}")
            for edit in placement.edits
        ]

    for row in _table_rows(mod):
        declared.setdefault(row.map_name, []).append(
            SourcedEdit(edit=_edit_of(row), source=f"{row.source}:{row.line}")
        )

    for map_name, found in declared.items():
        _refuse_collisions(mod, map_name, found)
    return [
        MapPlacements(map_name=name, edits=[item.edit for item in found])
        for name, found in declared.items()
    ]


@dataclass(frozen=True)
class SourcedRow:
    """A table row that remembers which file it was read from."""

    row: tables.TableRow
    source: str

    @property
    def map_name(self) -> str:
        return self.row.map_name

    @property
    def line(self) -> int:
        return self.row.line


def _table_rows(mod: Mod) -> list[SourcedRow]:
    """Every enemy-table row this mod declares.

    ⚠️ **`tables_of`, not `tables`.** These rows become enemy placements, so
    only the tables that say they are enemy tables belong here; the kinds still
    to come describe other things entirely (D125).
    """
    out: list[SourcedRow] = []
    for ref in mod.manifest.tables_of(TableKind.ENEMIES):
        path = mod.root / ref.path
        if not path.is_file():
            raise EditError(
                f"{mod.name}: no table at {ref.path}, declared under "
                f"'tables.{ref.kind}' in {MANIFEST_NAME}"
            )
        table = tables.read(path, source=ref.path, map_name=ref.map_name)
        out += [SourcedRow(row=row, source=table.source) for row in table.rows]
    return out


def _edit_of(sourced: SourcedRow) -> PlacementEdit:
    """A table row as the same declaration an inline edit makes."""
    row = sourced.row
    return PlacementEdit(
        slot=row.slot,
        template=row.template,
        position=row.position,
        clear=row.clear,
        copy_from=row.copy_from,
    )


def _refuse_collisions(mod: Mod, map_name: str, declared: list[SourcedEdit]) -> None:
    """Refuse one mod declaring the same slot twice.

    ⚠️ Within a mod this is ambiguous rather than a conflict: nothing says which
    of its own two statements the author meant, and picking the later one is how
    an afternoon disappears. **Across** mods it is an ordinary conflict and the
    existing chain order settles it.
    """
    seen: dict[int, str] = {}
    for item in declared:
        first = seen.get(item.edit.slot)
        if first is not None:
            raise EditError(
                f"{mod.name}: slot {item.edit.slot} of {map_name} is declared "
                f"twice -- in {first} and in {item.source}.\n"
                f"  Which one wins is not defined, so declare it in one place."
            )
        seen[item.edit.slot] = item.source


def _archive_member(base: Path, map_name: str) -> bytes:
    """The map's own setup file, read out of its archive.

    Taken from the archive rather than `files/setup/`: the two are
    byte-identical on the disc, and this copy travels with its map.
    """
    archive = base / ARCHIVE.format(map_name=map_name)
    if not archive.is_file():
        raise EditError(f"no map archive at {archive}")

    raw = archive.read_bytes()
    payload = lz77.decompress(raw) if lz77.is_lz77(raw) else raw
    if not u8.is_u8(payload):
        raise EditError(f"{archive} is not an archive")

    wanted = u8.member_key(MEMBER.format(map_name=map_name))
    for item in u8.read_all(payload):
        if u8.member_key(item.path) == wanted and item.data is not None:
            return item.data
    raise EditError(
        f"{map_name} has no setup file inside its archive, so it places nothing to edit"
    )


def _apply_map(mod: Mod, placement, base: Path) -> PlacementBuild:
    data = setup.parse(
        _archive_member(base, placement.map_name),
        origin=f"{placement.map_name}.dat",
    )
    before = len(data.used)

    # ⚠️ `copy_from` reads the **base** file, not the partly-edited one, so the
    # order rows appear in cannot change what a table means. Chained copies
    # would otherwise depend on line order, which is not a thing an author
    # should have to reason about.
    original = list(data.enemies)
    slots = list(data.enemies)
    for edit in placement.edits:
        source = None
        if edit.copy_from is not None:
            source = _copy_source(mod, placement, edit, original)
        slots[edit.slot] = _apply_edit(slots[edit.slot], edit, mod.name, source)

    updated = setup.SetupFile(
        version=data.version,
        enemies=slots,
        items=data.items,
        item_version=data.item_version,
        has_item_section=data.has_item_section,
    )
    _refuse_orphans(mod, placement, updated)

    # ⚠️ BOTH copies: which one drives spawning is unestablished (D53, D59),
    # so writing both is correct either way and leaves no stale copy.
    payload = updated.to_bytes()
    outputs = [
        mod.overlay
        / ARCHIVE.format(map_name=placement.map_name)
        / MEMBER.format(map_name=placement.map_name),
        mod.overlay / STANDALONE.format(map_name=placement.map_name),
    ]
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)

    return PlacementBuild(
        mod=mod.name,
        map_name=placement.map_name,
        output=outputs[0],
        also_wrote=outputs[1],
        applied=len(placement.edits),
        used_before=before,
        used_after=len(updated.used),
    )


def _refuse_orphans(mod: Mod, placement, updated: setup.SetupFile) -> None:
    """Refuse an edit that leaves a gap with used slots after it.

    ⚠️ **The game stops reading setup entries at the first empty one** (D79), so
    a cleared middle slot silently discards everything past it.

    Refused rather than compacted: renumbering would change what `{"slot": 2}`
    means in another mod's manifest.
    """
    empty = [i for i, enemy in enumerate(updated.enemies) if enemy.is_empty]
    if not empty:
        return
    first_gap = empty[0]
    orphaned = [
        index
        for index, enemy in enumerate(updated.enemies)
        if index > first_gap and not enemy.is_empty
    ]
    if not orphaned:
        return

    listed = ", ".join(str(index) for index in orphaned)
    raise EditError(
        f"{mod.name}: clearing slot {first_gap} of {placement.map_name} would "
        f"orphan slot(s) {listed}.\n"
        f"  The game stops reading setup entries at the first empty one, so "
        f"anything after a gap never spawns -- silently.\n"
        f"  Clear the last used slot instead, or move the later enemies down."
    )


def _copy_source(mod: Mod, placement, edit, original: list[setup.Enemy]) -> setup.Enemy:
    """The entry a `copy_from` edit builds on, refusing an empty one.

    ⚠️ **Copying an empty slot is refused rather than allowed to do nothing.**
    An unused slot is zeros, so the copy would carry nothing across and the edit
    would land on zeros exactly as if `copy_from` were absent -- an author who
    wrote it believing they had the shipped bytes would be wrong and could not
    tell. That is precisely the shape of the D123 run that measured a control
    which did not exist.
    """
    source = original[edit.copy_from]
    if source.is_empty:
        raise EditError(
            f"{mod.name}: slot {edit.slot} of {placement.map_name} copies from "
            f"slot {edit.copy_from}, which is empty.\n"
            f"  An empty slot is zeros, so the copy would carry nothing across "
            f"and the edit would build on zeros anyway (D123).\n"
            f"  `bleck setup show {placement.map_name}` lists the slots that "
            f"hold something."
        )
    return source


def _apply_edit(
    enemy: setup.Enemy, edit, mod_name: str, source: setup.Enemy | None = None
) -> setup.Enemy:
    try:
        if edit.clear:
            return enemy.cleared()
        if source is not None:
            enemy = enemy.copied_from(source)
        if edit.template is not None:
            enemy = enemy.with_template(edit.template)
        if edit.position is not None:
            enemy = enemy.with_position(edit.position)
        return enemy
    except setup.SetupError as exc:
        raise EditError(f"{mod_name}: {edit.describe()}\n  {exc}") from exc
