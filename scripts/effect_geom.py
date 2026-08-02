"""Rasterise one effect display list straight from effdata.dat, to confirm D263.

⚠️ **Deliberately not `dimentio`.** This shares no code with the viewer — it
reads the disc file, walks the display list, samples the exported PNG and fills
triangles itself. If the star appears here it is because the *format reading* is
right, not because two halves of one program agree with each other.

Orthographic, straight down -Z. Effect geometry is flat (Z is 0 throughout the
star), so there is nothing a perspective camera would add except a way to be
wrong.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bleck.formats import png  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DAT = REPO / "work" / "extracted" / "eu0" / "files" / "eff" / "effdata.dat"
TEX = REPO / "work" / "export" / "textures" / "files" / "eff" / "effdata.tpl"

SIZE = 520
SPAN = 420.0
BACK = (26, 28, 34)
PRIMS = (0x80, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8)


def read_png(path: Path):
    data = path.read_bytes()
    at, idat, w, h, depth, colour = 8, b"", 0, 0, 0, 0
    while at < len(data):
        n = struct.unpack(">I", data[at : at + 4])[0]
        kind = data[at + 4 : at + 8]
        if kind == b"IHDR":
            w, h, depth, colour = struct.unpack(">IIBB", data[at + 8 : at + 18])
        elif kind == b"IDAT":
            idat += data[at + 8 : at + 8 + n]
        at += 12 + n
    raw = zlib.decompress(idat)
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    bpp = ch * depth // 8
    out, prev, k = [], bytearray(w * bpp), 0
    for _ in range(h):
        f, k = raw[k], k + 1
        line = bytearray(raw[k : k + w * bpp])
        k += w * bpp
        for x in range(len(line)):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        out.append(bytes(line))
        prev = line
    return w, h, ch, b"".join(out)


def sample(tex, u, v):
    w, h, ch, px = tex
    # ⚠️ Clamped, not wrapped. The star's UVs sit inside 0..1, so wrapping would
    # never fire — and guessing a wrap mode here would be inventing one.
    x = min(w - 1, max(0, int(u * w)))
    y = min(h - 1, max(0, int(v * h)))
    at = (y * w + x) * ch
    if ch == 4:
        return px[at], px[at + 1], px[at + 2], px[at + 3]
    if ch == 3:
        return px[at], px[at + 1], px[at + 2], 255
    return (px[at],) * 3 + (px[at + 1] if ch == 2 else 255,)


def primitives(raw, offs, dl, descriptor):
    """Every primitive in one display list, as (position index, uv index) pairs."""
    stride = 2 * bin(descriptor & 0x7FFF).count("1")
    base = offs[3] + dl
    size = struct.unpack_from(">I", raw, base)[0]
    at, end, found = base + 32, base + 32 + size, []
    while at < end:
        op = raw[at]
        if op == 0 or op & 0xF8 not in PRIMS:
            break
        n = struct.unpack_from(">H", raw, at + 1)[0]
        verts = []
        for i in range(n):
            row = struct.unpack_from(f">{stride // 2}H", raw, at + 3 + i * stride)
            verts.append((row[0], row[-1]))
        found.append(verts)
        at += 3 + n * stride
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--dl", type=lambda s: int(s, 0), default=0x001C80,
                    help="display-list offset into section 3")
    ap.add_argument("--descriptor", type=lambda s: int(s, 0), default=0x0009,
                    help="GX vertex descriptor from the section 8 entry")
    ap.add_argument("--image", type=int, default=13, help="effdata.tpl image index")
    args = ap.parse_args()
    dl_offset, descriptor, image = args.dl, args.descriptor, args.image
    raw = DAT.read_bytes()
    offs = list(struct.unpack_from(">16I", raw, 0)) + [len(raw)]
    tex = read_png(TEX / f"{image}.png")

    def pos(i):
        return struct.unpack_from(">3h", raw, offs[13] + i * 6)

    def uv(i):
        return struct.unpack_from(">2f", raw, offs[11] + i * 8)

    canvas = bytearray(bytes(BACK + (255,)) * (SIZE * SIZE))

    def to_screen(p):
        return (p[0] / SPAN * SIZE / 2 + SIZE / 2, -p[1] / SPAN * SIZE / 2 + SIZE / 2)

    def triangle(a, b, c):
        """One textured triangle, alpha-composited. (screen xy, uv) per corner."""
        xs = [v[0][0] for v in (a, b, c)]
        ys = [v[0][1] for v in (a, b, c)]
        area = (b[0][0] - a[0][0]) * (c[0][1] - a[0][1]) - (c[0][0] - a[0][0]) * (
            b[0][1] - a[0][1]
        )
        if abs(area) < 1e-9:
            return
        for y in range(max(0, int(min(ys))), min(SIZE, int(max(ys)) + 2)):
            for x in range(max(0, int(min(xs))), min(SIZE, int(max(xs)) + 2)):
                px, py = x + 0.5, y + 0.5
                w0 = ((b[0][0] - a[0][0]) * (py - a[0][1]) - (px - a[0][0]) * (b[0][1] - a[0][1])) / area
                w1 = ((px - a[0][0]) * (c[0][1] - a[0][1]) - (c[0][0] - a[0][0]) * (py - a[0][1])) / area
                w2 = 1.0 - w0 - w1
                if w0 < 0 or w1 < 0 or w2 < 0:
                    continue
                u = w2 * a[1][0] + w1 * b[1][0] + w0 * c[1][0]
                v = w2 * a[1][1] + w1 * b[1][1] + w0 * c[1][1]
                r, g, bl, al = sample(tex, u, v)
                if not al:
                    continue
                at = (y * SIZE + x) * 4
                for k, src in enumerate((r, g, bl)):
                    canvas[at + k] = (src * al + canvas[at + k] * (255 - al)) // 255

    drawn = 0
    for verts in primitives(raw, offs, dl_offset, descriptor):
        corners = [(to_screen(pos(p)), uv(t)) for p, t in verts]
        for i in range(1, len(corners) - 1):
            triangle(corners[0], corners[i], corners[i + 1])
        drawn += 1

    out = args.out
    out.write_bytes(png.write(SIZE, SIZE, bytes(canvas)))
    print(f"display list 0x{dl_offset:06X}: {drawn} primitive(s) from image {image}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
