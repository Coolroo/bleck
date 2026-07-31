"""⛔ Nothing `bleck` ships may contain the game's own words.

Addresses, struct offsets, internal identifiers and enum member names are
*facts* about the game and are fine to record — `CLAUDE.md` says so, and the
catalogs carry the MIT attribution for the spm-headers material they derive
from.

An item's **English display name is not a fact, it is Nintendo's text.** 538 of
them shipped inside the PyInstaller binary until D194, read out of
`files/msg/UK`. They are now resolved at runtime from whatever disc the user
extracted, and this file exists so they cannot come back by accident — a
regenerated catalog is one `scripts/dump_items.py --headers` away from
reintroducing them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Everything `bleck.spec` bundles into the shipped binary.
BUNDLED = (
    "bleck/backends/mapcatalog.json",
    "bleck/backends/doorcatalog.json",
    "bleck/formats/npccatalog.json",
    "bleck/formats/itemcatalog.json",
    "bleck/script/catalog.json",
)


def rows_of(body) -> list:
    """Every record in a catalog, whatever it calls its list."""
    found = []
    for value in body.values() if isinstance(body, dict) else []:
        if isinstance(value, list):
            found += [row for row in value if isinstance(row, dict)]
    return found


@pytest.mark.parametrize("relative", BUNDLED)
def test_no_bundled_catalog_carries_item_display_text(relative: str):
    """⛔ The specific 538 strings that shipped, by the field they lived in."""
    path = REPO / relative
    if not path.is_file():
        pytest.skip(f"{relative} not present")
    body = json.loads(path.read_text(encoding="utf-8"))
    guilty = [row for row in rows_of(body) if row.get("msg") and row.get("english")]
    assert not guilty, (
        f"{relative}: {len(guilty)} row(s) carry text resolved from the game's "
        f"own files/msg/. Ship the `msg` key; resolve the words at runtime."
    )


def test_the_item_catalog_still_carries_the_key_to_resolve_with():
    """⚠️ Stripping the text is only safe because the key survives."""
    body = json.loads((REPO / "bleck/formats/itemcatalog.json").read_text("utf-8"))
    keyed = sum(1 for row in body["items"] if row.get("msg"))
    assert keyed > 500, f"only {keyed} items carry a message key"


def test_tribe_names_are_kept_because_they_are_not_game_text():
    """⚠️ The distinction that makes this surgical rather than blunt.

    Tribe English names come from spm-headers' `NPCTribeId` enum members --
    `NPC_FLIP_GOOMBA` becomes "Flip Goomba" -- which is MIT-licensed source
    code, not the game's message files. Deleting them too would have lost data
    this project is entitled to ship.
    """
    body = json.loads((REPO / "bleck/formats/npccatalog.json").read_text("utf-8"))
    named = [t for t in body["tribes"] if t.get("english")]
    assert len(named) > 400
    assert not any(t.get("msg") for t in named)
