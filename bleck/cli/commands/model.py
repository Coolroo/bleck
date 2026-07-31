"""`model` commands: see what geometry is on the disc, and get it out.

The counterpart to `texture export`, and it exists for the same reason — until
a mesh can be looked at, every claim about it is a claim about a hex dump.

⛔ **Export is for looking, never for building.** Nothing reads an OBJ back in.
A model edit, when it arrives, will be declared as data against the user's own
disc like every other edit (see `vision.md`), not shipped as baked geometry.

The export writes `models.json` beside the OBJ files, and *that* is the
contract Dimentio reads. A filename cannot say which shape inside a file it
came from, how many faces it had, or what it measures.

⛔ **What this exports is a fragment, and it says so.** One shape record is
read per file; a character file names dozens. Median coverage is **13.6%** —
`p_big_kuppa` exports three of its 3,401 vertices. Every command here prints the
coverage, and the manifest carries it, so nothing downstream can mistake a
fragment for a character (D211).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from bleck.cli.types import AddCommand
from bleck.common.errors import UserError
from bleck.formats import gltf, model, png, texdecode, tpl
from bleck.mods import registry

CATEGORY = "inspection"

#: Written beside the OBJ files. Dimentio reads this, not the directory listing.
MANIFEST = "models.json"

#: Where character models live on the disc.
MODEL_DIR = "files/a"


@dataclass(frozen=True)
class Found:
    """One model file, and the mesh read out of it."""

    disc_path: str
    mesh: model.Mesh

    @property
    def name(self) -> str:
        return Path(self.disc_path).name

    @property
    def filename(self) -> str:
        return f"{self.name}.glb"


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
            found.append(Found(relative, mesh))
    return found


def texture_for(base: Path, disc_path: str) -> bytes:
    """Image 0 of the bank beside a model, as PNG, or empty when there is none.

    ⚠️ **Image 0, not the right image.** Which texture a shape draws with is not
    decoded; the bank pairing is (D202), and most banks hold one image. A model
    whose bank holds several may be textured with the wrong one.
    """
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


def cmd_export(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    base = _base()
    found = _walk(base, args.search or "")
    if args.min_coverage:
        wanted = args.min_coverage / 100.0
        kept = [entry for entry in found if entry.mesh.coverage >= wanted]
        # ⚠️ Said out loud. A filter that silently halved the output would
        # read as "the disc has fewer models".
        print(
            f"keeping {len(kept)} of {len(found)} model(s) at "
            f"{args.min_coverage:g}% coverage or better"
        )
        found = kept
    entries: list[dict] = []
    failed: list[str] = []
    for entry in found:
        texture = b"" if args.no_textures else texture_for(base, entry.disc_path)
        try:
            (out / entry.filename).write_bytes(
                gltf.write(entry.mesh, texture, entry.name)
            )
        except ValueError as exc:
            failed.append(f"{entry.name}: {exc}")
            continue
        lowest, highest = _extent(entry.mesh)
        entries.append(
            {
                "name": entry.name,
                "shape": entry.mesh.name,
                "file": entry.filename,
                "source": entry.disc_path,
                "positions": len(entry.mesh.positions),
                "faces": len(entry.mesh.faces),
                "triangles": len(entry.mesh.triangles()),
                "coverage": round(entry.mesh.coverage, 4),
                "fragment": True,
                "textured": entry.mesh.is_textured and bool(texture),
                "min": [round(v, 4) for v in lowest],
                "max": [round(v, 4) for v in highest],
            }
        )

    (out / MANIFEST).write_text(
        json.dumps({"schema": 1, "models": entries}, indent=2) + "\n",
        encoding="utf-8",
    )
    textured = sum(1 for entry in entries if entry["textured"])
    print(f"wrote {len(entries)} .glb file(s) and {MANIFEST} to {out}")
    print(f"  {textured} carry an embedded texture")
    print("  a .glb opens in Blender, Windows 3D Viewer or any browser")
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
    export.add_argument(
        "--min-coverage",
        type=float,
        default=0.0,
        metavar="PCT",
        help="only models whose faces reach this much of their vertices; "
        "95 gives the 132 that are known to render correctly",
    )
    export.set_defaults(func=cmd_export)
