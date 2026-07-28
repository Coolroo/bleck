"""Booting a built image in Dolphin.

Separate from `disc.py` because the emulator is a different program from the
disc tools. `Dolphin.exe` and `DolphinTool.exe` ship in the same folder and are
easy to confuse, but only one of them boots a game.

This closes the edit-build-boot loop: without it, the last step of testing a mod
is the only one that happens outside `bleck`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from bleck import platforms
from bleck.backends.disc import DiscError, find_tool

DOLPHIN = platforms.DOLPHIN


@dataclass(frozen=True)
class Launch:
    """A Dolphin process that was started."""

    executable: str
    image: Path
    pid: int

    exit_code: int | None = None
    """The emulator's exit status, or None if it was left running."""

    @property
    def finished(self) -> bool:
        return self.exit_code is not None


def launch(
    image: Path,
    batch: bool = False,
    wait: bool = False,
    unlimited: bool = False,
    state: Path | None = None,
) -> Launch:
    """Boot a disc image in Dolphin.

    Returns as soon as the emulator starts unless `wait` is set — a build-and-
    boot loop wants its shell back, not a terminal pinned until the game is
    closed. `wait` exists for scripting, where the exit code is the point.

    `batch` adds Dolphin's `-b`, which boots straight into the game instead of
    opening the game list first.

    `unlimited` removes the 100% speed cap. Super Paper Mario spends its first
    ~2,100 frames on logos, so a cold boot takes about 45 seconds of watching
    nothing; uncapped it reaches gameplay in about 6 (D63).

    ⚠️ It stays uncapped. Dolphin's `-C` is a session override, so nothing leaks
    into the user's config — but there is no way to restore the cap part-way
    through a run, which makes this useless for anything a human wants to play.
    For that, put the destination in the disc with `code.boot` (`--map`) and
    leave the speed alone. D64.

    `state` loads a Dolphin save state, which skips the boot altogether and --
    more usefully -- carries a save with it. Entering a map without one leaves
    the player character uninitialised and invisible.
    """
    if not image.exists():
        raise DiscError(f"no such image: {image}")

    dolphin = find_tool(DOLPHIN)
    args = [dolphin]
    if batch:
        args.append("-b")

    # The two-token `-e <path>` form, never `--exec=<path>`. The joined form has
    # to be quoted by whoever builds the command line, and a path that arrives
    # still wrapped in its quotes makes Dolphin report "Could not be opened!
    # This may happen with improper permissions, or use by another process" —
    # which blames permissions for what is actually a mangled argument.
    args += ["-e", str(image.resolve())]

    if unlimited:
        args += ["-C", "Dolphin.Core.EmulationSpeed=0"]
    if state is not None:
        if not state.exists():
            raise DiscError(f"no save state at {state}")
        args += ["-s", str(state.resolve())]

    try:
        # Deliberately not a context manager: the emulator has to outlive this
        # process, so there is nothing to close here.
        process = subprocess.Popen(args)  # pylint: disable=consider-using-with
    except OSError as exc:
        raise DiscError(f"could not start {Path(dolphin).name}: {exc}") from exc

    if not wait:
        return Launch(dolphin, image, process.pid)
    return Launch(dolphin, image, process.pid, exit_code=process.wait())
