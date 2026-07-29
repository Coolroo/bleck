"""Dump the game's item table, so an `item:` selector can name an item.

    uv run python scripts/dump_items.py --out bleck/formats/itemcatalog.json \\
        --enum-out bleck/formats/itemids.py \\
        --headers work/upstream/spm-headers/include/spm/item_data_ids.h

Two outputs, **one read of the game**: `itemcatalog.json` (every name an item
has) and `bleck/formats/itemids.py` (`ItemId`, the ids themselves). Both are
projections of the same dump, so they cannot drift from each other -- and
`tests/test_items.py` regenerates the second from the first to prove it.

`itemDataTable` holds pointers, so the names are three lookups away from the
table. Two sources give the same bytes:

- **the extracted `sys/main.dol`** (the default). The table and every string it
  points at are static `.data`, so a file read answers it -- no emulator, no
  boot, reproducible.
- **a running game** (`--boot`), the same instrument `dump_npcs.py` uses. Kept
  because it is the one that can be checked against, and because a future field
  of this table may only be true at run time.

⚠️ `itemName` is the *internal* name -- `HONOO_SAKURETU`, romaji, not English.
The English name is a second lookup: `nameMsg` is a key into `files/msg/<lang>`,
which is why this script reads those too.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ingame import Session, running_dolphins  # noqa: E402

from bleck import platforms  # noqa: E402
from bleck.backends import dol as dolfile  # noqa: E402
from bleck.backends.disc import DiscError, find_tool  # noqa: E402
from bleck.formats import itemgen  # noqa: E402
from bleck.mods import registry  # noqa: E402

#: eu0. `ItemData` is 0x2c bytes (spm-headers, item_data.h).
#: ✅ Cross-checks: the next symbol in `spm.eu0.lst` is `itemEventDataTable` at
#: 0x803FBC10, and 0x803FBC10 - 0x803F5F98 = 0x5C78 = 538 * 0x2C exactly.
ITEMS = 0x803F5F98
ITEM_COUNT = 538
STRUCT_SIZE = 0x2C

#: `ItemData`. The internal name, and the message key naming the localised one.
ITEM_NAME = 0x00
ITEM_NAME_MSG = 0x10

LOW = 0x80000000
HIGH = 0x94000000

#: Where the DOL and the messages live inside an extracted build.
DOL_PATH = "sys/main.dol"
MSG_PATH = "files/msg"

#: British English, since eu0 is the PAL build. `US` also exists.
DEFAULT_LANGUAGE = "UK"


#: ⚠️ Scoped to `enum ItemType` deliberately. `item_data_ids.h` also carries
#: `#define ITEM_ID_USE_START 65` and friends, which an unscoped match would
#: read as members and shift every id after them.
_BLOCK = re.compile(r"enum\s+ItemType\s*\{(.*?)\n\}", re.DOTALL)

#: `/* 0x041 */ ITEM_ID_USE_HONOO_SAKURETU,`. The comment is captured so it can
#: be *checked* against the position; the position is what is trusted.
_MEMBER = re.compile(
    r"^\s*(?:/\*\s*(0[xX][0-9A-Fa-f]+)\s*\*/)?\s*(ITEM_ID_[A-Za-z0-9_]+)\s*,?\s*$",
    re.MULTILINE,
)

_DECLARED_MAX = re.compile(r"^#define\s+ITEM_ID_MAX\s+(\d+)", re.MULTILINE)


def enum_names(header: Path) -> dict:  # pylint: disable=container-return
    """Item id -> `ITEM_ID_*` constant, parsed from spm-headers.

    ⚠️ Ids are **positional** -- no member carries an initialiser -- so the
    position is what counts. The `/* 0x041 */` comment beside each one is
    checked against it and a disagreement is fatal: a header that has drifted by
    one would otherwise rename every item after the drift, silently.
    """
    text = header.read_text(encoding="utf-8")
    block = _BLOCK.search(text)
    if not block:
        raise SystemExit(f"no `enum ItemType` in {header}; has it been renamed?")
    if "=" in block.group(1):
        raise SystemExit(
            f"{header}: a member of `enum ItemType` now has an initialiser, so "
            f"ids are no longer positional -- this parser would be wrong"
        )

    names = {}
    for position, (comment, name) in enumerate(_MEMBER.findall(block.group(1))):
        if comment and int(comment, 16) != position:
            raise SystemExit(
                f"{header}: {name} is member {position} (0x{position:03X}) but is "
                f"commented 0x{int(comment, 16):03X}. One of them is wrong, and "
                f"guessing which would misname every item after it."
            )
        names[position] = name

    declared = _DECLARED_MAX.search(text)
    if declared and int(declared.group(1)) != len(names):
        raise SystemExit(
            f"{header}: ITEM_ID_MAX is {declared.group(1)} but `enum ItemType` "
            f"holds {len(names)} members"
        )
    if len(names) != ITEM_COUNT:
        raise SystemExit(
            f"{header}: {len(names)} enum members, but this script reads "
            f"{ITEM_COUNT} table entries"
        )
    return names


def message_names(directory: Path) -> dict:  # pylint: disable=container-return
    """Message key -> text, from every `files/msg/<lang>/*.txt`.

    The format is a flat run of NUL-terminated strings, alternating key and
    value from byte 0 with NUL padding at the end. Earlier files win, so
    `global.txt` (read first, alphabetically) is authoritative.
    """
    table: dict[str, str] = {}
    for path in sorted(directory.glob("*.txt")):
        parts = path.read_bytes().split(b"\0")
        while parts and not parts[-1]:
            parts.pop()
        for key, value in zip(parts[0::2], parts[1::2], strict=False):
            name = key.decode("utf-8", "replace")
            if name not in table:
                table[name] = value.decode("utf-8", "replace")
    return table


class DolMemory:
    """The game's address space as the DOL has it, before it ever runs."""

    def __init__(self, path: Path) -> None:
        self.dol = dolfile.read(path)

    def word(self, address: int) -> int:
        found = self.dol.word_at(address)
        if found is None:
            raise SystemExit(
                f"{self.dol.path}: 0x{address:08X} is not in any loaded section "
                f"({self.dol.address_range}); is this the right build?"
            )
        return found

    def text(self, address: int, limit: int = 64) -> str:
        section = self.dol.section_for(address)
        if section is None:
            return ""
        at = section.file_offset(address)
        return _decode(self.dol.data[at : at + limit])


class LiveMemory:
    """The same address space, read out of a running Dolphin."""

    def __init__(self, dme) -> None:
        self.dme = dme

    def word(self, address: int) -> int:
        return self.dme.read_word(address)

    def text(self, address: int, limit: int = 64) -> str:
        if not LOW <= address < HIGH:
            return ""
        try:
            return _decode(self.dme.read_bytes(address, limit))
        except RuntimeError:
            return ""


def _decode(raw: bytes) -> str:
    end = raw.find(b"\0")
    raw = raw[: end if end >= 0 else len(raw)]
    # Internal names are ASCII, any Japanese debug text Shift-JIS. Strict first,
    # so a mangled decode never silently wins.
    for encoding in ("ascii", "shift_jis"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("ascii", "replace").strip()


def dump(memory) -> dict:  # pylint: disable=container-return
    items = [
        {
            "id": index,
            "name": memory.text(memory.word(ITEMS + index * STRUCT_SIZE + ITEM_NAME)),
            "msg": memory.text(memory.word(ITEMS + index * STRUCT_SIZE + ITEM_NAME_MSG)),
        }
        for index in range(ITEM_COUNT)
    ]
    return {"items": items}


def boot_and_read(mod: str, seconds: int) -> dict | None:  # pylint: disable=container-return
    """Boot the image and read the table out of the running game."""
    image = registry.build_root() / f"{mod}.wbfs"
    if not image.exists():
        raise SystemExit(f"no image at {image}; build one first")
    try:
        dolphin = find_tool(platforms.ToolKey.DOLPHIN)
    except DiscError as exc:
        raise SystemExit(str(exc)) from exc

    # ⚠️ The reader attaches to *a* Dolphin. An idle one already running makes
    # every read fail, which reads as "the table is not there".
    existing = running_dolphins()
    if existing:
        listed = ", ".join(str(pid) for pid in existing)
        raise SystemExit(
            f"{len(existing)} Dolphin process(es) already running ({listed}); "
            f"the memory reader would attach to the wrong one. Close them, or "
            f"drop --boot and read the table out of sys/main.dol instead."
        )

    import dolphin_memory_engine as dme

    print(f"booting {image.name} ...")
    with Session(image, dolphin) as session:
        start = time.time()
        while time.time() - start < seconds:
            time.sleep(3)
            if session.exited:
                break
            if not dme.is_hooked():
                dme.hook()
                continue
            try:
                tables = dump(LiveMemory(dme))
            except RuntimeError:
                continue
            named = sum(1 for item in tables["items"] if item["name"])
            if named:
                print(f"[t+{int(time.time() - start):>3}s] {named} named items")
                return tables
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mod", default="attended", help="a built image to boot")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument(
        "--headers",
        help="path to spm-headers/include/spm/item_data_ids.h, for ITEM_ID_* names",
    )
    parser.add_argument(
        "--enum-out",
        help="also write bleck/formats/itemids.py -- the same ITEM_ID_* names as "
        "a Python IntEnum. Needs --headers",
    )
    parser.add_argument(
        "--boot",
        action="store_true",
        help="read from a booted game rather than the extracted sys/main.dol",
    )
    parser.add_argument(
        "--dol", help=f"the DOL to read (default: <base>/{DOL_PATH})"
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help=f"which files/msg directory supplies English names "
        f"(default: {DEFAULT_LANGUAGE})",
    )
    args = parser.parse_args()

    # Checked before anything slow, and before the header is even read: the
    # member names *are* the constants, so there is nothing to write without
    # them and finding that out after a 90 s boot would be absurd.
    if args.enum_out and not args.headers:
        raise SystemExit(
            "--enum-out needs --headers: an ItemId member IS its ITEM_ID_* "
            "constant, and only item_data_ids.h carries those."
        )

    # Parsed before anything slow: a broken header should not cost a boot.
    names = enum_names(Path(args.headers)) if args.headers else {}

    if args.boot:
        tables = boot_and_read(args.mod, args.seconds)
        source = f"a running {args.mod}"
    else:
        path = Path(args.dol) if args.dol else registry.base_root() / DOL_PATH
        if not path.is_file():
            raise SystemExit(
                f"no DOL at {path}. Extract a build first, or pass --boot to "
                f"read the table out of a running game instead."
            )
        tables = dump(DolMemory(path))
        source = path.as_posix()

    if not tables or not any(item["name"] for item in tables["items"]):
        raise SystemExit("the item table never became readable")
    print(f"{len(tables['items'])} items read from {source}")

    if names:
        for item in tables["items"]:
            item["enum"] = names.get(item["id"], "")
        print(f"merged {sum(1 for i in tables['items'] if i['enum'])} ITEM_ID_* names")

    # Two projections of `names`, never two reads of the game: the JSON column
    # below and the enum here say the same thing in the two shapes that need it
    # (D119). A second dump would be a second chance to disagree.
    if args.enum_out:
        try:
            module = itemgen.render(itemgen.from_constants(names))
        except itemgen.GenerationError as exc:
            raise SystemExit(f"{args.enum_out}: {exc}") from exc
        Path(args.enum_out).write_text(module, encoding="utf-8", newline="\n")
        print(f"wrote {args.enum_out} ({len(names)} ItemId members)")

    messages = registry.base_root() / MSG_PATH / args.language
    if messages.is_dir():
        text = message_names(messages)
        for item in tables["items"]:
            item["english"] = text.get(item["msg"], "")
        found = sum(1 for i in tables["items"] if i["english"])
        print(f"merged {found} English names from {messages.as_posix()}")
    else:
        print(f"no messages at {messages}; the catalog will carry no English names")

    tables["attribution"] = (
        "Table address and field offsets from SeekyCt/spm-headers "
        "(item_data.h, item_data_ids.h), MIT licensed. Values read out of the "
        f"game ({source}); regenerate with scripts/dump_items.py."
    )
    body = json.dumps(tables, indent=1, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(body[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
