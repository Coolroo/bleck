"""Emulation commands: launch.

Kept apart from the disc commands because Dolphin the emulator and DolphinTool
the disc utility are different binaries found in different ways. This is also
where per-game emulator configuration will land if `bleck` grows it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bleck.backends import emulator

CATEGORY = "emulation"


def cmd_launch(args: argparse.Namespace) -> int:
    result = emulator.launch(Path(args.image), batch=args.batch, wait=args.wait)
    if result.finished:
        print(f"{result.image.name} exited ({result.exit_code})")
        return result.exit_code or 0
    print(f"launched {result.image.name} in Dolphin  (pid {result.pid})")
    return 0


def register(add) -> None:
    p = add("launch", help="boot a disc image in Dolphin")
    p.add_argument("image")
    p.add_argument(
        "--batch",
        action="store_true",
        help="boot straight into the game, skipping Dolphin's game list",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help="block until the emulator exits, and return its exit code",
    )
    p.set_defaults(func=cmd_launch)
