"""Check a frozen `bleck` binary actually works before it is published.

⚠️ A PyInstaller build that *builds* proves almost nothing. The failures that
matter are all at runtime: a data file bundled to the wrong path, a command
module never imported because nothing references it by name, a compiled
dependency missing its native half. Each produces a binary that starts happily
and then reports an empty catalog or an unknown subcommand — which reads as a
corrupt install rather than a packaging bug.

So CI runs this against the artifact it just built, on every platform.

    uv run python scripts/smoke_binary.py work/dist/bleck

Deliberately needs no extracted disc: these check what is *inside* the binary,
so they run on a CI machine that has never seen the game.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    """One thing the binary must be able to do, and how to tell."""

    name: str
    args: list[str]
    expect: str = ""
    """Text that must appear in stdout. Empty means "any success will do"."""

    json_out: bool = False
    """Parse stdout as JSON, so malformed output fails rather than passing."""


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
        ["maps", "--search", "he1_0"],
        expect="383 maps",
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


def run(binary: Path, check: Check) -> str:
    result = subprocess.run(
        [str(binary), *check.args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
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

    for check in CHECKS:
        run(binary, check)
        print(f"ok   {check.name}")
    print(f"\n{len(CHECKS)} checks passed against {binary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
