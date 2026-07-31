"""`model` commands: see what geometry is on the disc, and get it out.

The counterpart to `texture export`, and it exists for the same reason — until
a mesh can be looked at, every claim about it is a claim about a hex dump.

⛔ **Export is for looking, never for building.** Nothing reads an OBJ back in.
A model edit, when it arrives, will be declared as data against the user's own
disc like every other edit (see `vision.md`), not shipped as baked geometry.

The export writes `models.json` at the export root, and *that* is the contract
Dimentio reads. A filename cannot say which shape inside a file it came from,
how many faces it had, or what it measures.

The `.glb` files go under `models/`, mirroring the disc — see
`bleck/common/exportlayout.py` for why every kind gets its own subtree.

✅ **What this exports is the whole model.** Median coverage across the disc is
100% and the mean 99.8%, and every shape in a file comes out as its own
primitive (D224, D240). Every command here still prints the coverage, and the
manifest carries it — it is the number that would fall if the per-shape bases
stopped being read, so it stays in front of the user.

⛔ D211 described this as a fragment at 13.6% coverage and is superseded.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from bleck.cli.types import AddCommand
from bleck.common import exportlayout
from bleck.common.errors import UserError
from bleck.formats import gltf, model, png, texdecode, tpl
from bleck.mods import registry

CATEGORY = "inspection"

#: Written at the export root. Dimentio reads this, not the directory listing.
MANIFEST = "models.json"

#: The subtree the `.glb` files go under, keeping them clear of the other kinds.
KIND = "models"

#: Where character models live on the disc.
MODEL_DIR = "files/a"

#: Coverage at or above which a model is treated as whole rather than a
#: fragment. ⚠️ **The manifest's `fragment` flag used to be a hardcoded `True`**,
#: which made it useless to filter on — a viewer honouring it hid everything.
#: 132 of 864 models clear this bar (D211).
WHOLE = 0.95


#: The game's video rate, which is what a clip's key times are counted in.
#: 🔶 The times decode as whole numbers running to 280 for a Mario clip, and
#: `effdata` already converts effect frames at 60 (D219) -- so this is the same
#: inference, not a separate measurement. glTF's sampler input is defined as
#: seconds, so writing raw frame numbers there would play a 4.7-second clip
#: over 280 seconds in every viewer.
FRAME_RATE = 60.0


@dataclass(frozen=True)
class ClipInfo:
    """One animation clip of a file, decoded both ways it can be read.

    `curves` is the track data (D216) and `poses` the per-vertex morphs (D217).
    The manifest reports both; only `poses` can be written into a `.glb`.
    """

    name: str
    curves: list = field(default_factory=list)  # pylint: disable=container-return
    poses: list = field(default_factory=list)  # pylint: disable=container-return

    @property
    def frames(self) -> float:
        """The clip's last key, on the timeline the file counts in."""
        return max((pose.time for pose in self.poses), default=0.0)

    @property
    def seconds(self) -> float:
        return self.frames / FRAME_RATE

    def as_gltf(self) -> gltf.Clip:
        """The same clip with its key times in seconds, which glTF requires."""
        return gltf.Clip(
            name=self.name,
            poses=[replace(pose, time=pose.time / FRAME_RATE) for pose in self.poses],
        )


@dataclass(frozen=True)
class Found:
    """One model file, and the mesh read out of it."""

    disc_path: str
    mesh: model.Mesh
    clips: list = field(default_factory=list)  # pylint: disable=container-return

    @property
    def name(self) -> str:
        return Path(self.disc_path).name

    @property
    def relative(self) -> str:
        """Where the `.glb` lands, relative to the export root.

        One file in, one file out, so it sits in the directory the disc file
        sits in rather than in a directory named after it.
        """
        directory = PurePosixPath(self.disc_path).parent.as_posix()
        return exportlayout.place(KIND, directory, f"{self.name}.glb")


def _base() -> Path:
    base = registry.base_root()
    if not base.is_dir():
        raise UserError(
            f"no extracted base at {base}\n"
            "  run `bleck extract <disc>` first, or set BLECK_BASE_DIR"
        )
    return base


def _walk(base: Path, pattern: str) -> list[Found]:  # pylint: disable=container-return
    """Every model whose geometry this reading covers.

    ⚠️ A file that `mesh` refuses is skipped rather than guessed at. Six on the
    disc fail the normal check and would otherwise export as plausible noise.
    """
    found: list[Found] = []
    directory = base / MODEL_DIR
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if pattern and pattern not in relative:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not model.is_model(data):
            continue
        try:
            mesh = model.mesh(data)
        except model.ModelError:
            continue
        if mesh.is_drawable:
            found.append(Found(relative, mesh, _clips_of(data, mesh)))
    return found


def _clips_of(data: bytes, mesh: model.Mesh) -> list:  # pylint: disable=container-return
    """A file's animation clips, with their curves and their poses decoded.

    ⚠️ An unreadable header costs the clips, never the geometry -- `read` is
    stricter than `mesh` and refuses files whose bounding box does not check
    out, which is no reason to drop a model that renders.

    ⚠️ A pose reaching past the mesh's own positions is dropped here rather
    than at write time, so the count the manifest reports is the count that
    could be written.
    """
    try:
        found = model.read(data)
    except model.ModelError:
        return []
    reach = len(mesh.positions)
    clips = []
    for clip in found.animations:
        poses = model.morphs(data, clip)
        clips.append(
            ClipInfo(
                name=clip.name,
                curves=model.curves(data, clip),
                poses=[p for p in poses if p.offsets and p.reach < reach],
            )
        )
    return clips


@dataclass(frozen=True)
class Budget:
    """What one file's morph data may weigh, both ways it can be capped.

    ⚠️ **Two caps, and whichever is smaller wins.** `targets` binds on a small
    mesh with hundreds of poses; `size` binds on a large one. A single cap of
    either shape is wrong, because the cost per target varies 25-fold across
    the disc.
    """

    targets: int
    size: int


#: The default caps, priced against `gltf.costs` rather than a vertex count.
#:
#: ⚠️ **Measured across all 864 models, not picked round** (D238). Keeping
#: every clip on the disc needs **10.65 MB** on the worst file (`p_luigi`,
#: 1,466 poses) and **1,466** targets; 11 MiB already drops none, and 12 MiB
#: leaves room for the cost model's 3.4% worst-case error. **All 3,079 clips
#: are written**, for 102 MB of morph data across the export against the old
#: 55 MB for 2,279.
#:
#: ⚠️ The target cap binds on nothing this disc holds. It is a guard against a
#: file whose clips are individually cheap and collectively unbounded, and the
#: byte cap is what actually decides every real model.
SPARSE = Budget(targets=2048, size=12 * 1024 * 1024)

#: ...and the caps `--dense-morphs` restores, exactly as D235 measured them. A
#: dense target costs `vertices * 12`, so 256 alone would give `e_3D_manera2`
#: -- 3,811 welded vertices -- an 11 MB animation block on a 130 KB mesh.
DENSE = Budget(targets=256, size=2 * 1024 * 1024)


@dataclass(frozen=True)
class Animations:
    """The clips one file's budget allowed, and what was left out.

    ⚠️ `dropped` is reported, never swallowed. A model that silently exported
    3 of its 94 clips reads as a model with 3 animations.
    """

    clips: list = field(default_factory=list)  # pylint: disable=container-return
    dropped: int = 0
    targets: int = 0

    def wrote(self, clip: ClipInfo) -> bool:
        """Whether this exact clip is one of the ones written.

        ⚠️ Identity, not the name. Clip names inside one file are not unique,
        and a by-name test would mark a dropped clip as written.
        """
        return any(kept is clip for kept in self.clips)


def fit_animations(mesh, clips: list, dense: bool = False) -> Animations:
    """Every clip that moves something and fits, in the file's own order.

    ⚠️ **Greedy, in file order, skipping what does not fit.** A clip too big
    for what is left does not end the walk — a 245-pose clip in the middle of a
    file must not cost every shorter clip behind it.

    ⚠️ **The cost of adding a clip rises as the file fills**, because every
    keyframe already written gains a weight for each new target. So the walk
    prices each clip against the total it would produce, not against itself.
    """
    cap = DENSE if dense else SPARSE
    usable = [clip for clip in clips if clip.poses]
    priced = gltf.costs(mesh, usable, sparse=not dense)
    kept: list = []
    spent = 0
    targets = 0
    for clip, cost in zip(usable, priced, strict=True):
        total = targets + cost.poses
        grew = spent + cost.body + gltf.weight_cost(total) - gltf.weight_cost(targets)
        if grew <= cap.size and total <= cap.targets:
            spent = grew
            targets = total
            kept.append(clip)
    return Animations(clips=kept, dropped=len(usable) - len(kept), targets=targets)


def textures_for(base: Path, disc_path: str, mesh: model.Mesh) -> list:
    # pylint: disable=container-return
    """The bank images this model's shapes actually name, as PNG.

    ✅ **Each shape's own image, read from the file** (D243). A shape's record
    lists the texture layers it draws with, each layer resolves through slot 17
    to a material record, and the material's index is the image's place in the
    bank beside the model.

    ⛔ D229 shipped image 0 for single-shape models and nothing at all for the
    other 761, because the binding was not decoded and painting image 0 across
    a whole model drew the sprite sheet onto every limb. That is superseded:
    the binding is now read, and `--guess-textures` is gone with it.

    ⚠️ Only the images some shape reaches are decoded. A bank may carry images
    nothing references, and embedding those would grow every `.glb` for
    nothing.
    """
    wanted = sorted({index for span in mesh.shape_spans() for index in span.textures})
    if not wanted:
        return []
    source = base / disc_path
    try:
        bank = model.bank_for(source, source.read_bytes())
    except OSError:
        return []
    if not bank.is_file():
        return []
    try:
        raw = bank.read_bytes()
        images = tpl.read(raw) if tpl.is_tpl(raw) else []
    except (tpl.TextureError, OSError, ValueError):
        # ⚠️ An undecodable bank costs a texture, never the geometry.
        return []
    found = []
    for index in wanted:
        at = mesh.materials[index].index if index < len(mesh.materials) else index
        if at >= len(images):
            continue
        try:
            pixels = texdecode.decode(raw, images[at])
        except (tpl.TextureError, ValueError):
            continue
        found.append(
            gltf.Paint(
                index=index, png=png.write(pixels.width, pixels.height, pixels.rgba)
            )
        )
    return found


def _extent(mesh: model.Mesh) -> tuple:  # pylint: disable=container-return
    lowest = [min(p[i] for p in mesh.positions) for i in range(3)]
    highest = [max(p[i] for p in mesh.positions) for i in range(3)]
    return lowest, highest


def cmd_list(args: argparse.Namespace) -> int:
    found = _walk(_base(), args.search or "")
    if not found:
        print("no models matched")
        return 0

    shown = found[: args.limit]
    for entry in shown:
        mesh = entry.mesh
        print(
            f"{entry.name:<24} {mesh.name[:26]:<28} "
            f"{len(mesh.positions):>6} verts {len(mesh.faces):>5} faces "
            f"{mesh.coverage * 100:>5.1f}% covered"
        )
    if len(found) > len(shown):
        print(f"... and {len(found) - len(shown)} more (raise --limit)")
    print(f"\n{len(found)} model(s)")
    _warn_about_coverage(found)
    return 0


def _warn_about_coverage(found: list[Found]) -> None:
    """⚠️ Printed every time, never once. A number this bad has to stay in
    front of whoever is looking at the output."""
    if not found:
        return
    ranked = sorted(entry.mesh.coverage for entry in found)
    median = ranked[len(ranked) // 2]
    low = sum(1 for value in ranked if value < 0.95)
    if not low:
        print(f"\n  all {len(ranked)} reach 95%+ of their vertices")
        return
    print(
        f"\n! {low} of {len(ranked)} are fragments -- median coverage "
        f"{median * 100:.1f}% of each\n"
        f"  file's vertices, and a fragment renders as stretched geometry.\n"
        f"  Pass --min-coverage 95 for the ones known to render correctly."
    )


def _above_coverage(found: list, percent: float) -> list:
    # pylint: disable=container-return
    """⚠️ Says what it dropped. A filter that silently halved the output would
    read as "the disc has fewer models"."""
    if not percent:
        return found
    kept = [entry for entry in found if entry.mesh.coverage >= percent / 100.0]
    print(
        f"keeping {len(kept)} of {len(found)} model(s) at {percent:g}% coverage or better"
    )
    return kept


def _clip_entry(clip: ClipInfo, written: bool) -> dict:
    # pylint: disable=container-return
    """One clip as the manifest carries it.

    `written` is the field the viewer needs: a clip listed here without one in
    the `.glb` is a clip the budget dropped, not a clip that failed to decode.
    """
    return {
        "name": clip.name,
        "curves": len(clip.curves),
        "keys": sum(len(c.times) for c in clip.curves),
        "span": round(max((c.span for c in clip.curves), default=0.0), 3),
        "poses": len(clip.poses),
        "frames": round(clip.frames, 3),
        "seconds": round(clip.seconds, 4),
        "written": written,
    }


def _summarise(entries: list, dense: bool = False) -> None:
    """What the export produced, in the terms that decide whether to trust it."""
    textured = sum(1 for entry in entries if entry["textured"])
    images = sum(entry["textures"] for entry in entries)
    bare = sum(1 for entry in entries if not entry["textured"])
    animated = sum(1 for entry in entries if entry["animated"])
    clips = sum(len(entry["clips"]) for entry in entries)
    curves = sum(c["curves"] for entry in entries for c in entry["clips"])
    played = sum(entry["animations"] for entry in entries)
    dropped = sum(entry["animations_dropped"] for entry in entries)
    targets = sum(entry["targets"] for entry in entries)
    shapes = sum(entry["painted"] for entry in entries)
    print(f"  {textured} carry a texture, {images} embedded image(s) in total")
    print(f"  {shapes} shape(s) resolve to one, counted in the files themselves")
    if bare:
        print(
            f"  ! {bare} name no image at all: every shape in them draws with\n"
            f"    vertex colour, which the file states rather than this reader\n"
            f"    failing to find one (D243)."
        )
    cap = DENSE if dense else SPARSE
    shape = "dense" if dense else "sparse"
    print(f"  {animated} carry a playable morph animation")
    print(f"  {played} clip(s) written as {targets} {shape} morph target(s)")
    if dropped:
        print(
            f"  ! {dropped} further clip(s) did NOT fit the per-file budget of\n"
            f"    {cap.targets} target(s) or {cap.size // 1024} KiB, whichever\n"
            f"    binds first. Each is listed in the manifest with written: false."
        )
    print(f"  {clips} clip(s) and {curves} curve(s) listed in the manifest")
    print("  a .glb opens in Blender, Windows 3D Viewer or any browser")


def cmd_export(args: argparse.Namespace) -> int:
    out = Path(args.out)
    tree = exportlayout.Tree(out)

    base = _base()
    found = _above_coverage(_walk(base, args.search or ""), args.min_coverage)
    entries: list[dict] = []
    failed: list[str] = []
    for entry in found:
        paints = (
            [] if args.no_textures else textures_for(base, entry.disc_path, entry.mesh)
        )
        animation = (
            Animations()
            if args.no_animation
            else fit_animations(entry.mesh, entry.clips, args.dense_morphs)
        )
        written = [clip.as_gltf() for clip in animation.clips]
        try:
            blob = gltf.write(
                entry.mesh,
                name=entry.name,
                clips=written,
                sparse=not args.dense_morphs,
                paints=paints,
            )
        except ValueError as exc:
            failed.append(f"{entry.name}: {exc}")
            continue
        tree.write(entry.relative, blob)
        # ⚠️ Counted out of the bytes just written, never from `paints`. An
        # image the caller decoded is not an image a primitive reaches (D245).
        painted = gltf.painting(blob)
        lowest, highest = _extent(entry.mesh)
        entries.append(
            {
                "name": entry.name,
                "shape": entry.mesh.name,
                "file": entry.relative,
                "source": entry.disc_path,
                "positions": len(entry.mesh.positions),
                "faces": len(entry.mesh.faces),
                "triangles": len(entry.mesh.triangles()),
                "coverage": round(entry.mesh.coverage, 4),
                "fragment": entry.mesh.coverage < WHOLE,
                "textured": painted.textured,
                "textures": painted.images,
                "painted": painted.painted,
                "shapes": entry.mesh.shapes,
                "animated": bool(animation.clips),
                "animations": len(animation.clips),
                "animations_dropped": animation.dropped,
                "targets": animation.targets,
                "clips": [
                    _clip_entry(clip, animation.wrote(clip)) for clip in entry.clips
                ],
                "min": [round(v, 4) for v in lowest],
                "max": [round(v, 4) for v in highest],
            }
        )

    (out / MANIFEST).write_text(
        json.dumps({"schema": 1, "models": entries}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} .glb file(s) under {out / KIND}")
    print(f"  and {MANIFEST} to {out}")
    _summarise(entries, args.dense_morphs)
    if failed:
        print(f"\n{len(failed)} could not be written:")
        for note in failed[:5]:
            print(f"  {note}")
    _warn_about_coverage(found)
    return 0


def register(add: AddCommand) -> None:
    parser = add("model", help="look at the game's geometry")
    sub = parser.add_subparsers(dest="model_command", required=True)

    listing = sub.add_parser("list", help="every model whose mesh can be read")
    listing.add_argument("--search", help="only paths containing this")
    listing.add_argument("--limit", type=int, default=40)
    listing.set_defaults(func=cmd_list)

    export = sub.add_parser("export", help="write models out as glTF (.glb)")
    export.add_argument("--out", default="work/models", help="where to write them")
    export.add_argument("--search", help="only paths containing this")
    export.add_argument(
        "--no-textures", action="store_true", help="geometry only, smaller files"
    )
    export.add_argument("--no-animation", action="store_true", help="skip morph targets")
    export.add_argument(
        "--dense-morphs",
        action="store_true",
        help="write every morph target in full rather than as a sparse "
        "accessor; larger files and far fewer clips, for a viewer that will "
        "not read sparse",
    )
    export.add_argument(
        "--min-coverage",
        type=float,
        default=0.0,
        metavar="PCT",
        help="only models whose faces reach this much of their vertices; "
        "95 gives the 132 that are known to render correctly",
    )
    export.set_defaults(func=cmd_export)
