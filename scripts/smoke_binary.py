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

⚠️ **Nothing here names a row of a catalog.** Every expectation is read out of
the committed JSON the binary is supposed to be carrying, so renaming an entry
carries the check with it. A hard-coded name took the whole matrix down once:
this asked for the item `fire_burst` and its English name `Fire Burst`, D194
stopped shipping the game's own words, and Linux, Windows and macOS then failed
the same assertion about a fact that no longer existed.

⚠️ **A catalog check asserts on a *field*, not on a substring.** Ids and
`ITEM_ID_*` constants come from generated *modules* (D119), so they print from a
binary carrying no catalog at all -- and `ITEM_ID_NULL` contains `NULL`, so even
the internal name is a substring of something that survives. `Check.fields`
compares whitespace-separated columns for that reason.

⚠️ **`npccatalog.json` is bundled and is not checked here.** The only command
that reads it is `bleck setup show`, which needs a real setup file from an
extracted disc; a check that cannot fail on CI is worse than no check.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Floors under each catalog's size. Not the real counts -- those change every
#: time a catalog is regenerated, and pinning them would put back the landmine
#: this file exists without. They are here so an emptied or truncated catalog
#: fails loudly rather than yielding a sample the binary satisfies trivially.
FLOORS = {
    "bleck/script/catalog.json": 300,
    "bleck/backends/mapcatalog.json": 300,
    "bleck/backends/doorcatalog.json": 200,
    "bleck/formats/itemcatalog.json": 400,
}


@dataclass(frozen=True)
class Check:
    """One thing the binary must be able to do, and how to tell."""

    name: str
    args: list[str]

    expect: list[str] = field(default_factory=list)
    """Text that must all appear somewhere in stdout."""

    fields: list[str] = field(default_factory=list)
    """The leading whitespace-separated columns of some one output line.

    Columns rather than a substring, because the interesting failure prints a
    line of the right shape with a column *missing*: with no item catalog
    bundled the name column is blank and the line still contains the id and the
    constant it was going to be compared against.
    """

    json_out: bool = False
    """Parse stdout as JSON, so malformed output fails rather than passing."""

    needs_base: bool = False
    """Point `BLECK_BASE_DIR` at the synthetic disc before running."""


@dataclass(frozen=True)
class Sample:
    """A catalog's first row, and how many rows it has.

    The first row rather than a chosen one: choosing is what produced a check
    naming an item that later stopped existing.
    """

    ident: int
    name: str
    total: int


def rows(relative: str, key: str) -> list:
    """A committed catalog's rows, refusing one too small to prove anything."""
    path = REPO / relative
    if not path.is_file():
        raise SystemExit(f"cannot check the binary: {path} is missing from this repo")
    found = json.loads(path.read_text(encoding="utf-8")).get(key) or []
    floor = FLOORS[relative]
    if len(found) < floor:
        raise SystemExit(
            f"cannot check the binary: {relative} holds {len(found)} {key}, "
            f"fewer than the {floor} these checks assume. Regenerate it."
        )
    return found


def first(relative: str, key: str) -> Sample:
    """The first row of a catalog, reduced to the columns a check reads."""
    found = rows(relative, key)
    head = found[0]
    return Sample(
        ident=int(head.get("id", -1)),
        name=str(head.get("name", "")),
        total=len(found),
    )


def checks(game_map: Sample) -> list[Check]:
    """Every check, with its expectations read from the committed catalogs.

    Built rather than declared, because each catalog check must say what *this
    tree's* catalog holds. A literal here is a literal that goes stale.

    `game_map` is passed in rather than read here so that the check and the
    synthetic disc it runs against cannot name two different maps.
    """
    builtins = first("bleck/script/catalog.json", "builtins")
    item = first("bleck/formats/itemcatalog.json", "items")
    doors = rows("bleck/backends/doorcatalog.json", "maps")
    return [
        Check("starts at all", ["--help"], expect=["usage"]),
        Check(
            "builtin catalog is bundled",
            ["script", "builtins", "--search", builtins.name],
            expect=[builtins.name, f"of {builtins.total} builtins"],
        ),
        Check(
            "map catalog is bundled",
            ["maps", "--search", game_map.name],
            # The id column, which only the catalog can fill: the name comes
            # back off the synthetic disc with no catalog bundled at all, and
            # the id prints as `?`.
            fields=[str(game_map.ident), game_map.name],
            needs_base=True,
        ),
        Check(
            "item catalog is bundled",
            ["items", "--search", item.name],
            # The name column, the opposite choice to the map above and for the
            # same underlying reason: here it is the *id* that survives without
            # a catalog, because `itemids.py` is a module (D119).
            fields=[f"0x{item.ident:03x}", item.name],
        ),
        Check(
            "door catalog is bundled",
            ["doors"],
            expect=[f"across {len(doors)} map(s)"],
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
            expect=["export"],
        ),
    ]


def synthetic_base(root: Path, map_name: str) -> Path:
    """A base build with one map and nothing else.

    `bleck maps` takes names from the disc and ids from the bundled catalog;
    this is the smallest thing exercising both without a real extraction.
    """
    map_dir = root / "files" / "map"
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / f"{map_name}.bin").write_bytes(b"")
    return root


def line_with(out: str, wanted: list[str]) -> bool:
    """Whether some line's leading columns are exactly `wanted`."""
    return any(line.split()[: len(wanted)] == wanted for line in out.splitlines())


def run(binary: Path, check: Check, base: Path, blank: Path) -> str:
    environment = dict(os.environ)
    # ⚠️ Always set, never inherited. An item's English name is resolved at run
    # time from whatever disc `BLECK_BASE_DIR` points at (D194), so a developer
    # with a disc extracted sees a different name column from CI. Pointing the
    # unrelated checks at an empty directory makes every machine agree.
    environment["BLECK_BASE_DIR"] = str(base if check.needs_base else blank)
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
    for wanted in check.expect:
        if wanted not in result.stdout:
            raise SystemExit(
                f"FAIL {check.name}\n"
                f"  expected {wanted!r} in the output, got:\n"
                f"  {result.stdout.strip()[:500]}"
            )
    if check.fields and not line_with(result.stdout, check.fields):
        raise SystemExit(
            f"FAIL {check.name}\n"
            f"  no line starts with the columns {check.fields}, got:\n"
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

    game_map = first("bleck/backends/mapcatalog.json", "maps")
    every = checks(game_map)
    with tempfile.TemporaryDirectory(prefix="bleck-smoke-") as scratch:
        base = synthetic_base(Path(scratch) / "base", game_map.name)
        blank = Path(scratch) / "blank"
        blank.mkdir()
        for check in every:
            run(binary, check, base, blank)
            print(f"ok   {check.name}")
    print(f"\n{len(every)} checks passed against {binary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
