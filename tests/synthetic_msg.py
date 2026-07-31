"""A synthetic `files/msg/<lang>/` table, so tests can resolve English names.

⛔ **Every word in here is invented.** An item's English display name is the
game's own text, and D194 stopped shipping it: `itemcatalog.json` carries the
message key, and `bleck/formats/msg.py` resolves it against whatever disc the
user extracted. A CI runner has no disc, so every test covering that tier had
nothing to resolve against and failed.

They resolve against this table instead. The **keys** are the ones the committed
catalog already ships -- identifiers, not prose -- and the words behind them are
made up, which is what keeps `tests/test_no_game_text.py` honest: a real name
here would read as game data to whoever finds it next, and the fixture would
become the thing that file exists to forbid.

⚠️ **One key, many items.** `msg_unknown_item` is the key of 18 different ids,
so naming it once is what makes an ambiguous English name testable -- the
ambiguity comes from the game's own table rather than from anything invented
here.
"""

from __future__ import annotations

import json
from pathlib import Path

from bleck.formats import items
from bleck.formats.msg import ENGLISH, MSG_DIR

#: Item 0x41, `ITEM_ID_USE_HONOO_SAKURETU`: one id, one key, one name. The
#: item the manifest and CLI tests resolve by every spelling.
BLASTER_ID = 0x41
BLASTER = "Widget Blaster"

#: Item 0x00's key, `msg_unknown_item`, which 17 further ids share. Naming it
#: gives one English name that means 18 items, which is what an ambiguity
#: message is tested against.
SPARE_ID = 0x00
SPARE = "Spare Widget"

#: Item id -> the invented name the table gives it.
INVENTED = {BLASTER_ID: BLASTER, SPARE_ID: SPARE}

#: The same names as a selector spells them. Derived rather than written twice,
#: so the two spellings of one invented name cannot drift apart.
BLASTER_WRITTEN = items.normalize(BLASTER)
SPARE_WRITTEN = items.normalize(SPARE)

#: The file the pairs are written to. Any `*.txt` in the directory is read.
TABLE_NAME = "items.txt"


def message_key(item_id: int) -> str:
    """The key the committed catalog gives an item.

    Read rather than written down: a key is what the catalog ships, and a copy
    here would be a copy that goes stale the next time it is regenerated.
    """
    body = json.loads(items.ITEM_CATALOG.read_text(encoding="utf-8"))
    for row in body.get("items") or []:
        if int(row.get("id", -1)) == item_id:
            return str(row.get("msg", ""))
    raise LookupError(f"no item {item_id:#x} in {items.ITEM_CATALOG}")


def write(base: Path) -> Path:
    """Write the invented table under `base`, and return `base`.

    The format is the game's own (`docs-site/findings/msg-file-format.md`): a
    flat run of NUL-terminated strings alternating key and value, so this
    exercises the real reader rather than a stub of it.
    """
    directory = base / MSG_DIR / ENGLISH[0]
    directory.mkdir(parents=True, exist_ok=True)
    pairs = b"".join(
        f"{message_key(item_id)}\0{english}\0".encode()
        for item_id, english in INVENTED.items()
    )
    (directory / TABLE_NAME).write_bytes(pairs)
    return base
