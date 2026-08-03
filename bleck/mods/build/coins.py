"""A map's coins: the item section of a setup file, and the flag budget it costs.

Split from `edits`, which builds the enemy list of the same file. The two are
separate concerns that meet in one `.dat`: an enemy is a slot in a fixed table,
a coin is an entry in a variable-length section, and a coin additionally spends
a **save flag** out of a per-map budget that adding one can overflow.

⛔ **That overflow hangs the game**, which is why the budget check is here and
not in the manifest — it needs the base disc's DOL, and by the time a build has
that it also has the shipped item list to compare against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bleck.backends import coinflags
from bleck.formats import setup, tables
from bleck.mods.build.editbase import EditError, table_path
from bleck.mods.manifest import CoinEdit, TableKind
from bleck.mods.registry import Mod

#: Where the coin-flag table is read from, relative to an extracted base.
DOL_PATH = "sys/main.dol"


@dataclass(frozen=True)
class CoinResult:
    """A map's rebuilt coin list, and anything the build wants to say about it."""

    items: list[setup.Item]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourcedCoin:
    """One coin edit and where it was written, so a collision can name both."""

    edit: CoinEdit
    source: str


@dataclass(frozen=True)
class SourcedCoinRow:
    """A coin table row that remembers which file it was read from."""

    row: tables.coins.Row
    source: str

    @property
    def map_name(self) -> str:
        return self.row.map_name

    @property
    def line(self) -> int:
        return self.row.line


def coin_rows(mod: Mod) -> list[SourcedCoinRow]:
    """Every coin-table row this mod declares."""
    # pylint: disable=container-return
    out: list[SourcedCoinRow] = []
    for ref in mod.tables_of(TableKind.COINS):
        table = tables.coins.read(
            table_path(mod, ref), source=ref.path, map_name=ref.map_name
        )
        out += [SourcedCoinRow(row=row, source=table.source) for row in table.rows]
    return out


def coin_of(sourced: SourcedCoinRow) -> CoinEdit:
    """A coin table row as the same declaration an inline edit makes."""
    row = sourced.row
    return CoinEdit(
        index=row.index,
        position=row.position,
        flags=row.flags,
        clear=row.clear,
    )


def refuse_coin_collisions(mod: Mod, map_name: str, declared: list[SourcedCoin]) -> None:
    """Refuse one mod editing the same coin twice.

    ⚠️ Only *indexed* edits can collide. Two rows that both add an item are two
    coins, which is the whole point -- deduplicating adds would make a table of
    thirty coins silently place fewer.
    """
    seen: dict[int, str] = {}
    for item in declared:
        if item.edit.index is None:
            continue
        first = seen.get(item.edit.index)
        if first is not None:
            raise EditError(
                f"{mod.name}: coin {item.edit.index} of {map_name} is declared "
                f"twice -- in {first} and in {item.source}.\n"
                f"  Which one wins is not defined, so declare it in one place."
            )
        seen[item.edit.index] = item.source


def _check_coin_budget(
    mod: Mod, placement, data: setup.SetupFile, base: Path
) -> list[str]:
    """Refuse the coin additions measured to hang, and warn about the rest.

    ✅ **The reason, in the game's own words** (D130). Hooking `__assert2`:
    `swdrv.c:505`, `(wp->gameCoinId - 1) < assign_tbl[i].num`, message
    `コインのフラグが溢れました` -- "the coin flags have overflowed".

    A coin is *persistent*, so each owns a save flag from a per-map budget in
    `assign_tbl`. **The budget is spent by coins the setup file cannot see** --
    coins in blocks are map objects. `he1_01`'s budget is 4, it ships no setup
    items, and one added coin still overflowed; `gameCoinId` was 5 when the
    assert fired.

    Three cases, all measured (D130, D133):

    | map | one added coin |
    |---|---|
    | in `assign_tbl`, ships coins (`he1_03`, 62/5) | ✅ works |
    | in `assign_tbl`, ships none (`he1_01` 4, `he2_02` 29) | ⛔ **asserts** |
    | **not** in `assign_tbl` (`an1_02`) | ✅ works, flag id -1 |

    ⚠️ **Absence from the table is the common case, not a failure**: 204 of the
    227 maps with a setup file have no entry, the allocator returns -1 instead of
    asserting, and the collected-check reads -1 as "not collected". Refusing
    those -- which is what the first version of this guard did -- blocks the
    large majority of maps for no reason.

    🔶 A -1 flag has nowhere to record the coin being picked up, so such a coin
    may reappear on every map load. Warned about, not refused: it is a gameplay
    surprise, not a hang, and nothing has measured it either way.
    """
    # pylint: disable=container-return
    if not placement.coins:
        return []

    budgets = coinflags.read(base / DOL_PATH)
    if not budgets:
        # ⚠️ Unknown, not "no budgets". Fall back to the conservative rule so a
        # build against an unreadable DOL cannot emit a disc that hangs.
        if data.has_item_section:
            return []
        raise EditError(
            f"{mod.name}: cannot read the coin-flag table out of "
            f"{base / DOL_PATH}, so whether {placement.map_name} has room for a "
            f"coin is unknown.\n"
            f"  Adding one to a map with no room hangs the game (D130), so this "
            f"is refused rather than guessed."
        )

    entry = budgets.find(placement.map_name)
    if entry is None:
        return [
            f"{mod.name}: {placement.map_name} has no coin-flag budget, so its "
            f"coins get flag id -1 and the game has nowhere to record them as "
            f"collected. They spawn (D133), but may come back every time the "
            f"map loads."
        ]

    if not data.has_item_section:
        raise EditError(
            f"{mod.name}: {placement.map_name} reserves {entry.flags} coin "
            f"flag(s) and places no coins of its own in the setup file, which "
            f"means its blocks have already spent them. Adding one hangs the "
            f"game (D130).\n"
            f"  A coin needs a save flag so it stays collected, and the game "
            f"asserts 'the coin flags have overflowed' before the map finishes "
            f"loading.\n"
            f"  Maps with no budget entry at all take coins fine -- it is "
            f"specifically the ones already at their limit that cannot."
        )
    return []


def apply_coins(mod: Mod, placement, data: setup.SetupFile, base: Path) -> CoinResult:
    """The map's item list with this mod's edits applied.

    ⚠️ **Indexed edits resolve against the list as it shipped**, then removals
    happen, then additions append. So the order rows appear in cannot change
    what a table means -- an author should not have to reason about whether
    row 4 renumbered the item row 5 refers to.
    """
    notes = _check_coin_budget(mod, placement, data, base)

    kept = list(data.items)
    added: list[setup.Item] = []
    removed: set[int] = set()

    for edit in placement.coins:
        if edit.index is None:
            added.append(
                setup.Item(
                    flags=setup.Item.SPAWNS if edit.flags is None else edit.flags,
                    type=setup.Item.COIN,
                    position=edit.position,
                )
            )
            continue
        if edit.index >= len(kept):
            raise EditError(
                f"{mod.name}: {placement.map_name} places {len(kept)} coin(s), "
                f"so there is no coin {edit.index}.\n"
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
    return CoinResult(items=items, warnings=notes)


def _edited_item(item: setup.Item, edit) -> setup.Item:
    return setup.Item(
        flags=item.flags if edit.flags is None else edit.flags,
        type=item.type,
        position=item.position if edit.position is None else edit.position,
    )
