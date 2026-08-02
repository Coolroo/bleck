"""`effect` commands: what the game's 139 effects are made of.

The third thing Dimentio shows, and the least complete of them. An effect is a
name, a list of parts, and transform rows that drive placement (D172, D173).
All of that is read; **which image a part draws is not** (see below).

The export writes `effects.json`, the same contract shape as `texture export`
and `model export`. Its images are the 219 in `files/eff/effdata.tpl`, which
`texture export` already writes out — so a viewer has the effect structure from
here and the pixels from there.

✅ **The part-to-image binding is decoded** (D258). `Part.first` is a node
index relative to the effect's base, and the image is **five sections further
on**: node → draw → subdraw → material → texture → the `effdata.tpl` index.
Every one of all 704 parts resolves, all 219 images are referenced, and none is
orphaned.

⚠️ Seven earlier candidates were refuted (D210, D218) because every one of them
was looked for in or beside the part record. The answer was never a field.

⚠️ **A part draws a set of images, not one**, so `pictures` is a list. 35 parts
draw none — their materials carry the documented `-1` — and that is a fact
about them rather than a failure to resolve.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bleck.cli.types import AddCommand
from bleck.common.errors import UserError
from bleck.formats import effdata
from bleck.mods import registry

CATEGORY = "inspection"

#: Written beside the other manifests. Dimentio reads this, not the file.
MANIFEST = "effects.json"

#: Where the effect definitions and their images live on the disc.
EFFECT_DATA = "files/eff/effdata.dat"
EFFECT_TEXTURES = "files/eff/effdata.tpl"


def _read() -> list[effdata.Effect]:  # pylint: disable=container-return
    base = registry.base_root()
    path = base / EFFECT_DATA
    if not path.is_file():
        raise UserError(
            f"no {EFFECT_DATA} under {base}\n"
            "  run `bleck extract <disc>` first, or set BLECK_BASE_DIR"
        )
    return effdata.read(path.read_bytes())


def cmd_list(args: argparse.Namespace) -> int:
    effects = _read()
    shown = [e for e in effects if not args.search or args.search in e.name]
    for effect in shown[: args.limit]:
        rows = f"{len(effect.rows):>3} row(s)" if effect.rows else "no rows"
        print(f"{effect.name:<34} {len(effect.parts):>3} part(s)  {rows}")
    if len(shown) > args.limit:
        print(f"... and {len(shown) - args.limit} more (raise --limit)")
    print(f"\n{len(shown)} effect(s) of {len(effects)}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    effects = _read()
    for effect in effects:
        if effect.name != args.name:
            continue
        print(f"{effect.name}  ({len(effect.parts)} part(s))")
        for part, composed in zip(effect.parts, effect.composed(), strict=True):
            print(
                f"  part {part.index:>4}  {composed:<32} {part.first:>4} {part.second:>4}"
            )
        for row in effect.rows[: args.limit]:
            values = "  ".join(f"{v:9.4f}" for v in row.values)
            print(f"  row  {row.index:>4}  {values}{'  unit' if row.is_unit else ''}")
        return 0
    raise UserError(f"no effect named {args.name!r}; `bleck effect list` shows them")


def _pictures(data: bytes, effect: effdata.Effect, part: effdata.Part) -> list[dict]:
    # pylint: disable=container-return
    """A part's images, as the viewer needs them.

    ⚠️ **A list, because a part draws a set.** 560 of 704 draw one image, 35
    none and the rest up to twelve, so a scalar field here would silently drop
    the artwork of the parts that need it most.
    """
    return [
        {
            "image": picture.image,
            "wrap": picture.wrap,
            "red": picture.red,
            "green": picture.green,
            "blue": picture.blue,
            "alpha": picture.alpha,
        }
        for picture in effdata.artwork(data, effect, part)
    ]


def cmd_export(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = (registry.base_root() / EFFECT_DATA).read_bytes()

    entries = [
        {
            "name": effect.name,
            "index": effect.index,
            "parts": [
                {
                    "name": part.name,
                    "composed": composed,
                    "index": part.index,
                    "frames": part.second,
                    "seconds": round(part.seconds, 4),
                    "pictures": _pictures(raw, effect, part),
                }
                for part, composed in zip(effect.parts, effect.composed(), strict=True)
            ],
            "seconds": round(max((p.seconds for p in effect.parts), default=0.0), 4),
            "rows": [
                {"index": row.index, "values": [round(v, 5) for v in row.values]}
                for row in effect.rows
            ],
        }
        for effect in _read()
    ]
    (out / MANIFEST).write_text(
        json.dumps(
            {"schema": 1, "textures": EFFECT_TEXTURES, "effects": entries}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} effect(s) to {out / MANIFEST}")
    print(f"  images come from {EFFECT_TEXTURES}, which `bleck texture export` writes")
    return 0


def register(add: AddCommand) -> None:
    parser = add("effect", help="what the game's effects are made of")
    sub = parser.add_subparsers(dest="effect_command", required=True)

    listing = sub.add_parser("list", help="every effect and its part count")
    listing.add_argument("--search", help="only names containing this")
    listing.add_argument("--limit", type=int, default=40)
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="one effect's parts and transform rows")
    show.add_argument("name")
    show.add_argument("--limit", type=int, default=12)
    show.set_defaults(func=cmd_show)

    export = sub.add_parser("export", help="write effects.json for the viewer")
    export.add_argument("--out", default="work/export", help="where to write it")
    export.set_defaults(func=cmd_export)
