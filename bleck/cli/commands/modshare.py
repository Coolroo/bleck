"""A mod leaving this checkout, or arriving in it.

Split from `mods`, which is everything you do to a mod *here*. These five
commands are the boundary: `pack`/`install` move a mod as a `.bleck` archive,
and `export`/`import`/`schema` move its declarations as JSON.

⚠️ **`export`, `import` and `schema` speak the versioned contract in
`bleck/api/`**, which other programs integrate against — the shapes they print
are that contract's, not this module's, and changing one is a contract change.

⚠️ Neither archive form carries game data. `pack` refuses overlay files without
consent, and says which of the two things it is doing (D186).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from bleck import api
from bleck.common.errors import UserError
from bleck.mods import manifest, pack, registry


def cmd_pack(args: argparse.Namespace) -> int:
    """A mod as a shareable `.bleck` archive, carrying no game data."""
    mod = registry.load().require(args.name)
    plan = pack.plan(mod)
    out = Path(args.output) if args.output else Path(f"{mod.name}{pack.SUFFIX}")

    include = False
    if plan.needs_consent:
        print("")
        print(f"WARNING: {plan.describe_assets()}")
        print("")
        if args.include_assets:
            include = True
            print("  --include-assets given; packing them.")
        else:
            print("  Type exactly: yes I understand")
            print("  Anything else packs the mod without them.")
            try:
                include = input("  > ").strip() == "yes I understand"
            except EOFError:
                include = False
            if not include:
                print("  Packing without them; the mod may be incomplete.")

    result = pack.write(mod, plan, out, include_assets=include)
    print("")
    print(f"{result.path}  ({len(result.packed)} file(s))")
    for name in result.packed:
        print(f"    {name}")
    if result.skipped:
        print(f"  left out, rebuilt on install: {len(result.skipped)} file(s)")
    if result.assets_included:
        # ⚠️ What the author declared, not what bleck assumed. Telling someone
        # their own artwork is game-derived was the bug (D186).
        if mod.manifest.assets is manifest.AssetOrigin.ORIGINAL:
            print("  Includes this mod's overlay files, declared as your own work.")
        else:
            print("  WARNING: includes overlay files that may be game-derived.")
            print('  Declare `"assets"` in mod.json to say which.')
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """Unpack a `.bleck` into the mods directory."""
    done = pack.install(Path(args.file), registry.mods_root(), force=args.force)
    print(f"{done.name} -> {done.root}  ({len(done.files)} file(s))")
    if done.assets_included:
        if done.assets_origin is manifest.AssetOrigin.ORIGINAL:
            print("  Includes overlay files the author declares as their own work.")
        else:
            print("  WARNING: this archive carried overlay files that replace disc")
            print("  content, and the author did not say where they came from.")
    print(f"  build it with: bleck mod build {done.name}")
    return 0


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
    mod = registry.load().require(args.name)
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

    mod = registry.load().require(args.name)
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
