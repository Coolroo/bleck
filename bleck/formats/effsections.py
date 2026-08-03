"""The `effdata.dat` section table, which every other `eff*` module reads through.

The file opens with sixteen `u32` section offsets and nothing else; each of the
readers — `effgeom` for display lists, `effcurve` for sampled curves, `effnode`
for the scene graph, `effdata` for the effects themselves — starts by asking
where its section begins and ends. That question has exactly one right answer,
so it lives in one place rather than being spelled out four times.

⚠️ **On disc those sixteen words are offsets; in memory they are pointers.**
The game rewrites the header in place when it loads the file, so
`header[n] == buffer + offset[n]` for all sixteen (D199, measured live). Anyone
comparing a memory dump against this reading will see sixteen numbers that
disagree completely and are the same thing.
"""

from __future__ import annotations

import struct

#: The header is sixteen u32 section offsets, then the magic at the first.
SECTIONS = 16


def section(data: bytes, index: int) -> tuple:  # pylint: disable=container-return
    """Where section `index` starts and ends, clamped to what is really there.

    ⚠️ The last section has no following offset to bound it, so the file's own
    end is the bound — reading one past the table would raise on section 15,
    which is the vertex colour array and is genuinely read.

    ⚠️ A truncated file still carries a full section table, so the table's end
    is a claim rather than a fact, and both ends are clamped to the data.
    """
    offsets = struct.unpack_from(f">{SECTIONS}I", data, 0)
    end = offsets[index + 1] if index + 1 < SECTIONS else len(data)
    return min(offsets[index], len(data)), min(end, len(data))


def count_in(data: bytes, index: int, stride: int) -> int:
    """How many `stride`-byte entries section `index` holds."""
    start, end = section(data, index)
    return max(end - start, 0) // stride
