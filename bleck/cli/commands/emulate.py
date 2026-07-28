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
    result = emulator.launch(
        Path(args.image),
        batch=args.batch,
        wait=args.wait,
        unlimited=args.fast,
        state=Path(args.state) if args.state else None,
    )
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
    p.add_argument(
        "--fast",
        action="store_true",
        help="uncap emulation speed; reaches gameplay in ~6s instead of ~45s",
    )
    p.add_argument(
        "--state",
        help="load a Dolphin save state, skipping the boot and carrying a save",
    )
    p.set_defaults(func=cmd_launch)
