"""Tile an effect's own images at a readable size, for eyeballing against a wiki.

`dimentio reel` answers "which images, and when". It is poor at "what does the
art look like": the quads are small in the frame and the bank is full of 16x32
sprites. This reads the exported PNGs at native resolution, scales each up by a
whole number, and lays them out side by side on a mid-grey field.

⚠️ Nearest-neighbour, whole-number scaling only. Smoothing would invent detail
in a 16x32 sprite, and the whole point is to look at what is actually there.
"""

from __future__ import annotations

import argparse
import json
import sys
import zlib
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bleck.formats import png  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "work" / "export"
DEFAULT_CELL = 160
PAD = 6
BACK = (58, 60, 66, 255)


def read_png(path: Path):
    data = path.read_bytes()
    at, idat = 8, b""
    width = height = depth = colour = 0
    while at < len(data):
        size = struct.unpack(">I", data[at : at + 4])[0]
        kind = data[at + 4 : at + 8]
        body = data[at + 8 : at + 8 + size]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        at += 12 + size
    raw = zlib.decompress(idat)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    stride = channels * depth // 8
    out, prev, k = [], bytearray(width * stride), 0
    for _ in range(height):
        filt, k = raw[k], k + 1
        line = bytearray(raw[k : k + width * stride])
        k += width * stride
        for x in range(len(line)):
            a = line[x - stride] if x >= stride else 0
            b = prev[x]
            c = prev[x - stride] if x >= stride else 0
            if filt == 1:
                line[x] = (line[x] + a) & 255
            elif filt == 2:
                line[x] = (line[x] + b) & 255
            elif filt == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif filt == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        out.append(bytes(line))
        prev = line
    return width, height, channels, b"".join(out)


def images_of(effect: str) -> list:
    manifest = json.loads((ROOT / "effects.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["effects"] if e["name"] == effect)
    seen, order = set(), []
    for part in entry["parts"]:
        # ⚠️ A draw with no texture carries -1, not 0 — and 0 is a real image.
        for draw in part["draws"]:
            if draw["image"] >= 0 and draw["image"] not in seen:
                seen.add(draw["image"])
                order.append(draw["image"])
    return order


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("effect", help="as `bleck effect list` names it")
    ap.add_argument("out", type=Path, help="where to write the PNG")
    ap.add_argument(
        "--cell",
        type=int,
        default=DEFAULT_CELL,
        help=f"edge of one tile, in pixels (default {DEFAULT_CELL})",
    )
    args = ap.parse_args()
    effect, out, cell = args.effect, args.out, max(16, args.cell)
    picked = images_of(effect)
    if not picked:
        print(f"{effect} draws no images")
        return 1

    tiles = []
    for index in picked:
        path = ROOT / "textures" / "files" / "eff" / "effdata.tpl" / f"{index}.png"
        width, height, channels, pixels = read_png(path)
        tiles.append((index, width, height, channels, pixels))

    columns = min(len(tiles), 6)
    rows = (len(tiles) + columns - 1) // columns
    sheet_w = columns * cell + (columns + 1) * PAD
    sheet_h = rows * cell + (rows + 1) * PAD
    canvas = bytearray(bytes(BACK) * (sheet_w * sheet_h))

    for slot, (index, width, height, channels, pixels) in enumerate(tiles):
        # ⚠️ Both directions. The bank runs from 16x32 sprites to 192x192
        # sheets, and an integer upscale alone leaves the big ones larger than
        # the cell — which silently *grew* the canvas, because bytearray slice
        # assignment past the end appends rather than raising.
        if width <= cell and height <= cell:
            scale = max(1, min(cell // max(width, 1), cell // max(height, 1)))
            drawn_w, drawn_h = width * scale, height * scale
        else:
            shrink = max(width, height) / cell
            drawn_w = max(1, int(width / shrink))
            drawn_h = max(1, int(height / shrink))
        left = PAD + (slot % columns) * (cell + PAD) + (cell - drawn_w) // 2
        top = PAD + (slot // columns) * (cell + PAD) + (cell - drawn_h) // 2
        for y in range(drawn_h):
            sy = min(y * height // drawn_h, height - 1)
            for x in range(drawn_w):
                sx = min(x * width // drawn_w, width - 1)
                at = (sy * width + sx) * channels
                if channels == 4:
                    r, g, b, a = pixels[at : at + 4]
                elif channels == 3:
                    r, g, b = pixels[at : at + 3]
                    a = 255
                else:
                    r = g = b = pixels[at]
                    a = pixels[at + 1] if channels == 2 else 255
                # Composited over a checker so transparency is visible as
                # transparency rather than as black.
                back = 96 if ((x // 8) + (y // 8)) % 2 else 72
                blend = lambda c: (c * a + back * (255 - a)) // 255  # noqa: E731
                o = ((top + y) * sheet_w + (left + x)) * 4
                canvas[o : o + 4] = bytes((blend(r), blend(g), blend(b), 255))

    out.write_bytes(png.write(sheet_w, sheet_h, bytes(canvas)))
    sizes = ", ".join(f"{i}({w}x{h})" for i, w, h, _, _ in tiles)
    print(f"{effect}: {len(tiles)} image(s) -> {sizes}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
