#!/usr/bin/env python3
"""Recolour a CMPR TPL in the endpoint domain, without decompressing it.

A CMPR block is two RGB565 endpoints followed by 2-bit indices into the four
colours they imply. A per-pixel colour map only changes the *endpoints*, so the
indices are copied untouched — which means this never has to decode GameCube's
index packing, and never re-compresses. The result is exact, not approximate.

⚠️ **The one hazard is the `c0 > c1` flag.** DXT1 switches between a 4-colour
block and a 3-colour-plus-transparent block depending on which endpoint is
larger. A recolour that reorders them silently changes transparency, so the
original ordering is restored after mapping.

This is the prototype for the `tint` operation in
[`plan-textures.md`](../docs/plan-textures.md); when that lands, the transform
moves into `bleck` and a mod declares it instead of shipping the result.

    python scripts/tint_tpl.py <in.tpl> <out.tpl> --preset chaos
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

TPL_MAGIC = 0x0020AF30
CMPR = 14
BLOCK = 8


@dataclass(frozen=True)
class Tint:
    """A per-channel affine map, applied in 8-bit space."""

    name: str
    scale: tuple[float, float, float]  # pylint: disable=container-return
    offset: tuple[int, int, int]  # pylint: disable=container-return


#: Dark purple-black with a magenta cast — the Chaos Heart's palette. Green is
#: crushed hardest because that is what turns grey stone violet rather than blue.
PRESETS = {
    "chaos": Tint("chaos", (0.55, 0.12, 0.85), (46, 0, 60)),
    "dark": Tint("dark", (0.35, 0.35, 0.35), (0, 0, 0)),
    "invert": Tint("invert", (-1.0, -1.0, -1.0), (255, 255, 255)),
}


def _unpack565(value: int) -> tuple[int, int, int]:
    # pylint: disable=container-return
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def _pack565(r: int, g: int, b: int) -> int:
    r = max(0, min(255, r)) * 31 // 255
    g = max(0, min(255, g)) * 63 // 255
    b = max(0, min(255, b)) * 31 // 255
    return (r << 11) | (g << 5) | b


def map_endpoint(value: int, tint: Tint) -> int:
    r, g, b = _unpack565(value)
    return _pack565(
        int(r * tint.scale[0] + tint.offset[0]),
        int(g * tint.scale[1] + tint.offset[1]),
        int(b * tint.scale[2] + tint.offset[2]),
    )


def retint_cmpr(data: bytes, start: int, blocks: int, tint: Tint) -> bytearray:
    """Rewrite every block's endpoints, leaving the indices byte-identical."""
    out = bytearray(data)
    flipped = 0
    for i in range(blocks):
        at = start + i * BLOCK
        c0, c1 = struct.unpack_from(">HH", out, at)
        n0, n1 = map_endpoint(c0, tint), map_endpoint(c1, tint)
        # ⚠️ Preserve which side of the c0 > c1 test the block falls on, or a
        # 4-colour block silently becomes 3-colour-plus-transparent.
        if (c0 > c1) != (n0 > n1):
            n0, n1 = n1, n0
            flipped += 1
        struct.pack_into(">HH", out, at, n0, n1)
    if flipped:
        print(f"  {flipped} block(s) had their endpoints reordered to keep the "
              f"transparency flag")
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--preset", default="chaos", choices=sorted(PRESETS))
    args = parser.parse_args(argv)

    data = Path(args.source).read_bytes()
    if struct.unpack_from(">I", data, 0)[0] != TPL_MAGIC:
        print(f"{args.source} is not a TPL", file=sys.stderr)
        return 1

    count, table = struct.unpack_from(">II", data, 4)
    out = bytearray(data)
    touched = 0
    for i in range(count):
        head, _ = struct.unpack_from(">II", data, table + i * 8)
        height, width, fmt = struct.unpack_from(">HHI", data, head)
        offset = struct.unpack_from(">I", data, head + 8)[0]
        if fmt != CMPR:
            print(f"  image {i}: {width}x{height} format {fmt} — not CMPR, skipped")
            continue
        blocks = (width // 4) * (height // 4)
        print(f"  image {i}: {width}x{height} CMPR, {blocks} blocks")
        out = retint_cmpr(bytes(out), offset, blocks, PRESETS[args.preset])
        touched += 1

    Path(args.output).write_bytes(bytes(out))
    print(f"wrote {args.output} ({len(out):,} bytes, {touched} image(s) retinted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
