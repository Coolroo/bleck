"""Check a frozen `bleck` binary actually works before it is published.

A PyInstaller build that *builds* proves almost nothing; the failures that
matter are all at runtime -- a data file bundled to the wrong path, a command
module nothing references by name, a compiled dependency missing its native
half. CI runs this against the artifact it just built, on every platform.

    uv run python scripts/smoke_binary.py work/dist/bleck

⚠️ Every check must be able to fail where it runs. These need no extracted
disc, so they work on a CI machine that has never seen the game -- the first
version's map check quietly required one and passed only where it could not
fail.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


#: A real map name, and the id `mapcatalog.json` records for it. Nothing on the
#: disc stores the id, so it can only come from the bundled catalog.
SAMPLE_MAP = "he1_01"
SAMPLE_MAP_ID = "26"

#: A real item, and the English name `itemcatalog.json` records for it.
#:
#: ⚠️ The **name**, and deliberately not the id -- the opposite choice to the
#: map above, for the same underlying reason. Ids and `ITEM_ID_*` constants live
#: in `bleck/formats/itemids.py`, a generated *module* (D119), so PyInstaller
#: carries them whether or not the JSON is bundled: `0x041` and
#: `ITEM_ID_USE_HONOO_SAKURETU` would both print from a binary with no item
#: catalog at all. `Fire Burst` is text from `files/msg/UK` and exists nowhere
#: but the catalog, so it is the only column whose absence this can see.
#:
#: `fire_burst` as the query matters too: it is an English-tier alias, so with
#: no catalog the search matches nothing and the command exits 1 as well.
SAMPLE_ITEM = "fire_burst"
SAMPLE_ITEM_NAME = "Fire Burst"


@dataclass(frozen=True)
class Check:
    """One thing the binary must be able to do, and how to tell."""

    name: str
    args: list[str]
    expect: str = ""
    """Text that must appear in stdout. Empty means "any success will do"."""

    json_out: bool = False
    """Parse stdout as JSON, so malformed output fails rather than passing."""

    needs_base: bool = False
    """Point `BLECK_BASE_DIR` at the synthetic disc before running."""


#: Each covers a different way packaging goes wrong, not a different feature.
CHECKS = [
    Check("starts at all", ["--help"], expect="usage"),
    Check(
        "builtin catalog is bundled",
        ["script", "builtins", "--search", "pouch"],
        expect="evt_pouch",
    ),
    Check(
        "map catalog is bundled",
        ["maps", "--search", SAMPLE_MAP],
        # The id, not the name -- the name would come back from the synthetic
        # disc even with no catalog bundled at all.
        expect=SAMPLE_MAP_ID,
        needs_base=True,
    ),
    Check(
        "item catalog is bundled",
        ["items", "--search", SAMPLE_ITEM],
        expect=SAMPLE_ITEM_NAME,
        # No `needs_base`: unlike maps, both halves of an item's name ship with
        # `bleck`, so this check works on a machine with no disc at all.
    ),
    Check(
        "pydantic models load and emit a schema",
        ["mod", "schema"],
        json_out=True,
    ),
    Check(
        "setup schema too, so both API modules import",
        ["setup", "schema", "--of", "edits"],
        json_out=True,
    ),
    Check(
        "every command module was collected",
        ["mod", "--help"],
        expect="export",
    ),
]


def synthetic_base(root: Path) -> Path:
    """A base build with one map and nothing else.

    `bleck maps` takes names from the disc and ids from the bundled catalog;
    this is the smallest thing exercising both without a real extraction.
    """
    map_dir = root / "files" / "map"
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / f"{SAMPLE_MAP}.bin").write_bytes(b"")
    return root


def run(binary: Path, check: Check, base: Path) -> str:
    environment = dict(os.environ)
    if check.needs_base:
        environment["BLECK_BASE_DIR"] = str(base)
    result = subprocess.run(
        [str(binary), *check.args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=environment,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"FAIL {check.name}\n"
            f"  {binary.name} {' '.join(check.args)} exited {result.returncode}\n"
            f"  {(result.stderr or result.stdout).strip()[:500]}"
        )
    if check.expect and check.expect not in result.stdout:
        raise SystemExit(
            f"FAIL {check.name}\n"
            f"  expected {check.expect!r} in the output, got:\n"
            f"  {result.stdout.strip()[:500]}"
        )
    if check.json_out:
        try:
            json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"FAIL {check.name}\n  output is not valid JSON: {exc}"
            ) from exc
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("binary", help="path to the built executable")
    args = parser.parse_args()

    binary = Path(args.binary)
    if not binary.exists():
        # Windows adds the suffix; accepting either keeps one CI command.
        binary = binary.with_suffix(".exe")
    if not binary.exists():
        raise SystemExit(f"no binary at {args.binary}")

    with tempfile.TemporaryDirectory(prefix="bleck-smoke-") as scratch:
        base = synthetic_base(Path(scratch) / "base")
        for check in CHECKS:
            run(binary, check, base)
            print(f"ok   {check.name}")
    print(f"\n{len(CHECKS)} checks passed against {binary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
