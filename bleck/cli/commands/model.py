"""`model` commands: see what geometry is on the disc, and get it out.

The counterpart to `texture export`, and it exists for the same reason — until
a mesh can be looked at, every claim about it is a claim about a hex dump.

⛔ **Export is for looking, never for building.** Nothing reads an OBJ back in.
A model edit, when it arrives, will be declared as data against the user's own
disc like every other edit (see `vision.md`), not shipped as baked geometry.

The export writes `models.json` beside the OBJ files, and *that* is the
contract Dimentio reads. A filename cannot say which shape inside a file it
came from, how many faces it had, or what it measures.

⚠️ **One shape per file, for now.** A character file holds several shapes and
only the first is read (D208), so an exported OBJ is a part of a model rather
than the whole of one.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from bleck.cli.types import AddCommand
from bleck.common.errors import UserError
from bleck.formats import model
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
        return f"{self.name}.obj"


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


def write_obj(mesh: model.Mesh) -> str:
    """One mesh as Wavefront OBJ: vertices, then triangles.

    ⚠️ OBJ indices are **1-based**, and an off-by-one here shifts every face by
    a vertex — which still renders, as a recognisable model with wrong
    topology. That is the failure this whole reading has been guarding against.
    """
    lines = [f"# {mesh.name}", f"# {len(mesh.positions)} vertices"]
    for x, y, z in mesh.positions:
        lines.append(f"v {x:.6g} {y:.6g} {z:.6g}")
    for x, y, z in mesh.normals:
        lines.append(f"vn {x:.6g} {y:.6g} {z:.6g}")

    usable = len(mesh.normals)
    for triangle in mesh.corner_triangles():
        parts = []
        for corner in triangle:
            normal = corner.normal
            if normal is None or normal >= usable:
                parts.append(str(corner.position + 1))
            else:
                parts.append(f"{corner.position + 1}//{normal + 1}")
        lines.append("f " + " ".join(parts))
    return "\n".join(lines) + "\n"


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
            f"{entry.name:<24} {mesh.name[:30]:<32} "
            f"{len(mesh.positions):>6} verts {len(mesh.faces):>6} faces"
        )
    if len(found) > len(shown):
        print(f"... and {len(found) - len(shown)} more (raise --limit)")
    print(f"\n{len(found)} model(s)")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    found = _walk(_base(), args.search or "")
    entries: list[dict] = []
    for entry in found:
        (out / entry.filename).write_text(write_obj(entry.mesh), encoding="ascii")
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
                "min": [round(v, 4) for v in lowest],
                "max": [round(v, 4) for v in highest],
            }
        )

    (out / MANIFEST).write_text(
        json.dumps({"schema": 1, "models": entries}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} OBJ file(s) and {MANIFEST} to {out}")
    return 0


def register(add: AddCommand) -> None:
    parser = add("model", help="look at the game's geometry")
    sub = parser.add_subparsers(dest="model_command", required=True)

    listing = sub.add_parser("list", help="every model whose mesh can be read")
    listing.add_argument("--search", help="only paths containing this")
    listing.add_argument("--limit", type=int, default=40)
    listing.set_defaults(func=cmd_list)

    export = sub.add_parser("export", help="write models out as Wavefront OBJ")
    export.add_argument("--out", default="work/models", help="where to write them")
    export.add_argument("--search", help="only paths containing this")
    export.set_defaults(func=cmd_export)
