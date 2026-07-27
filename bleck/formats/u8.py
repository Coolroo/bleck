#!/usr/bin/env python3
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


@dataclass
class U8Entry:
    path: str
    is_dir: bool
    offset: int
    size: int


def is_u8(data: bytes) -> bool:
    return len(data) >= 4 and struct.unpack_from(">I", data)[0] == U8_MAGIC


def read(data: bytes) -> list[U8Entry]:
    """Return every entry in the archive, directories included, in node order."""
    if not is_u8(data):
        raise U8Error("not a U8 archive")

    root_off, header_size, data_off = struct.unpack_from(">3I", data, 4)

    # The root node's "size" field carries the total node count.
    _, _, node_count = _node(data, root_off, 0)
    string_table = root_off + node_count * NODE_SIZE

    entries: list[U8Entry] = []
    # dir_stack holds (end_index, path) so we know when a directory's subtree ends.
    dir_stack: list[tuple[int, str]] = [(node_count, "")]

    for i in range(1, node_count):
        kind, name_off, field1, field2 = _node_full(data, root_off, i)
        name = _string(data, string_table + name_off)

        while len(dir_stack) > 1 and i >= dir_stack[-1][0]:
            dir_stack.pop()
        parent = dir_stack[-1][1]
        path = f"{parent}/{name}" if parent else name

        if kind == 1:
            entries.append(U8Entry(path, True, 0, 0))
            dir_stack.append((field2, path))
        else:
            entries.append(U8Entry(path, False, field1, field2))

    return entries


def extract(data: bytes, entry: U8Entry) -> bytes:
    if entry.is_dir:
        raise U8Error(f"{entry.path} is a directory")
    return data[entry.offset : entry.offset + entry.size]


# SPM's archives align every file to 32 bytes and leave no trailing padding.
DATA_ALIGN = 32


def _align(value: int, to: int = DATA_ALIGN) -> int:
    return (value + to - 1) // to * to


def read_all(data: bytes) -> list[tuple[str, bytes | None]]:
    """Read into the (path, contents) form `write` accepts. None marks a dir."""
    return [
        (e.path, None if e.is_dir else extract(data, e)) for e in read(data)
    ]


def write(entries: list[tuple[str, bytes | None]]) -> bytes:
    """Pack entries into a U8 archive.

    Entry order is preserved exactly as given — the node table is a flat
    depth-first listing, so callers round-tripping an archive should pass the
    order `read_all` produced or the result will not match the original.
    """
    # Node 0 is the implicit root; the caller's list supplies nodes 1..n.
    count = len(entries) + 1

    names = [""] + [p.rsplit("/", 1)[-1] for p, _ in entries]
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
    for _, contents in entries:
        if contents is None:
            offsets.append(0)
            continue
        pos = data_start + len(blobs)
        pad = _align(pos) - pos
        blobs += b"\0" * pad
        offsets.append(data_start + len(blobs))
        blobs += contents

    nodes = bytearray()
    nodes += struct.pack(">3I", 1 << 24, 0, count)  # root
    for i, (path, contents) in enumerate(entries, start=1):
        if contents is None:
            parent = _parent_index(entries, path)
            nodes += struct.pack(
                ">3I", 1 << 24 | name_offsets[i], parent, _subtree_end(entries, path, i)
            )
        else:
            nodes += struct.pack(">3I", name_offsets[i], offsets[i - 1], len(contents))

    out = bytearray(struct.pack(">4I", U8_MAGIC, 0x20, header_size, data_start))
    out += b"\0" * 16  # reserved
    out += nodes
    out += string_table
    out += b"\0" * (data_start - len(out))
    out += blobs
    return bytes(out)


def _parent_index(entries: list[tuple[str, bytes | None]], path: str) -> int:
    if "/" not in path:
        return 0
    parent = path.rsplit("/", 1)[0]
    for i, (p, _) in enumerate(entries, start=1):
        if p == parent:
            return i
    return 0


def _subtree_end(entries: list[tuple[str, bytes | None]], path: str, index: int) -> int:
    """Index of the first node after this directory's subtree."""
    end = index + 1
    for i, (p, _) in enumerate(entries[index:], start=index + 1):
        if p.startswith(path + "/"):
            end = i + 1
        else:
            break
    return end


def _node(data: bytes, root_off: int, index: int) -> tuple[int, int, int]:
    kind, name_off, f1, f2 = _node_full(data, root_off, index)
    return kind, f1, f2


def _node_full(data: bytes, root_off: int, index: int) -> tuple[int, int, int, int]:
    off = root_off + index * NODE_SIZE
    raw, f1, f2 = struct.unpack_from(">3I", data, off)
    return raw >> 24, raw & 0x00FFFFFF, f1, f2


def _string(data: bytes, off: int) -> str:
    end = data.index(b"\0", off)
    return data[off:end].decode("ascii", "replace")
