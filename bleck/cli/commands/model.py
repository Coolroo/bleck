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

⛔ **What this exports is a fragment, and it says so.** One shape record is
read per file; a character file names dozens. Median coverage is **13.6%** —
`p_big_kuppa` exports three of its 3,401 vertices. Every command here prints the
coverage, and the manifest carries it, so nothing downstream can mistake a
fragment for a character (D211).
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


#: Morph targets one file may carry, across every clip in it.
#:
#: ⚠️ **Measured, not picked round.** 218 of 864 models have a clip that moves
#: something, and they hold 3,079 such clips between them; 256 is the smallest
#: cap under which *every one of those 218 gets at least one clip*, because a
#: file whose shortest usable clip is 245 poses gets nothing from a smaller one.
#: It keeps 2,256 of the 3,079 (D235).
MAX_TARGETS = 256

#: ...and the bytes those targets may take, whichever binds first. A target
#: costs `vertices * 12`, so the cap above alone would give `e_3D_manera2` --
#: 3,811 welded vertices -- an 11 MB animation block on a 130 KB mesh. At 2 MiB
#: the largest file in a full export is 2.08 MB.
MORPH_BUDGET = 2 * 1024 * 1024


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


def budget(vertices: int) -> int:
    """How many targets this mesh may carry, of the two caps that apply."""
    cost = max(vertices * gltf.TARGET_BYTES, 1)
    return min(MAX_TARGETS, MORPH_BUDGET // cost)


def fit_animations(clips: list, vertices: int) -> Animations:
    """Every clip that moves something and fits, in the file's own order.

    ⚠️ **Greedy, in file order, skipping what does not fit.** A clip too big
    for what is left does not end the walk — a 245-pose clip in the middle of a
    file must not cost every shorter clip behind it.
    """
    usable = [clip for clip in clips if clip.poses]
    allowed = budget(vertices)
    kept: list = []
    left = allowed
    for clip in usable:
        if len(clip.poses) <= left:
            left -= len(clip.poses)
            kept.append(clip)
    return Animations(clips=kept, dropped=len(usable) - len(kept), targets=allowed - left)


def texture_for(
    base: Path, disc_path: str, shapes: int = 1, guess: bool = False
) -> bytes:
    """Image 0 of the bank beside a model, when that is unambiguous.

    ⛔ **A model with more than one shape gets no texture** (D229). Every
    shape's UVs span the whole [0,1] square, so each has its *own* image rather
    than a region of an atlas, and which image goes with which shape is not
    decoded. Painting image 0 across all of them draws the whole sprite sheet
    onto every limb -- `e_2D_manera6` rendered as a crowd of small Mimis on a
    big one.

    ⚠️ 109 of 870 models have a single shape. The other 761 export untextured
    until the binding is found, because wrong texturing looks like a broken
    renderer while no texturing looks like what it is.

    ⛔ `guess=True` overrides that and gives every shape image 0 anyway. **It
    is wrong for most models** and exists only because grey geometry is hard to
    identify; the manifest marks each one `texture_guessed` so nothing
    downstream mistakes it for a reading. Three mappings have been refuted:
    shape *i* to texture *i* (31% vs a 24% shuffled control), the slot-17 table
    (23% -- worse than shuffling), and a material index in the face record
    (always zero). See D229.
    """
    if shapes != 1 and not guess:
        return b""
    bank = model.bank_for(base / disc_path)
    if not bank.is_file():
        return b""
    try:
        raw = bank.read_bytes()
        images = tpl.read(raw) if tpl.is_tpl(raw) else []
        if not images:
            return b""
        pixels = texdecode.decode(raw, images[0])
        return png.write(pixels.width, pixels.height, pixels.rgba)
    except (tpl.TextureError, OSError, ValueError):
        # ⚠️ An undecodable bank costs a texture, never the geometry.
        return b""


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


def _summarise(entries: list) -> None:
    """What the export produced, in the terms that decide whether to trust it."""
    textured = sum(1 for entry in entries if entry["textured"])
    many = sum(1 for entry in entries if entry["shapes"] > 1)
    animated = sum(1 for entry in entries if entry["animated"])
    clips = sum(len(entry["clips"]) for entry in entries)
    curves = sum(c["curves"] for entry in entries for c in entry["clips"])
    guessed = sum(1 for entry in entries if entry["texture_guessed"])
    played = sum(entry["animations"] for entry in entries)
    dropped = sum(entry["animations_dropped"] for entry in entries)
    targets = sum(entry["targets"] for entry in entries)
    print(f"  {textured} carry an embedded texture")
    if guessed:
        print(
            f"  ! {guessed} of those are GUESSED -- every shape got image 0,\n"
            f"    which is wrong for most of them. The manifest marks each one\n"
            f"    texture_guessed; the binding is not decoded (D229)."
        )
    elif many:
        print(
            f"  ! {many} have several shapes and export untextured: each shape\n"
            f"    has its own image and the binding is not decoded (D229).\n"
            f"    --guess-textures paints image 0 on them anyway."
        )
    print(f"  {animated} carry a playable morph animation")
    print(f"  {played} clip(s) written as {targets} morph target(s)")
    if dropped:
        print(
            f"  ! {dropped} further clip(s) did NOT fit the per-file budget of\n"
            f"    {MAX_TARGETS} target(s) or {MORPH_BUDGET // 1024} KiB, whichever\n"
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
        texture = (
            b""
            if args.no_textures
            else texture_for(
                base, entry.disc_path, entry.mesh.shapes, args.guess_textures
            )
        )
        animation = (
            Animations()
            if args.no_animation
            else fit_animations(entry.clips, gltf.vertex_count(entry.mesh))
        )
        written = [clip.as_gltf() for clip in animation.clips]
        try:
            tree.write(
                entry.relative, gltf.write(entry.mesh, texture, entry.name, written)
            )
        except ValueError as exc:
            failed.append(f"{entry.name}: {exc}")
            continue
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
                "textured": entry.mesh.is_textured and bool(texture),
                "texture_guessed": bool(texture) and entry.mesh.shapes > 1,
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
    _summarise(entries)
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
        "--guess-textures",
        action="store_true",
        help="give multi-shape models image 0 anyway; wrong for most of them, "
        "and the manifest marks each one guessed",
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
