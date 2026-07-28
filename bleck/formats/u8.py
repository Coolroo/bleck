"""Nintendo U8 archive reading.

A U8 archive is a 0x20-byte header followed by a flat node table and a string
table, then file data. Each node is 12 bytes; directories store the index of the
first node *after* their subtree, so the tree is reconstructed by walking indices
rather than by nesting.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

U8_MAGIC = 0x55AA382D
NODE_SIZE = 12


class U8Error(Exception):
    pass


@dataclass(frozen=True)
class U8Entry:
    """An entry as it appears on disc, with its location in the archive."""

    path: str
    is_dir: bool
    offset: int
    size: int


@dataclass(frozen=True)
class U8Item:
    """An entry detached from any archive: a path and its contents.

    `data is None` marks a directory. `read_all` yields these and `write`
    consumes them.
    """

    path: str
    data: bytes | None

    @property
    def is_dir(self) -> bool:
        return self.data is None


@dataclass(frozen=True)
class _RawNode:
    """The 12-byte on-disc node, before its fields are interpreted."""

    kind: int
    name_offset: int
    first: int
    second: int


@dataclass(frozen=True)
class _OpenDir:
    """A directory being walked: where its subtree ends, and its path."""

    end_index: int
    path: str


def member_key(path: str) -> str:
    """A member path in a form both of SPM's archive families agree on.

    `map/*.bin` stores `./dvd/setup/x.dat`; `lyt/*.bin.uk` stores `arc/...`, so
    the leading `./` is dropped for *matching only*. ⚠️ Write back the
    archive's own spelling, or a rebuilt archive stops being byte-identical.
    """
    return path[2:] if path.startswith("./") else path


def is_u8(data: bytes) -> bool:
    return len(data) >= 4 and struct.unpack_from(">I", data)[0] == U8_MAGIC


def read(data: bytes) -> list[U8Entry]:
    """Return every entry in the archive, directories included, in node order."""
    if not is_u8(data):
        raise U8Error("not a U8 archive")

    root_off = struct.unpack_from(">I", data, 4)[0]

    # The root node's "size" field carries the total node count.
    node_count = _node(data, root_off, 0).second
    string_table = root_off + node_count * NODE_SIZE

    entries: list[U8Entry] = []
    open_dirs = [_OpenDir(node_count, "")]

    for i in range(1, node_count):
        node = _node(data, root_off, i)
        name = _string(data, string_table + node.name_offset)

        while len(open_dirs) > 1 and i >= open_dirs[-1].end_index:
            open_dirs.pop()
        parent = open_dirs[-1].path
        path = f"{parent}/{name}" if parent else name

        if node.kind == 1:
            entries.append(U8Entry(path, True, 0, 0))
            open_dirs.append(_OpenDir(node.second, path))
        else:
            entries.append(U8Entry(path, False, node.first, node.second))

    return entries


def extract(data: bytes, entry: U8Entry) -> bytes:
    if entry.is_dir:
        raise U8Error(f"{entry.path} is a directory")
    return data[entry.offset : entry.offset + entry.size]


# SPM's archives align every file to 32 bytes and leave no trailing padding.
DATA_ALIGN = 32


def _align(value: int, to: int = DATA_ALIGN) -> int:
    return (value + to - 1) // to * to


def read_all(data: bytes) -> list[U8Item]:
    """Read into the detached form `write` accepts."""
    return [U8Item(e.path, None if e.is_dir else extract(data, e)) for e in read(data)]


def write(entries: list[U8Item]) -> bytes:
    """Pack entries into a U8 archive.

    The node table is a flat depth-first listing and entry order is preserved
    as given, so a round trip must pass the order `read_all` produced.
    """
    # Node 0 is the implicit root; the caller's list supplies nodes 1..n.
    count = len(entries) + 1

    names = [""] + [item.path.rsplit("/", 1)[-1] for item in entries]
    name_offsets: list[int] = []
    string_table = bytearray()
    for name in names:
        name_offsets.append(len(string_table))
        string_table += name.encode("ascii") + b"\0"

    node_table_size = count * NODE_SIZE
    header_size = node_table_size + len(string_table)
    data_start = _align(0x20 + header_size)

    # Lay out file data, then fill in the node table now that offsets are known.
    blobs = bytearray()
    offsets: list[int] = []
    for item in entries:
        if item.data is None:
            offsets.append(0)
            continue
        pos = data_start + len(blobs)
        blobs += b"\0" * (_align(pos) - pos)
        offsets.append(data_start + len(blobs))
        blobs += item.data

    nodes = bytearray()
    nodes += struct.pack(">3I", 1 << 24, 0, count)  # root
    for i, item in enumerate(entries, start=1):
        if item.data is None:
            nodes += struct.pack(
                ">3I",
                1 << 24 | name_offsets[i],
                _parent_index(entries, item.path),
                _subtree_end(entries, item.path, i),
            )
        else:
            nodes += struct.pack(">3I", name_offsets[i], offsets[i - 1], len(item.data))

    out = bytearray(struct.pack(">4I", U8_MAGIC, 0x20, header_size, data_start))
    out += b"\0" * 16  # reserved
    out += nodes
    out += string_table
    out += b"\0" * (data_start - len(out))
    out += blobs
    return bytes(out)


def _parent_index(entries: list[U8Item], path: str) -> int:
    if "/" not in path:
        return 0
    parent = path.rsplit("/", 1)[0]
    for i, item in enumerate(entries, start=1):
        if item.path == parent:
            return i
    return 0


def _subtree_end(entries: list[U8Item], path: str, index: int) -> int:
    """Index of the first node after this directory's subtree."""
    end = index + 1
    for i, item in enumerate(entries[index:], start=index + 1):
        if not item.path.startswith(path + "/"):
            break
        end = i + 1
    return end


def _node(data: bytes, root_off: int, index: int) -> _RawNode:
    packed, first, second = struct.unpack_from(">3I", data, root_off + index * NODE_SIZE)
    return _RawNode(packed >> 24, packed & 0x00FFFFFF, first, second)


def _string(data: bytes, off: int) -> str:
    end = data.index(b"\0", off)
    return data[off:end].decode("ascii", "replace")
