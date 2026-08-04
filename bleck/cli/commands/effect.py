"""`effect` commands: what the game's 139 effects are made of.

The third thing Dimentio shows. An effect is a name, a list of parts, and
transform rows that drive placement (D172, D173) — and each part issues draws,
which are now exported with **both** the image they paint with and the geometry
they paint.

The export writes `effects.json`, the same contract shape as `texture export`
and `model export`. Its images are the 219 in `files/eff/effdata.tpl`, which
`texture export` already writes out — so a viewer has the effect structure from
here and the pixels from there.

✅ **The part-to-image binding is decoded** (D258). `Part.first` is a node
index relative to the effect's base, and the image is **five sections further
on**: node → draw → subdraw → material → texture → the `effdata.tpl` index.
Every one of all 704 parts resolves, all 219 images are referenced, and none is
orphaned.

✅ **So is the geometry** (D263, D264). The same subdraw that names the material
names a GX display list and the vertex descriptor to read it under, so a draw
carries a mesh as well as a picture. Effects are indexed triangle fans, not
billboards.

⚠️ Seven earlier candidates for the image were refuted (D210, D218) because
every one of them was looked for in or beside the part record. The answer was
never a field.

⚠️ **A part issues a set of draws, not one**, so `draws` is a list. 35 parts
reach no image — their materials carry the documented `-1`, exported as
`NO_IMAGE` — and that is a fact about them rather than a failure to resolve.

✅ **All three of the file's curve evaluators are exported** (D281). A node's
transform was the only one until now; a material's colour register and a
texture's UV transform are the other two, and they arrive as the shared
`materials` and `samplers` tables — 97 and 103 of which carry a curve run,
naming the same `curves` array the nodes do.

⚠️ **A frozen tail reads as a finished animation.** 32 effects hold a
byte-identical pose across 1,523 frames while their colour or UV data moves
(D278), so an export that drops the other two evaluators renders those frames
as a still and nothing reports it.

✅ **Blend mode 0 is a request to derive a mode, and its inputs are exported**
(D283) — a sampler's `alpha_type` and a draw's `translucent`. ⛔ **The mode
itself is not**: the derivation reads the evaluated colour alpha, so a resolved
mode is wrong for 341 draws the moment an instance fades.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bleck.cli.types import AddCommand
from bleck.common.errors import UserError
from bleck.formats import effcurve, effdata, effgeom, effnode, effpaint
from bleck.mods import registry

CATEGORY = "inspection"

#: Written beside the other manifests. Dimentio reads this, not the file.
MANIFEST = "effects.json"

#: Bumped to 5 when the manifest gained the two inputs blend mode 0's derivation
#: reads — a sampler's `alpha_type` and a draw's `translucent` (D283).
#: 4 added the `materials` and `samplers` tables, the other two evaluators the
#: file drives from the same `curves` table (D281); 3 added `nodes` and `curves`
#: so a viewer could pose an effect at an arbitrary time (D266); 2 added `draws`
#: and `meshes` (D263); 1 was the original.
SCHEMA = 5

#: A draw whose material names no texture. ⚠️ Not 0, which is a real image.
NO_IMAGE = -1

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
        print(f"{effect.name:<34} {len(effect.parts):>3} part(s)")
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
        return 0
    raise UserError(f"no effect named {args.name!r}; `bleck effect list` shows them")


#: Descriptor bits, so the export can leave out an array the geometry never
#: names rather than writing a column of defaults for every vertex.
HAS_NORMAL, HAS_COLOUR, HAS_TEXCOORD = 1 << 1, 1 << 2, 1 << 3


def _mesh(mesh: effgeom.Mesh) -> dict:  # pylint: disable=container-return
    """One display list, as indexed triangles the viewer can draw directly.

    Positions and texture coordinates are written **as the file stores them** —
    raw `s16` units and unscaled floats. ⚠️ What one position unit is in the
    game's world is not established, so converting here would be inventing a
    scale and burying it where nobody would look for it.

    ⚠️ **Vertices are shared, not repeated per triangle.** Fans overlap heavily
    — every quad of Dimentio's star carries the same centre — and writing three
    fresh vertices per triangle made this manifest three times the size for the
    same geometry.

    An array the descriptor does not name is left out entirely rather than
    filled with defaults, which is most of the file: 2,494 of the 2,960 draws
    carry position and texture coordinate alone.
    """
    order: dict = {}
    vertices: list[effgeom.Vertex] = []
    triangles: list[int] = []
    for triangle in mesh.triangles():
        for vertex in (triangle.a, triangle.b, triangle.c):
            at = order.get(vertex)
            if at is None:
                at = order[vertex] = len(vertices)
                vertices.append(vertex)
            triangles.append(at)

    written = {
        "offset": mesh.offset,
        "descriptor": mesh.descriptor,
        "positions": [c for v in vertices for c in (v.x, v.y, v.z)],
        "triangles": triangles,
    }
    if mesh.descriptor & HAS_TEXCOORD:
        written["uvs"] = [round(c, 6) for v in vertices for c in (v.u, v.v)]
    if mesh.descriptor & HAS_COLOUR:
        written["colours"] = [
            c for v in vertices for c in (v.red, v.green, v.blue, v.alpha)
        ]
    if mesh.descriptor & HAS_NORMAL:
        written["normals"] = [round(c, 5) for v in vertices for c in (v.nx, v.ny, v.nz)]
    return written


def _draws(
    data: bytes, effect: effdata.Effect, part: effdata.Part, index: dict
) -> list[dict]:
    # pylint: disable=container-return
    """A part's draws: what it paints with, and the geometry it paints.

    ⚠️ **A list, because a part issues a set of draws.** 560 of 704 resolve to
    one image, 35 to none and the rest to as many as twelve, so a scalar field
    here would silently drop the artwork of the parts that need it most.

    ⚠️ **Not deduplicated by image.** Two draws sharing a material and differing
    in geometry are two draws; collapsing them would lose half the shape.

    ⛔ **`blend` 0 is exported unresolved, and `translucent` is why** (D283). The
    derivation reads the *evaluated* colour alpha, which the runtime fade moves,
    so a mode baked here is wrong for 341 draws the moment anything fades. The
    inputs travel instead: this bit, and the sampler's `alpha_type`.
    """
    written = []
    for draw in effdata.draws(data, effect, part):
        picture = draw.picture
        written.append(
            {
                "mesh": index[(draw.offset, draw.descriptor)],
                "chain": list(draw.chain),
                "blend": draw.blend,
                "translucent": draw.translucent,
                "image": picture.image if picture else NO_IMAGE,
                "wrap": picture.wrap if picture else 0,
                "red": picture.red if picture else 255,
                "green": picture.green if picture else 255,
                "blue": picture.blue if picture else 255,
                "alpha": picture.alpha if picture else 255,
                # ⚠️ The static fields above stay: they are what an older
                # reader uses, and dropping them would make this export render
                # every draw white in one.
                "material": draw.material,
                "sampler": picture.sampler if picture else effdata.NO_RECORD,
            }
        )
    return written


class _Curves:
    """The shared `curves` table, and the dedup that keeps it one table.

    ⚠️ **Deduplicated by section 2 offset, across all three consumers.** Nodes,
    materials and textures name the same command table and several of them land
    on the same curve record; writing one array per reference would inflate the
    manifest for no extra information.
    """

    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.every = effnode.commands(raw)
        self.written: list[dict] = []
        self._order: dict = {}

    def slot(self, offset: int) -> int:
        """Where this curve's samples sit in the shared table, writing it first
        if nothing has named it yet."""
        at = self._order.get(offset)
        if at is not None:
            return at
        curve = effcurve.curve_at(self.raw, offset)
        at = self._order[offset] = len(self.written)
        self.written.append(
            {
                "length": curve.length,
                "start": curve.start,
                "end": curve.end,
                "loop": curve.loop,
                "bytes": curve.byte_samples,
                "samples": [round(v, 5) for v in curve.samples],
            }
        )
        return at

    def driven(self, run: effpaint.Run, slots: int) -> list:
        # pylint: disable=container-return
        """A record's curve run as `[tag, curve]` pairs.

        ⚠️ A tag outside the record's own slot array is dropped rather than
        exported: the reader has no slot to put it in, and a viewer inventing
        one would drive a scalar the game never touches.
        """
        return [
            [command.tag, self.slot(command.offset)]
            for command in effpaint.run_of(run, self.every)
            if 0 <= command.tag < slots
        ]


def _scene(raw: bytes, curves: _Curves) -> dict:  # pylint: disable=container-return
    """The node tree, the materials and the samplers, as three shared tables.

    ⚠️ **The viewer poses, rather than being handed a pose.** An effect's
    transform is a function of time — 44% of drawing nodes are flat at rest and
    26 effects vanish entirely (D265) — so shipping one frame's matrices would
    ship the one frame that does not work. The tables are what the game itself
    reads.

    ⚠️ **All three tables reference the same `curves`.** The file drives a
    node's transform, a material's colour register and a texture's UV transform
    from one command table, and 305 of its 4,752 commands belong to the second
    and third (D278, D281).
    """
    nodes: list[dict] = []
    for index in range(effnode.node_count(raw)):
        node = effnode.node_at(raw, index)
        nodes.append(
            {
                "t": [round(v, 5) for v in effnode.vector_at(raw, node.translate)],
                "r": [round(v, 5) for v in effnode.vector_at(raw, node.rotate)],
                "s": [round(v, 5) for v in effnode.vector_at(raw, node.scale)],
                "alpha": node.alpha,
                "curves": curves.driven(
                    effpaint.Run(node.curves, node.count), effnode.SLOTS
                ),
            }
        )
    return {
        "nodes": nodes,
        "materials": _materials(raw, curves),
        "samplers": _samplers(raw, curves),
    }


def _materials(raw: bytes, curves: _Curves) -> list[dict]:
    # pylint: disable=container-return
    """Section 5: every colour register, and the curves that drive its channels.

    ⚠️ **Written whole, not per draw.** 2,960 draws share 524 materials, and 97
    of those carry a curve run — inlining the run on each draw would repeat the
    same reference five times over.
    """
    return [
        {
            "rgba": [
                material.colour.red,
                material.colour.green,
                material.colour.blue,
                material.colour.alpha,
            ],
            "curves": curves.driven(material.run, len(effpaint.MATERIAL_SLOT_NAMES)),
        }
        for material in effpaint.materials(raw)
    ]


def _samplers(raw: bytes, curves: _Curves) -> list[dict]:
    # pylint: disable=container-return
    """Section 4: the whole 28-byte texture record, decoded.

    ⚠️ **`wrap_s` and `wrap_t` are decoded here, not left as the raw byte.** How
    the two bits per axis fold is a fact about the file — mirror wins over the
    repeat bit — and the reading belongs where the format is owned rather than
    in every consumer.

    ⚠️ **`alpha_type` is decoded the same way, and is not a blend mode.** It is
    one of three inputs the game folds together (D283); the raw `flags` stays
    beside it because the other six bits are still unread.
    """
    return [
        {
            "image": sampler.image,
            "wrap": sampler.wrap,
            "wrap_s": sampler.wrap_s,
            "wrap_t": sampler.wrap_t,
            "flags": sampler.flags,
            "alpha_type": sampler.alpha_type,
            "translate": [
                round(sampler.uv.translate_u, 6),
                round(sampler.uv.translate_v, 6),
            ],
            "scale": [round(sampler.uv.scale_u, 6), round(sampler.uv.scale_v, 6)],
            "rotation": round(sampler.uv.rotation, 5),
            "curves": curves.driven(sampler.run, len(effpaint.SAMPLER_SLOT_NAMES)),
        }
        for sampler in effpaint.samplers(raw)
    ]


def cmd_export(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = (registry.base_root() / EFFECT_DATA).read_bytes()

    # 2,960 draws share 360 display lists, so the geometry is written once at
    # the top level and referred to by index. Inlining it per draw would be
    # eight copies of every mesh.
    shared = effdata.meshes(raw)
    index = {(mesh.offset, mesh.descriptor): at for at, mesh in enumerate(shared)}
    curves = _Curves(raw)
    scene = _scene(raw, curves)

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
                    "draws": _draws(raw, effect, part, index),
                }
                for part, composed in zip(effect.parts, effect.composed(), strict=True)
            ],
            "seconds": round(max((p.seconds for p in effect.parts), default=0.0), 4),
        }
        for effect in _read()
    ]
    (out / MANIFEST).write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "textures": EFFECT_TEXTURES,
                "meshes": [_mesh(mesh) for mesh in shared],
                **scene,
                "curves": curves.written,
                "effects": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    faces = sum(len(mesh.triangles()) for mesh in shared)
    print(f"wrote {len(entries)} effect(s) to {out / MANIFEST}")
    print(f"  {len(shared)} display list(s), {faces} triangle(s)")
    print(
        f"  {len(scene['nodes'])} node(s), {len(scene['materials'])} material(s), "
        f"{len(scene['samplers'])} sampler(s) - the viewer poses from these"
    )
    print(f"  {len(curves.written)} curve(s), shared by all three")
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
