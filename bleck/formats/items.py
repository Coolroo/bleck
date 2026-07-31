"""`itemDataTable` names, so an `item:` selector can name an item.

An item's id is the only thing the game uses, and `item:0x41` is what a manifest
had to say. That number is unreadable: nothing in it says *Fire Burst*, so a
patch could not be reviewed without a lookup table in someone's head.

Two artifacts, and the split is deliberate (D119):

- **`itemids.py`** -- `ItemId`, one member per id, *generated* from
  spm-headers' `item_data_ids.h`. The ids and their constants.
- **`itemcatalog.json`** -- the names those ids have in the game: `itemName`,
  the message key, and the English text that key resolves to.

Both are committed rather than computed at build time -- `bleck` does not
require an extracted disc to read a manifest, and the strings live behind
pointers in the game's `.data` either way. `scripts/dump_items.py` regenerates
both from one read.

⚠️ **Names are a convenience.** An absent catalog is not an error: every id
keeps working, and since the ids now live in a module, so does every `ITEM_ID_*`
constant. Only the English tier needs the JSON.

Four spellings of the same item, all accepted (D114):

    item:0x41                        the id, unchanged and never looked up
    item:HONOO_SAKURETU              `itemName`, the internal name
    item:ITEM_ID_USE_HONOO_SAKURETU  the constant from `item_data_ids.h`
    item:fire_burst                  the English name, from `files/msg`
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from bleck.formats.itemids import ItemId

#: Item names, dumped from the game by `scripts/dump_items.py`. Committed
#: rather than recomputed: they exist only behind pointers in the DOL.
ITEM_CATALOG = Path(__file__).with_name("itemcatalog.json")

#: Every `ITEM_ID_*` constant carries it, so it is optional when writing one.
#: ⚠️ `itemgen.ENUM_PREFIX` is the same string and is deliberately a separate
#: definition -- importing it the other way would make the generator depend on
#: the module it generates.
ENUM_PREFIX = "ITEM_ID_"

#: Every id the game has, by value. Built once: `ItemId(...)` on an unknown
#: value raises, and "is there such an id" is asked per alias per lookup.
_MEMBERS = {int(member): member for member in ItemId}

_SEPARATORS = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """One spelling of a name, so case, dashes and spaces stop mattering.

    `Fire Burst`, `fire-burst` and `FIRE_BURST` are the same word to a person,
    and a selector that distinguished them would be a puzzle rather than a name.
    """
    return _SEPARATORS.sub("_", text.strip().lower()).strip("_")


@dataclass(frozen=True)
class ItemInfo:
    """One row of `itemDataTable`, as far as its names go."""

    id: int

    name: str = ""
    """`itemName`: the internal name, e.g. `HONOO_SAKURETU`. Romaji, not
    English -- the developers' name for it, which is why `english` exists."""

    enum: ItemId | None = None
    """The id as a named constant, or None for an id `ItemId` does not have.

    ⚠️ **An `ItemId` is an `int`.** `ItemId.NULL` is falsy and formats as `0`,
    so `if info.enum` is a bug for item 0 and `f"{info.enum}"` prints a number.
    Test with `is not None`; print `constant` (D119)."""

    msg: str = ""
    """`nameMsg`: a key into `files/msg/<language>`, not text."""

    english: str = ""
    """What `msg` resolves to in `files/msg/UK`, e.g. `Fire Burst`.

    ⛔ **Never shipped.** These are the game's own words, so the catalog carries
    only the `msg` key and this is filled in at load time from the user's own
    extracted disc (D194). Empty when there is no disc, which costs prettiness
    and nothing else."""

    def describe(self) -> str:
        if self.english and self.name:
            return f"{self.english} ({self.name})"
        return self.english or self.name or f"item {self.id}"

    @property
    def constant(self) -> str:
        """`ITEM_ID_USE_HONOO_SAKURETU`: the enum member spelled as C has it.

        The one place a member becomes text, because the obvious way -- putting
        it in an f-string -- yields its number instead.
        """
        return f"{ENUM_PREFIX}{self.enum.name}" if self.enum is not None else ""

    @property
    def selector(self) -> str:
        """How to write this item in a manifest, unambiguously."""
        return f"item:0x{self.id:x}"

    @property
    def group(self) -> str:
        """The family the constant puts it in: `USE`, `CARD`, `KEY`, ...

        Empty for `ITEM_ID_NULL`, which names no group.
        """
        short = self.enum.name if self.enum is not None else ""
        return short.split("_", 1)[0] if "_" in short else ""


@dataclass(frozen=True)
class GroupCount:
    """How many items one `ITEM_ID_*` group holds.

    The item answer to `maps.AreaCount`: 538 items in one flat list is not
    browsable, and the constant already sorts them -- `USE`, `CARD`, `KEY`.
    """

    group: str
    items: int

    def describe(self) -> str:
        # `ITEM_ID_NULL` names no group and is the only id that does not.
        return f"{self.group or '-':<10} {self.items:>4} items"


@dataclass(frozen=True)
class ItemMatch:
    """What a written name resolved to, and enough to explain it when it did not.

    Three outcomes, distinguished because they need different messages: one item
    (`item`), several (`ambiguous`), or none (`near` holds the closest names).
    """

    query: str
    item: ItemInfo | None = None
    ambiguous: list[ItemInfo] = field(default_factory=list)
    near: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.item is not None


class ItemNames:
    """Item names -> ids. The catalog supplies the names; `ItemId` the ids.

    Aliases are matched in tiers, most specific first, so an English name never
    shadows an internal one:

    1. `itemName`, the full `ITEM_ID_*` constant, and that constant without its
       `ITEM_ID_` prefix
    2. the constant without its group prefix too -- `HONOO_SAKURETU` for
       `ITEM_ID_USE_HONOO_SAKURETU`
    3. the English name

    A tier that matches decides the answer, even when it matches more than one
    item: falling through to the next tier would silently answer a different
    question than the one asked.

    ⚠️ **Tiers 1 and 2 come from `ItemId`, not from the catalog** (D119), so
    they still resolve when the JSON is missing. `itemName` and the English
    name do not, which is why the third tier can go quiet on its own.
    """

    def __init__(self, items=None) -> None:
        self._items = [_row(entry) for entry in items or []]
        self._by_id = {item.id: item for item in self._items}
        self._known = _merge(self._items)
        self._known_by_id = {info.id: info for info in self._known}
        self._tiers = [
            self._index(lambda info: [info.name, info.constant, _short(info)]),
            self._index(lambda info: [_bare(info)]),
            self._index(lambda info: [info.english]),
        ]

    def _index(self, aliases):  # pylint: disable=container-return
        table: dict[str, list[int]] = {}
        for info in self._known:
            for alias in aliases(info):
                key = normalize(alias)
                if not key:
                    continue
                found = table.setdefault(key, [])
                if info.id not in found:
                    found.append(info.id)
        return table

    def __bool__(self) -> bool:
        """Whether the *catalog* was read. Ids resolve either way."""
        return bool(self._items)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> list[ItemInfo]:
        """The catalog's own rows. Empty when the JSON is absent."""
        return list(self._items)

    @property
    def known(self) -> list[ItemInfo]:
        """Every id worth listing, catalog row or not, in id order.

        What a listing counts against, where `items` is what was *read*: with
        no catalog on disk this is still all 538 ids, because `ItemId` is a
        module (D119). The two lengths differing is the interesting case.
        """
        return list(self._known)

    def search(self, text: str) -> list[ItemInfo]:
        """Every item one of whose aliases contains `text`.

        Browsing, where `resolve` is identification: this answers "which items
        are worth looking at", so it matches on substrings and reports all of
        them rather than calling several a failure.

        ⚠️ It walks the **same tier tables** `resolve` does rather than
        rebuilding an alias list. A second list is a list that drifts, and the
        drift would show up as `bleck items` finding a name that a manifest
        then refuses (or worse, the reverse).
        """
        needle = normalize(text)
        if not needle:
            return self.known
        found = {
            item_id
            for tier in self._tiers
            for alias, ids in tier.items()
            if needle in alias
            for item_id in ids
        }
        return [info for info in self._known if info.id in found]

    def group(self, name: str) -> list[ItemInfo]:
        """Every item in one `ITEM_ID_*` group, e.g. `CARD`."""
        wanted = normalize(name)
        return [info for info in self._known if normalize(info.group) == wanted]

    def groups(self) -> list[GroupCount]:
        """The groups, largest first -- there are enough of them that
        alphabetical order buries the ones anybody is looking for."""
        counts: dict[str, int] = {}
        for info in self._known:
            counts[info.group] = counts.get(info.group, 0) + 1
        return sorted(
            (GroupCount(group=name, items=total) for name, total in counts.items()),
            key=lambda found: (-found.items, found.group),
        )

    def lookup(self, item_id: int) -> ItemInfo | None:
        """What an id names, or None when the catalog does not have it."""
        return self._by_id.get(item_id)

    def resolve(self, text: str) -> ItemMatch:
        """Find the item a written name means. Never raises: the caller has the
        context needed to phrase the failure, and there are three of them."""
        key = normalize(text)
        if not key:
            return ItemMatch(query=text)
        for tier in self._tiers:
            found = tier.get(key)
            if not found:
                continue
            if len(found) == 1:
                return ItemMatch(query=text, item=self._known_by_id[found[0]])
            return ItemMatch(
                query=text, ambiguous=[self._known_by_id[item_id] for item_id in found]
            )
        return ItemMatch(query=text, near=self.suggest(text))

    def suggest(self, text: str, limit: int = 3) -> list[str]:
        """The closest names to something that resolved to nothing."""
        every = sorted({alias for tier in self._tiers for alias in tier})
        return difflib.get_close_matches(normalize(text), every, n=limit, cutoff=0.6)


def _row(entry) -> ItemInfo:
    """One catalog row.

    ⚠️ The row's `enum` column is **not read**: the constant follows from the
    id, and `ItemId` is where ids are defined. Keeping the column is what lets
    `itemids.py` be regenerated from the JSON, and `tests/test_items.py` pins
    the two together.
    """
    item_id = int(entry.get("id", -1))
    return ItemInfo(
        id=item_id,
        name=str(entry.get("name", "")),
        enum=_MEMBERS.get(item_id),
        msg=str(entry.get("msg", "")),
        english=str(entry.get("english", "")),
    )


def _merge(rows: list[ItemInfo]) -> list[ItemInfo]:
    """Every id worth answering about, in id order.

    A catalog row where there is one, and a bare `ItemInfo` carrying only the
    constant where there is not -- which is every id when the catalog is absent.
    """
    by_id = {row.id: row for row in rows}
    every = sorted(set(by_id) | set(_MEMBERS))
    return [
        by_id[item_id]
        if item_id in by_id
        else ItemInfo(id=item_id, enum=_MEMBERS.get(item_id))
        for item_id in every
    ]


def _short(info: ItemInfo) -> str:
    """The constant without `ITEM_ID_`, which every one of them carries."""
    return info.enum.name if info.enum is not None else ""


def _bare(info: ItemInfo) -> str:
    """The constant without its group prefix as well, or empty when it has none.

    ⚠️ Deliberately a lower tier than the rest: `MARIO` is both a character item
    and a card, so dropping the group makes some names ambiguous. That is
    reported rather than resolved arbitrarily.
    """
    short = _short(info)
    return short.split("_", 1)[1] if "_" in short else ""


def load_items(path: Path | None = None, base: Path | None = None) -> ItemNames:
    """Read the committed item catalog. Absent is not an error: names are a
    convenience, and every id works without them.

    ⛔ English names come from the *user's* disc, never from this repository.
    The catalog ships each item's message key; `base` supplies the text behind
    it (D194).
    """
    source = path or ITEM_CATALOG
    if not source.is_file():
        return ItemNames()
    body = json.loads(source.read_text(encoding="utf-8"))
    return ItemNames(_with_english(body.get("items") or [], base))


def _with_english(rows: list, base: Path | None) -> list:
    # pylint: disable=container-return
    """Fill each row's `english` from the disc's message files, if there is one."""
    # ⚠️ `env`, not `registry.base_root()`. That would import `mods` from
    # `formats` and close an import cycle -- caught by `lint.sh --full`, which
    # a per-file check cannot see.
    from bleck.common import env  # pylint: disable=import-outside-toplevel
    from bleck.formats import msg  # pylint: disable=import-outside-toplevel

    if base is None:
        base = Path(env.text(env.BASE_DIR))
    table = msg.english(base)
    if table is None:
        return rows
    return [dict(row, english=table.get(str(row.get("msg", "")))) for row in rows]


@lru_cache(maxsize=1)
def catalog() -> ItemNames:
    """The catalog, read once. A manifest with many `item:` patches would
    otherwise re-read and re-index a 78 KB file per selector.

    Tests that swap `ITEM_CATALOG` must call `catalog.cache_clear()`.
    """
    return load_items()
