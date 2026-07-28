"""Mod commands. The base game is read-only throughout — these write only into
the mods or build directories.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from bleck import api
from bleck.backends import emulator, gecko, maps
from bleck.cli.types import AddCommand
from bleck.common.errors import UserError
from bleck.common.fsio import guard_overwrite
from bleck.formats import lz77, u8
from bleck.mods import builder, manifest, registry, resolver
from bleck.mods.build import outputs
from bleck.mods.build.overlay import normalize_disc_path, resolve_target

from .disc import add_format_flags

CATEGORY = "mods"


def _registry() -> registry.Registry:
    return registry.load()


def _base() -> Path:
    base = registry.base_root()
    if not base.is_dir():
        raise UserError(
            f"no extracted base at {base}\n"
            "  run `bleck extract <disc>` first, or set BLECK_BASE_DIR"
        )
    return base


def cmd_new(args: argparse.Namespace) -> int:
    root = registry.mods_root() / args.name
    if root.exists() and not args.force:
        raise UserError(f"{root} already exists (use --force to overwrite)")

    (root / manifest.OVERLAY_DIR).mkdir(parents=True, exist_ok=True)
    manifest.write(
        root,
        manifest.Manifest(
            name=args.name,
            version=manifest.Version(0, 1, 0),
            description=args.description,
            author=args.author,
            base=_base().name,
        ),
    )
    print(f"created {root}/")
    print(f"  edit {root}/{manifest.MANIFEST_NAME}")
    print(f"  then `bleck mod vendor {args.name} <disc-path>`")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    found = _registry()
    if not found.mods:
        print(f"no mods in {found.root}")
        return 0
    for mod in found.mods:
        overrides = len(mod.overlay_paths())
        deps = ", ".join(str(d) for d in mod.manifest.dependencies) or "none"
        print(f"{mod.name}  {mod.manifest.version}  base={mod.manifest.base or '?'}")
        print(f"  overrides: {overrides} file(s)   depends on: {deps}")
    return 0


def cmd_vendor(args: argparse.Namespace) -> int:
    """Copy a file out of the base into a mod's overlay, ready to edit."""
    mod = _registry().require(args.name)
    base = _base()
    disc_path = normalize_disc_path(base, args.path)
    target = resolve_target(base, disc_path)

    source = base / target.disc_path
    if not source.exists():
        raise UserError(f"{target.disc_path} is not in the base ({base})")

    data = source.read_bytes()
    if target.is_member:
        if lz77.is_lz77(data):
            data = lz77.decompress(data)
        if not u8.is_u8(data):
            raise UserError(f"{target.disc_path} is not an archive")
        entry = next((e for e in u8.read(data) if e.path == target.member), None)
        if entry is None:
            raise UserError(f"no member {target.member!r} in {target.disc_path}")
        data = u8.extract(data, entry)

    destination = mod.overlay / disc_path
    guard_overwrite(destination, args.force)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(f"vendored -> {destination}  ({len(data):,} bytes)")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    mod = _registry().require(args.name)
    base = _base()
    paths = mod.overlay_paths()
    if not paths:
        print(f"{mod.name} overrides nothing yet")
        return 0

    print(f"{mod.name} {mod.manifest.version} overrides {len(paths)} file(s):")
    for relative in paths:
        target = resolve_target(base, relative)
        kind = "member" if target.is_member else "file"
        print(f"  [{kind}] {target}")
    for path in mod.manifest.exclusive:
        print(f"  [exclusive] {path}")
    for path in mod.manifest.remove:
        print(f"  [remove] {path}")
    return 0


def cmd_chain(args: argparse.Namespace) -> int:
    chain = resolver.resolve(_registry(), args.name)
    for i, entry in enumerate(chain.entries, start=1):
        who = "target" if entry.is_target else f"required by {entry.required_by}"
        print(f"{i}. {entry.mod.name:<24} {entry.mod.manifest.version}  ({who})")
    return 0


def boot_override(args: argparse.Namespace, base: Path) -> builder.CodeOverride:
    """Turn command-line flags into build-time code changes.

    `--map` takes a map name or numeric id, resolved here so a typo is caught
    against the real map list before anything compiles.
    """
    if not args.map:
        return builder.CodeOverride()

    index = maps.load(base)
    wanted = str(args.map).strip()

    if wanted.lstrip("-").isdigit():
        found = next((e for e in index.entries if e.map_id == int(wanted)), None)
        if found is None:
            raise UserError(
                f"no map with id {wanted}. `bleck maps` lists all "
                f"{len(index.entries)} of them with their ids."
            )
        return builder.CodeOverride(boot_map=found.name)

    if index.find(wanted) is None:
        close = difflib.get_close_matches(
            wanted, [e.name for e in index.entries], n=3, cutoff=0.5
        )
        hint = f"\n  Did you mean: {', '.join(close)}?" if close else ""
        raise UserError(
            f"no map named {wanted!r} in {len(index.entries)} maps.\n"
            f"  `bleck maps --search {wanted[:3]}` will narrow it down.{hint}"
        )
    return builder.CodeOverride(boot_map=wanted)


def cmd_check(args: argparse.Namespace) -> int:
    chain = resolver.resolve(_registry(), args.name)
    base = _base()
    report = builder.check(chain, base, args.merge_binary, boot_override(args, base))
    return _report(report, chain)


def resolve_output(args: argparse.Namespace) -> outputs.OutputKind:
    """Which output kind to run: explicit name, legacy flag, then the path.

    `--no-image` and `--format` predate `--output` and still mean what they did.
    """
    if args.output:
        return outputs.find(args.output)
    if args.no_image:
        return outputs.NONE
    if args.format:
        return outputs.find(args.format)
    return outputs.for_path(Path(args.out)) if args.out else outputs.ISO


def cmd_build(args: argparse.Namespace) -> int:
    chain = resolver.resolve(_registry(), args.name)
    base = _base()
    staged = registry.build_root() / args.name
    report = builder.build(
        chain, base, staged, args.merge_binary, boot_override(args, base)
    )
    if _report(report, chain) != 0:
        return 1

    print(
        f"staged {staged}  "
        f"({report.files_written} file(s), {report.archives_merged} archive(s) merged"
        + (f", {report.files_removed} removed" if report.files_removed else "")
        + ")"
    )

    kind = resolve_output(args)
    if not kind.produces_artifact:
        if args.launch:
            raise UserError(f"--launch has nothing to boot with --output {kind.name}")
        return 0

    if kind.embeds_loader:
        _embed_loader(chain, staged, args)

    out = (
        Path(args.out) if args.out else kind.default_out(registry.build_root(), args.name)
    )
    guard_overwrite(out, args.force)
    result = kind.write(
        outputs.OutputRequest(
            name=args.name,
            base=base,
            staged=staged,
            out=out,
            keep_iso=args.keep_iso,
            base_image=Path(args.base_image) if args.base_image else None,
        )
    )
    for warning in result.warnings:
        print(f"warning: {warning}")
    if result.summary:
        print(result.summary)

    if args.launch:
        if result.bootable is None:
            raise UserError(f"--output {kind.name} produced nothing Dolphin can boot")
        started = emulator.launch(result.bootable)
        print(f"launched {result.bootable.name} in Dolphin  (pid {started.pid})")
    return 0


def _embed_loader(chain: resolver.Chain, staged: Path, args: argparse.Namespace) -> None:
    """Put the Gecko loader inside the disc, so a code mod runs without setup.

    A missing codelist warns loudly rather than failing — the loader may already
    be in Dolphin's cheat configuration.
    """
    coded = [mod for mod in chain.mods if mod.manifest.has_code]
    if not coded or args.no_embed_loader:
        return

    target = coded[-1].manifest.code.target
    try:
        result = gecko.embed_loader(staged, target, registry.build_root() / ".gecko")
    except gecko.GeckoError as exc:
        print(f"warning: the Gecko loader was NOT embedded:\n  {exc}")
        print(
            "  The mod will only run if the loader is in Dolphin's cheat "
            "configuration.\n  Pass --no-embed-loader to silence this."
        )
        return
    print(result.describe())


def _report(report: builder.BuildReport, chain: resolver.Chain) -> int:
    for built in report.code_builds:
        print(built.describe())
    for warning in report.warnings:
        print(f"warning: {warning}")
    if report.conflicts:
        print(f"error: {len(report.conflicts)} conflict(s)")
        for conflict in report.conflicts:
            print(conflict.describe())
        return 1
    print(f"chain OK: {' -> '.join(mod.name for mod in chain.mods)}")
    return 0


def register(add: AddCommand) -> None:
    parser = add("mod", help="create, inspect and build mods")
    sub = parser.add_subparsers(dest="mod_command", required=True, metavar="<action>")

    def action(name: str, func, help_text: str) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--force", action="store_true", help="overwrite output")
        child.set_defaults(func=func)
        return child

    child = action("new", cmd_new, "create and register a mod")
    child.add_argument("name")
    child.add_argument("--description", default="")
    child.add_argument("--author", default="")

    action("list", cmd_list, "list registered mods")

    child = action("vendor", cmd_vendor, "copy a file from the base into a mod")
    child.add_argument("name")
    child.add_argument("path", help="disc path, may address an archive member")

    child = action("status", cmd_status, "what a mod overrides")
    child.add_argument("name")

    child = action("chain", cmd_chain, "resolved install order")
    child.add_argument("name")

    child = action("export", cmd_export, "a mod's declarations as JSON")
    child.add_argument("name")

    child = action("import", cmd_import, "write a JSON document to a mod.json")
    child.add_argument("name")
    child.add_argument(
        "--json", required=True, metavar="FILE", help="document, or - for stdin"
    )

    action("schema", cmd_schema, "JSON Schema for a mod document")

    child = action("check", cmd_check, "resolve and detect conflicts; writes nothing")
    child.add_argument("name")
    _add_merge_flag(child)
    _add_map_flag(child)

    child = action("build", cmd_build, "base + chain -> disc image or patch")
    child.add_argument("name")
    child.add_argument("out", nargs="?")
    child.add_argument(
        "--output",
        choices=outputs.names(),
        default="",
        metavar="KIND",
        help="what to produce. " + outputs.describe_choices(),
    )
    child.add_argument(
        "--no-image",
        action="store_true",
        help="stage only, skip writing a disc image (same as --output none)",
    )
    child.add_argument(
        "--base-image",
        metavar="PATH",
        default="",
        help="an untouched disc image for a Riivolution patch to sit on; "
        "without it, Dolphin boots the extracted base directly",
    )
    child.add_argument(
        "--no-embed-loader",
        action="store_true",
        help="do not put the Gecko loader inside the disc",
    )
    child.add_argument(
        "--launch",
        action="store_true",
        help="boot the result in Dolphin once it is built",
    )
    add_format_flags(child)
    _add_merge_flag(child)
    _add_map_flag(child)


def _add_map_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--map",
        metavar="NAME|ID",
        help=(
            "start the game at this map instead of the attract demo, "
            "e.g. --map he1_01 or --map 42"
        ),
    )


def _add_merge_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--merge-binary",
        action="store_true",
        help=(
            "auto-merge disjoint edits to the same binary file; off by default "
            "because byte-disjoint edits can still be semantically incompatible"
        ),
    )


def _read_json(source: str) -> str:
    """JSON from a file, or from stdin when the path is `-`."""
    if source == "-":
        return sys.stdin.read()
    path = Path(source)
    if not path.exists():
        raise UserError(f"no such file: {path}")
    return path.read_text(encoding="utf-8")


def cmd_export(args: argparse.Namespace) -> int:
    """A whole mod as JSON. ⚠️ Declarations only — overlay assets stay on disk."""
    mod = _registry().require(args.name)
    print(api.ModDocument.of(mod.manifest).model_dump_json(indent=2))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Write a JSON document back to a mod's `mod.json`.

    ⚠️ Replaces the manifest rather than merging: an omitted field has no
    unsurprising meaning. An editor holds the whole document.
    """
    try:
        document = api.ModDocument.model_validate_json(_read_json(args.json))
    except ValidationError as exc:
        raise UserError(f"{args.json}: {exc}") from exc

    mod = _registry().require(args.name)
    if document.name != mod.name:
        raise UserError(
            f"this document is for {document.name!r}, but you asked to write it "
            f"to {mod.name!r}.\n"
            f"  Renaming a mod means moving its directory; bleck will not do "
            f"that by surprise."
        )

    manifest.write(mod.root, document.to_manifest())
    print(f"wrote {mod.root / manifest.MANIFEST_NAME}")
    return 0


def cmd_schema(_args: argparse.Namespace) -> int:
    """The JSON Schema for a mod document."""
    print(json.dumps(api.ModDocument.model_json_schema(), indent=2))
    return 0
