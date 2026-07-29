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

from dataclasses import dataclass, field
from pathlib import Path

from bleck.common.errors import BleckError
from bleck.formats import lz77, setup, tables, u8
from bleck.mods.manifest import (
    MANIFEST_NAME,
    ItemEdit,
    MapPlacements,
    PlacementEdit,
    TableKind,
)
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
    items_applied: int = 0
    items_before: int = 0
    items_after: int = 0

    warnings: list[str] = field(default_factory=list)
    """Empty today. It held the item-count warning until D129 measured that
    growing an existing section is fine; the plumbing stays because
    `bleck mod build` already collects these and the next placement finding
    should not have to re-add it."""

    def describe(self) -> str:
        out = (
            f"{self.mod}: {self.map_name} setup, {self.applied} edit(s) "
            f"-> {self.used_before} enemies becomes {self.used_after}"
        )
        # Reported only when there are any: every map has enemies and 14 of 227
        # have items, so an unconditional ", 0 items" would be noise on nearly
        # every line.
        if self.items_applied or self.items_before:
            out += (
                f", {self.items_applied} item edit(s) "
                f"-> {self.items_before} items becomes {self.items_after}"
            )
        return out


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

    ⚠️ Enemies and items merge **per map**, not per source, because both end up
    in one generated `.dat`. A mod that adds an enemy in a table and a coin
    inline must not produce two files, the second overwriting the first.
    """
    declared: dict[str, list[SourcedEdit]] = {}
    items: dict[str, list[SourcedItem]] = {}
    for placement in mod.manifest.setup:
        where = f"{MANIFEST_NAME} setup.{placement.map_name}"
        declared.setdefault(placement.map_name, []).extend(
            SourcedEdit(edit=edit, source=where) for edit in placement.edits
        )
        items.setdefault(placement.map_name, []).extend(
            SourcedItem(edit=edit, source=where) for edit in placement.items
        )

    for row in _table_rows(mod):
        declared.setdefault(row.map_name, []).append(
            SourcedEdit(edit=_edit_of(row), source=f"{row.source}:{row.line}")
        )
    for row in _item_rows(mod):
        items.setdefault(row.map_name, []).append(
            SourcedItem(edit=_item_of(row), source=f"{row.source}:{row.line}")
        )

    for map_name, found in declared.items():
        _refuse_collisions(mod, map_name, found)
    for map_name, found_items in items.items():
        _refuse_item_collisions(mod, map_name, found_items)

    return [
        MapPlacements(
            map_name=name,
            edits=[item.edit for item in declared.get(name, [])],
            items=[item.edit for item in items.get(name, [])],
        )
        for name in dict.fromkeys([*declared, *items])
    ]


@dataclass(frozen=True)
class SourcedItem:
    """One item edit and where it was written, so a collision can name both."""

    edit: ItemEdit
    source: str


@dataclass(frozen=True)
class SourcedRow:
    """A table row that remembers which file it was read from."""

    row: tables.enemies.Row
    source: str

    @property
    def map_name(self) -> str:
        return self.row.map_name

    @property
    def line(self) -> int:
        return self.row.line


@dataclass(frozen=True)
class SourcedItemRow:
    """An item table row that remembers which file it was read from."""

    row: tables.items.Row
    source: str

    @property
    def map_name(self) -> str:
        return self.row.map_name

    @property
    def line(self) -> int:
        return self.row.line


def _table_path(mod: Mod, ref) -> Path:
    path = mod.root / ref.path
    if not path.is_file():
        raise EditError(
            f"{mod.name}: no table at {ref.path}, declared under "
            f"'tables.{ref.kind}' in {MANIFEST_NAME}"
        )
    return path


def _item_rows(mod: Mod) -> list[SourcedItemRow]:
    """Every item-table row this mod declares."""
    out: list[SourcedItemRow] = []
    for ref in mod.manifest.tables_of(TableKind.ITEMS):
        table = tables.items.read(
            _table_path(mod, ref), source=ref.path, map_name=ref.map_name
        )
        out += [SourcedItemRow(row=row, source=table.source) for row in table.rows]
    return out


def _item_of(sourced: SourcedItemRow) -> ItemEdit:
    """An item table row as the same declaration an inline edit makes."""
    row = sourced.row
    return ItemEdit(
        index=row.index,
        position=row.position,
        type=row.type,
        flags=row.flags,
        clear=row.clear,
    )


def _table_rows(mod: Mod) -> list[SourcedRow]:
    """Every enemy-table row this mod declares.

    ⚠️ **`tables_of`, not `tables`.** These rows become enemy placements, so
    only the tables that say they are enemy tables belong here; the kinds still
    to come describe other things entirely (D125).
    """
    out: list[SourcedRow] = []
    for ref in mod.manifest.tables_of(TableKind.ENEMIES):
        table = tables.enemies.read(
            _table_path(mod, ref), source=ref.path, map_name=ref.map_name
        )
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


def _refuse_item_collisions(mod: Mod, map_name: str, declared: list[SourcedItem]) -> None:
    """Refuse one mod editing the same item twice.

    ⚠️ Only *indexed* edits can collide. Two rows that both add an item are two
    items, which is the whole point -- deduplicating adds would make a table of
    thirty coins silently place fewer.
    """
    seen: dict[int, str] = {}
    for item in declared:
        if item.edit.index is None:
            continue
        first = seen.get(item.edit.index)
        if first is not None:
            raise EditError(
                f"{mod.name}: item {item.edit.index} of {map_name} is declared "
                f"twice -- in {first} and in {item.source}.\n"
                f"  Which one wins is not defined, so declare it in one place."
            )
        seen[item.edit.index] = item.source


def _refuse_new_section(mod: Mod, placement, data: setup.SetupFile) -> None:
    """⛔ Refuse giving items to a map that ships none. **It hangs the game.**

    D126 reasoned that it should work: the game reads `itemCount` at `0x2BC4`
    whatever the file's length, and for the 213 maps that end exactly there it
    lands on zeroed padding, so a real count written at that offset should be
    read the same way. D127 tested it -- three coins on `he1_01`, byte-for-byte
    the same section shape `he1_03` ships -- and the map never rendered.

    Refused rather than warned about, because the output is a disc that hangs on
    entering the map. A warning scrolls past; this cannot.

    ⚠️ **Which part is fatal is still unknown**: the coins needing an asset the
    map does not load, or the file growing at all. `mods/items-empty` is built
    to split those and has not been run.
    """
    if data.has_item_section or not placement.items:
        return
    raise EditError(
        f"{mod.name}: {placement.map_name} ships no item section, and adding "
        f"one hangs the game (D127).\n"
        f"  Measured, not assumed: three coins on he1_01 -- a section shaped "
        f"exactly like the one he1_03 ships -- and the map never rendered.\n"
        f"  Only 14 of the game's 227 maps place items; those can be edited. "
        f"`bleck setup show <map>` says whether a map is one of them."
    )


def _apply_items(mod: Mod, placement, data: setup.SetupFile) -> list[setup.Item]:
    """The map's item list with this mod's edits applied.

    ⚠️ **Indexed edits resolve against the list as it shipped**, then removals
    happen, then additions append. So the order rows appear in cannot change
    what a table means -- an author should not have to reason about whether
    row 4 renumbered the item row 5 refers to.
    """
    _refuse_new_section(mod, placement, data)

    kept = list(data.items)
    added: list[setup.Item] = []
    removed: set[int] = set()

    for edit in placement.items:
        if edit.index is None:
            added.append(
                setup.Item(
                    flags=setup.Item.SPAWNS if edit.flags is None else edit.flags,
                    type=setup.Item.COIN if edit.type is None else edit.type,
                    position=edit.position,
                )
            )
            continue
        if edit.index >= len(kept):
            raise EditError(
                f"{mod.name}: {placement.map_name} places {len(kept)} item(s), "
                f"so there is no item {edit.index}.\n"
                f"  Leave 'index' empty to add one; "
                f"`bleck setup show {placement.map_name}` lists what is there."
            )
        if edit.clear:
            removed.add(edit.index)
            continue
        kept[edit.index] = _edited_item(kept[edit.index], edit)

    items = [item for index, item in enumerate(kept) if index not in removed] + added
    if len(items) > setup.MAX_ITEMS:
        raise EditError(
            f"{mod.name}: {placement.map_name} would place {len(items)} items, "
            f"and the game loads at most {setup.MAX_ITEMS}.\n"
            f"  The loader allocates {setup.MAX_ITEMS * 16} bytes and then "
            f"memcpys the file's own count into it, unchecked -- so a longer "
            f"list overruns the allocation rather than being truncated (D128).\n"
            f"  The busiest map the game ships places 48."
        )
    return items


def _edited_item(item: setup.Item, edit) -> setup.Item:
    return setup.Item(
        flags=item.flags if edit.flags is None else edit.flags,
        type=item.type if edit.type is None else edit.type,
        position=item.position if edit.position is None else edit.position,
    )


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

    items = _apply_items(mod, placement, data)
    updated = setup.SetupFile(
        version=data.version,
        enemies=slots,
        items=items,
        item_version=data.item_version,
        # ⚠️ Adding an item to a map that ships none has to *create* the
        # section. The game reads `itemCount` at 0x2BC4 either way -- for the
        # 213 maps without one that is past the end of the file, where upstream
        # notes it reads zeroed padding -- so writing a real count there is
        # read normally. 🔶 Not yet watched happen in game.
        has_item_section=data.has_item_section or bool(items),
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
        items_applied=len(placement.items),
        items_before=len(data.items),
        items_after=len(updated.items),
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
