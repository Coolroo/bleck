"""`texture` commands: see what is on the disc, and get it out as PNG.

Two jobs, and the second is what makes the first worth having. Nothing in this
project could *look* at a texture until now — a declared `invert` was verified
by building a 460 MB disc and booting Dolphin, 2-3 minutes per glance.

⛔ **Export is for looking, never for building.** A texture edit still goes
through the CMPR endpoint domain (D187), which is why it is lossless. If a
build ever decoded and re-encoded, every rebuild would cost a generation of
quality.

The export writes `textures.json` at the export root, and *that* is the
contract the viewer reads (`docs/plan-viewer.md`) — a filename cannot carry
which disc file an image came from, which container member, or what format it
was stored in.

The PNGs themselves go under `textures/`, mirroring the disc (see
`bleck/common/exportlayout.py`); 21,780 of them in one directory was unusable.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from bleck.cli.types import AddCommand
from bleck.common import exportlayout
from bleck.common.errors import UserError
from bleck.formats import lz77, png, texdecode, tpl, u8
from bleck.mods import registry

CATEGORY = "inspection"

#: Written at the export root. The viewer reads this, not the directory listing.
MANIFEST = "textures.json"

#: The subtree the PNGs go under, keeping them clear of the other kinds.
KIND = "textures"


@dataclass(frozen=True)
class Found:
    """One image, and the path through the disc that reaches it."""

    disc_path: str
    member: str
    """Empty when the TPL is a file rather than an archive member."""

    image: tpl.Image
    container: bytes

    @property
    def name(self) -> str:
        inside = f"/{self.member}" if self.member else ""
        return f"{self.disc_path}{inside}#{self.image.index}"

    @property
    def relative(self) -> str:
        """Where the PNG lands, relative to the export root.

        The TPL becomes a *directory*: a container holds several images, and
        what distinguishes them is the index, which is the leaf.
        """
        inside = f"{self.disc_path}/{self.member}" if self.member else self.disc_path
        return exportlayout.place(KIND, inside, f"{self.image.index}.png")


def _base() -> Path:
    base = registry.base_root()
    if not base.is_dir():
        raise UserError(
            f"no extracted base at {base}\n"
            "  run `bleck extract <disc>` first, or set BLECK_BASE_DIR"
        )
    return base


def _images_in(data: bytes, disc_path: str, member: str) -> list[Found]:
    # pylint: disable=container-return
    if not tpl.is_tpl(data):
        return []
    return [Found(disc_path, member, image, data) for image in tpl.read(data)]


def _walk(base: Path, pattern: str) -> list[Found]:  # pylint: disable=container-return
    """Every image reachable from the extracted disc, TPLs and archives alike.

    ⚠️ Archives are opened too. Most of the disc's textures live inside
    `map/*.bin` and `lyt/*.bin.uk`, so a scan that only looked at `*.tpl` would
    report a small fraction and look like it had worked.
    """
    found: list[Found] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if pattern and pattern not in relative:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue

        if tpl.is_tpl(data):
            found += _images_in(data, relative, "")
            continue

        payload = lz77.decompress(data) if lz77.is_lz77(data) else data
        if not u8.is_u8(payload):
            continue
        for item in u8.read_all(payload):
            if item.data and tpl.is_tpl(item.data):
                found += _images_in(item.data, relative, item.path)
    return found


def cmd_list(args: argparse.Namespace) -> int:
    found = _walk(_base(), args.search or "")
    if not found:
        print("no textures matched")
        return 0

    shown = found[: args.limit]
    for entry in shown:
        image = entry.image
        print(f"{entry.name:<58} {image.width:>4}x{image.height:<4} {image.format.name}")
    if len(found) > len(shown):
        print(f"... and {len(found) - len(shown)} more (raise --limit)")
    print(f"\n{len(found)} image(s)")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    out = Path(args.out)
    tree = exportlayout.Tree(out)

    found = _walk(_base(), args.search or "")
    written = 0
    failed: list[str] = []
    entries: list[dict] = []

    for entry in found:
        try:
            pixels = texdecode.decode(entry.container, entry.image)
            data = png.write(pixels.width, pixels.height, pixels.rgba)
        except tpl.TextureError as exc:
            # ⚠️ Recorded and reported, never silent. An export that quietly
            # skipped images would read as "the disc has fewer textures".
            failed.append(f"{entry.name}: {exc}")
            continue
        tree.write(entry.relative, data)
        written += 1
        entries.append(
            {
                "name": entry.name,
                "file": entry.relative,
                "format": entry.image.format.name,
                "width": entry.image.width,
                "height": entry.image.height,
                "source": entry.disc_path,
                "member": entry.member,
            }
        )

    (out / MANIFEST).write_text(
        json.dumps({"schema": 1, "textures": entries}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {written} PNG(s) under {out / KIND} and {MANIFEST} to {out}")
    if failed:
        print(f"\n{len(failed)} image(s) could not be decoded:")
        for note in failed[:10]:
            print(f"  {note}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")
    return 0


def register(add: AddCommand) -> None:
    parser = add("texture", help="look at the game's textures")
    sub = parser.add_subparsers(dest="texture_command", required=True)

    listing = sub.add_parser("list", help="every texture on the disc")
    listing.add_argument("--search", help="only paths containing this")
    listing.add_argument("--limit", type=int, default=40)
    listing.set_defaults(func=cmd_list)

    export = sub.add_parser("export", help="write textures out as PNG")
    export.add_argument("--out", default="work/export", help="where to write them")
    export.add_argument("--search", help="only paths containing this")
    export.set_defaults(func=cmd_export)
