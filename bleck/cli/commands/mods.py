"""Mod commands: new, list, vendor, status, chain, check, build.

The base game is treated as read-only throughout — every command reads from it
and writes only into the mods or build directories.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bleck.backends import disc, emulator
from bleck.common.errors import UserError
from bleck.common.fsio import guard_overwrite
from bleck.formats import lz77, u8
from bleck.mods import builder, manifest, registry, resolver
from bleck.mods.overlay import normalize_disc_path, resolve_target

from .disc import add_format_flags, resolve_format

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


def cmd_check(args: argparse.Namespace) -> int:
    chain = resolver.resolve(_registry(), args.name)
    report = builder.check(chain, _base(), args.merge_binary)
    return _report(report, chain)


def cmd_build(args: argparse.Namespace) -> int:
    chain = resolver.resolve(_registry(), args.name)
    base = _base()
    staged = registry.build_root() / args.name
    report = builder.build(chain, base, staged, args.merge_binary)
    if _report(report, chain) != 0:
        return 1

    print(
        f"staged {staged}  "
        f"({report.files_written} file(s), {report.archives_merged} archive(s) merged"
        + (f", {report.files_removed} removed" if report.files_removed else "")
        + ")"
    )

    if args.no_image:
        if args.launch:
            raise UserError("--launch needs an image to boot; drop --no-image")
        return 0

    default_suffix = disc.ImageFormat(args.format).suffix if args.format else ".iso"
    out = (
        Path(args.out)
        if args.out
        else registry.build_root() / f"{args.name}{default_suffix}"
    )
    guard_overwrite(out, args.force)
    image_format = resolve_format(out, args.format)
    builder.emit(staged, out, image_format, keep_iso=args.keep_iso)
    print(f"built {out}  ({out.stat().st_size:,} bytes, {image_format.value})")

    if args.launch:
        started = emulator.launch(out)
        print(f"launched {out.name} in Dolphin  (pid {started.pid})")
    return 0


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


def register(add) -> None:
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

    child = action("check", cmd_check, "resolve and detect conflicts; writes nothing")
    child.add_argument("name")
    _add_merge_flag(child)

    child = action("build", cmd_build, "base + chain -> ISO")
    child.add_argument("name")
    child.add_argument("out", nargs="?")
    child.add_argument(
        "--no-image", action="store_true", help="stage only, skip writing a disc image"
    )
    child.add_argument(
        "--launch",
        action="store_true",
        help="boot the result in Dolphin once it is built",
    )
    add_format_flags(child)
    _add_merge_flag(child)


def _add_merge_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--merge-binary",
        action="store_true",
        help=(
            "auto-merge disjoint edits to the same binary file; off by default "
            "because byte-disjoint edits can still be semantically incompatible"
        ),
    )
