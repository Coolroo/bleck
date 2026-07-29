"""Turning a `code.patches[].script` string into a kind and a target.

`map:he1_01`, `item:fire_burst`, `door:he1_01:0:init`, `npcdrv:2:onhit` — four
shapes with four sets of rules, split out of `codespec` because they are a
cohesive unit and it had reached its line ceiling.

⚠️ **A door index is bounds-checked against the committed catalog** (D141), an
item name is resolved through the item catalog (D114), and a map name is only
shape-checked — `mapDataPtr` is the authority and it is a run-time one.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from bleck.backends import doors
from bleck.formats import items
from bleck.mods.errors import ManifestError
from bleck.script import emit

#: Re-exported so a reader need not know the enum lives in the emitter.
PatchKind = emit.PatchKind

#: Kinds known to exist that have no mechanism yet, and why. Named separately so
#: asking for one gets the reason rather than "unsupported".
#:
#: ⚠️ Deliberately **not** `PatchKind` members. A key here is a selector bleck
#: recognises well enough to explain and refuses to accept; making it a member
#: would put it in `SUPPORTED_SELECTORS` and in every "here is what works" list.
#: ⛔ `door` was here until D101/D102. It is now a real kind: the descriptor
#: array's address sits in the map's init script as a `USER_FUNC` argument, so
#: no interception is needed. D93 and D94 concluded otherwise by searching for
#: one function at the argument count `evt_door.h` declares, which is wrong.
DEFERRED_PATCH_KINDS: dict[str, str] = {}

#: Shape only. `mapDataPtr` is the authority on whether a map exists, and
#: that is a run-time question.
_MAP_NAME_RE = re.compile(r"^[a-z0-9_]{1,16}$")


@dataclass(frozen=True)
class _Selector:
    """A `code.patches[].script` value split into its two halves."""

    kind: PatchKind
    target: str

    item_id: int = -1
    """The id an `item:` target names, once a name has been resolved."""


def _parse_selector(raw: str, where: str) -> _Selector:
    """Split `map:he1_01`, `item:0x41` or `item:fire_burst` into kind and target."""
    name, _, target = raw.partition(":")
    if name in DEFERRED_PATCH_KINDS:
        raise ManifestError(
            f"{where}: 'script' is {raw!r}, and bleck has no mechanism for "
            f"{name!r} scripts.\n  {DEFERRED_PATCH_KINDS[name]}\n"
            f"  Supported selectors: {emit.SUPPORTED_SELECTORS}."
        )
    kind = PatchKind.parse(name)
    if kind is None or not target:
        raise ManifestError(
            f"{where}: 'script' is {raw!r}, which names no script bleck can "
            f"reach.\n  Supported selectors: {emit.SUPPORTED_SELECTORS}.\n"
            f"  'map:he1_01' patches that map's init script; 'item:0x41' (or "
            f"'item:fire_burst') patches that item's use script; 'door:he1_01:0' "
            f"patches the interact script of that map's first door."
        )
    if kind is PatchKind.ITEM:
        return _parse_item_target(target, where)
    if kind is PatchKind.DOOR:
        return _Selector(kind=kind, target=_parse_door(target, where))
    if kind is PatchKind.NPC:
        return _Selector(kind=kind, target=_parse_npc(target, where))
    _check_map_name(target, where)
    return _Selector(kind=kind, target=target)


def _check_map_name(name: str, where: str) -> None:
    if _MAP_NAME_RE.match(name):
        return
    raise ManifestError(
        f"{where}: {name!r} is not a map name. They look like 'he1_01' -- "
        f"lowercase letters, digits and underscores.\n"
        f"  `bleck maps` lists all 383 of them."
    )


def _parse_door(raw: str, where: str) -> str:
    """Check `he1_01:0` or `he1_01:0:init`, and hand it back as written.

    ✅ **The index IS bounds-checked now**, against the committed door catalog
    (D141). It used to be a run-time question -- "how many doors a map
    registers is in the game's data" -- and the generated code still reports
    NO_SCRIPT rather than reading past the end. But a selector that can never
    match is a mistake, not a run-time condition, and `mods/door-attended`
    carried `door:he1_01:9` for weeks while `he1_01` has exactly one door.

    ⚠️ **An absent catalog means "unknown", not "no doors".** Refusing every
    selector because a data file was not shipped would be worse than the silence
    this replaces, so the check is skipped rather than failed.
    """
    parts = raw.split(":")
    if len(parts) not in (2, 3) or not all(parts[:2]):
        raise ManifestError(
            f"{where}: 'door:{raw}' names no door.\n"
            f"  A door selector is 'door:<map>:<index>', with an optional "
            f"script -- 'door:he1_01:0' is that map's first door, and "
            f"'door:he1_01:0:init' is the same door's init script.\n"
            f"  A map registers its doors in order, so the index is a position "
            f"in that list, not an id. `mods/door-scan` reports how many a map "
            f"has."
        )
    _check_map_name(parts[0], where)
    try:
        value = int(parts[1], 0)
    except ValueError:
        raise ManifestError(
            f"{where}: door index {parts[1]!r} is not a number. Write "
            f"'door:{parts[0]}:0' for the first door."
        ) from None
    if value < 0:
        raise ManifestError(f"{where}: door index {parts[1]!r} cannot be negative")
    if len(parts) == 3:
        _check_door_script(parts[2], raw, where)
    problem = doors.selector_problem(parts[0], value)
    if problem:
        raise ManifestError(f"{where}: {problem}")
    return raw


def _parse_npc(raw: str, where: str) -> str:
    """Check `2:onhit` and hand it back as written.

    ⚠️ The template id is **not** range-checked: how many templates the table
    holds was never measured (D111), so a build-time bound would be invented
    rather than known. The generated code compares against a measured entry
    count instead.
    """
    parts = raw.split(":")
    if len(parts) != 2 or not all(parts):
        raise ManifestError(
            f"{where}: 'npcdrv:{raw}' names no enemy script.\n"
            f"  A template selector is 'npcdrv:<template>:<script>' -- "
            f"'npcdrv:2:onhit' is what a Goomba does when hit.\n"
            f"  `bleck setup show <map>` prints the template id of every enemy "
            f"a map places."
        )
    try:
        value = int(parts[0], 0)
    except ValueError:
        raise ManifestError(
            f"{where}: template {parts[0]!r} is not a number. It is the id "
            f"`bleck setup show` prints, e.g. 'npcdrv:2:onhit'."
        ) from None
    if value < 0:
        raise ManifestError(f"{where}: template id {parts[0]!r} cannot be negative")
    if emit.NpcScript.parse(parts[1]) is None:
        known = ", ".join(emit.NPC_SCRIPTS)
        close = difflib.get_close_matches(parts[1], emit.NPC_SCRIPTS, n=1, cutoff=0.6)
        hint = f"\n  Did you mean {close[0]!r}?" if close else ""
        raise ManifestError(
            f"{where}: 'npcdrv:{raw}' names {parts[1]!r}, which is not one of an "
            f"enemy template's scripts.{hint}\n  A template carries: {known}.\n"
            f"  There is no default -- none of the four is the obvious one."
        )
    return raw


def _check_door_script(name: str, raw: str, where: str) -> None:
    """Which of the three scripts a `DoorDesc` carries, when one is named."""
    if emit.DoorScript.parse(name) is not None:
        return
    known = ", ".join(emit.DOOR_SCRIPTS)
    close = difflib.get_close_matches(name, emit.DOOR_SCRIPTS, n=1, cutoff=0.6)
    hint = f"\n  Did you mean {close[0]!r}?" if close else ""
    raise ManifestError(
        f"{where}: 'door:{raw}' names {name!r}, which is not one of a door's "
        f"scripts.{hint}\n"
        f"  A DoorDesc carries: {known}.\n"
        f"  Omitting it means 'interact' -- the script that runs when the "
        f"player uses the door."
    )


def _parse_item_target(raw: str, where: str) -> _Selector:
    """Resolve an `item:` target: a whole number, or a name from the catalog.

    The target is handed back **as written**, with the id beside it. A manifest
    that says `fire_burst` still says `fire_burst` after a round trip -- the
    number is what the build needs, not what the author wrote (D114).

    ⚠️ Membership is not checked for a number: `itemEventDataTable` lives in the
    game's data, so "is there such an item" is a run-time question. The generated
    code answers it with a NOT_FOUND status rather than patching a fallback. A
    *name* is checked, because the catalog is what turns it into a number at all.
    """
    try:
        value = int(raw, 0)
    except ValueError:
        resolved = _resolve_item(raw, where)
        return _Selector(kind=PatchKind.ITEM, target=raw, item_id=resolved)
    if value < 0:
        raise ManifestError(f"{where}: item id {raw!r} cannot be negative")
    return _Selector(kind=PatchKind.ITEM, target=raw, item_id=value)


#: How many candidates an ambiguous item name lists before it summarises.
AMBIGUOUS_SHOWN = 6


def _resolve_item(raw: str, where: str) -> int:
    """The id a written item name means, or a `ManifestError` saying why not.

    ⚠️ Resolution runs **before** the catalog is checked for: since `ItemId` is
    a module, an `ITEM_ID_*` constant resolves with no JSON on disk and only the
    English name needs one (D119). Asking first is what tells the two apart.
    """
    known = items.catalog()
    match = known.resolve(raw)
    if match.item is not None:
        return match.item.id
    if match.ambiguous:
        # Capped: `unavailable_item` is the English name of eighteen ids, and a
        # wall of them buries the sentence that says what to do about it.
        shown = match.ambiguous[:AMBIGUOUS_SHOWN]
        # ⚠️ `constant`, never `enum`: an `ItemId` is an int and formats as one.
        listed = "\n".join(
            f"    {found.selector:<12} {found.describe()}  [{found.constant}]"
            for found in shown
        )
        rest = len(match.ambiguous) - len(shown)
        more = f"\n    ... and {rest} more" if rest else ""
        raise ManifestError(
            f"{where}: {raw!r} names {len(match.ambiguous)} items, so bleck "
            f"cannot tell which one is meant:\n{listed}{more}\n"
            f"  Write the id, or the full ITEM_ID_* constant."
        )
    hint = (
        f"\n  Did you mean {', '.join(repr(near) for near in match.near)}?"
        if match.near
        else ""
    )
    if not known:
        raise ManifestError(
            f"{where}: {raw!r} is a name, and bleck has no item catalog to "
            f"resolve it with ({items.ITEM_CATALOG} is missing) -- without it "
            f"only the ITEM_ID_* constants resolve, since those live in "
            f"itemids.py.{hint}\n  Write the id instead -- 'item:65' or "
            f"'item:0x41' -- or regenerate it with scripts/dump_items.py."
        )
    raise ManifestError(
        f"{where}: {raw!r} is neither an item id nor an item bleck knows.{hint}\n"
        f"  An item is written as a number -- 'item:65', 'item:0x41' -- or as a "
        f"name: its internal name ('HONOO_SAKURETU'), its constant "
        f"('ITEM_ID_USE_HONOO_SAKURETU'), or its English name ('fire_burst').\n"
        f"  All {len(known)} names are in {items.ITEM_CATALOG.name}; "
        f"`mods/item-probe` reports which ids itemEventDataTable holds."
    )
