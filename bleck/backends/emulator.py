"""Booting a built image in Dolphin.

Separate from `disc.py`: `Dolphin.exe` and `DolphinTool.exe` ship in the same
folder and are easy to confuse, but only one of them boots a game.
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

    Returns as soon as the emulator starts unless `wait` is set, which exists
    for scripting where the exit code is the point.

    `batch` adds Dolphin's `-b`: boot straight into the game, no game list.

    `unlimited` removes the 100% speed cap, taking a cold boot from ~45 s to
    ~6 s (D63). ⚠️ It stays uncapped for the whole session — `-C` is a session
    override that cannot be undone part-way — so it is unusable for anything a
    human wants to play. Use `code.boot` (`--map`) for that (D64).

    `state` loads a Dolphin save state, which skips the boot and carries a save
    with it. Entering a map without one leaves the player invisible.
    """
    if not image.exists():
        raise DiscError(f"no such image: {image}")

    dolphin = find_tool(DOLPHIN)
    args = [dolphin]
    if batch:
        args.append("-b")

    # ⚠️ The two-token `-e <path>` form, never `--exec=<path>`: the joined form
    # needs quoting, and a path arriving still quoted makes Dolphin blame
    # permissions ("Could not be opened!") for a mangled argument.
    args += ["-e", str(image.resolve())]

    if unlimited:
        args += ["-C", "Dolphin.Core.EmulationSpeed=0"]
    if state is not None:
        if not state.exists():
            raise DiscError(f"no save state at {state}")
        args += ["-s", str(state.resolve())]

    try:
        # Not a context manager: the emulator has to outlive this process.
        process = subprocess.Popen(args)  # pylint: disable=consider-using-with
    except OSError as exc:
        raise DiscError(f"could not start {Path(dolphin).name}: {exc}") from exc

    if not wait:
        return Launch(dolphin, image, process.pid)
    return Launch(dolphin, image, process.pid, exit_code=process.wait())
