"""Run a mod in Dolphin and read its report block, unattended.

Three rounds of asking a human to look at a screen produced two wrong
conclusions (D38, D40). Reading the game's memory from outside settled the same
question in four runs and has since answered four more, so this is the default
way to test anything in-game — especially when nobody is at the machine.

How it works
------------
A mod writes progress into a fixed block of the game's RAM;
`dolphin-memory-engine` attaches to the running Dolphin *process* and reads it
back. No emulator configuration, no fork, stock builds. The mod side of the
convention is `docs/diagnostics/probe.h`.

    uv run python scripts/ingame.py menu-watch --words 12
    uv run python scripts/ingame.py coin-tick --watch-gw 30

Dolphin is always stopped at the end, including on failure or Ctrl-C.

⚠️ Input injection does not work here. Dolphin reads a DirectInput keyboard,
which polls device state rather than the window message queue, so `SendKeys`
and `PostMessage` are invisible to it — and driver-level injection still needs
the session to be unlocked and Dolphin focused. On a locked machine there is no
foreground window to give it to. Anything needing a button press has to be
tested by a human, or reached some other way. See D48.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from bleck.backends.disc import DiscError, find_tool  # noqa: E402
from bleck.mods import registry  # noqa: E402
from bleck import platforms  # noqa: E402

#: Unused TRK interrupt vector table. Free, and at the same address in every
#: region -- which is why `spm-loaders` reserves this range too. The Gecko
#: loader parks a memcpy at 0x80004000, well below it.
DEFAULT_PROBE = 0x80005000

#: `seqWork` (eu0). `seq` at +0x00, `stage` at +0x04.
SEQ_WORK = 0x80512360

#: `evtGetWork()`'s return, a fixed global. `gw[]` starts at +0x04.
EVT_WORK = 0x8050C990

SEQUENCES = ["LOGO", "TITLE", "GAME", "MAPCHANGE", "GAMEOVER", "LOAD"]


@dataclass(frozen=True)
class Snapshot:
    """One reading of the running game."""

    sequence: int
    stage: int
    words: list[int] = field(default_factory=list)
    gw: dict[int, int] = field(default_factory=dict)

    @property
    def sequence_name(self) -> str:
        return SEQUENCES[self.sequence] if 0 <= self.sequence < 6 else str(self.sequence)

    def render(self) -> str:
        parts = [f"seq={self.sequence_name}({self.sequence}) stage={self.stage}"]
        if self.gw:
            parts.append(" ".join(f"gw[{n}]={v}" for n, v in sorted(self.gw.items())))
        if self.words:
            shown = " ".join(f"{w:08X}" for w in self.words)
            parts.append(f"probe: {shown}")
        return "  ".join(parts)


def _signed(value: int) -> int:
    return value - 0x100000000 if value >= 0x80000000 else value


class Session:
    """A booted Dolphin, and the memory reads that make it observable."""

    def __init__(self, image: Path, dolphin: str) -> None:
        self.image = image
        self.dolphin = dolphin
        self.process: subprocess.Popen | None = None

    def __enter__(self) -> Session:
        # `-b` boots straight into the game rather than opening the game list.
        self.process = subprocess.Popen([self.dolphin, "-b", "-e", str(self.image)])
        return self

    def __exit__(self, *_exc: object) -> None:
        import dolphin_memory_engine as dme  # noqa: PLC0415

        if dme.is_hooked():
            dme.un_hook()
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()

    def read(self, probe: int, words: int, watch_gw: list[int]) -> Snapshot | None:
        import dolphin_memory_engine as dme  # noqa: PLC0415

        if not dme.is_hooked():
            dme.hook()
            return None
        try:
            return Snapshot(
                sequence=_signed(dme.read_word(SEQ_WORK)),
                stage=_signed(dme.read_word(SEQ_WORK + 4)),
                words=[dme.read_word(probe + 4 * i) for i in range(words)],
                gw={n: dme.read_word(EVT_WORK + 4 + 4 * n) for n in watch_gw},
            )
        except RuntimeError:
            # The process is up but the emulated memory is not mapped yet.
            return None


def build(mod: str, image: Path) -> None:
    result = subprocess.run(
        ["uv", "run", "bleck", "mod", "build", mod, str(image), "--force"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    print((result.stdout + result.stderr).strip())
    if result.returncode != 0:
        raise SystemExit(f"building {mod} failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mod", help="mod to build and boot")
    parser.add_argument(
        "--seconds", type=int, default=180, help="how long to watch (default: 180)"
    )
    parser.add_argument(
        "--probe",
        type=lambda v: int(v, 0),
        default=DEFAULT_PROBE,
        help="address of the mod's report block",
    )
    parser.add_argument(
        "--words", type=int, default=8, help="how many words of it to show"
    )
    parser.add_argument(
        "--watch-gw",
        type=int,
        nargs="*",
        default=[],
        metavar="N",
        help="also read these evt global work slots",
    )
    parser.add_argument(
        "--no-build", action="store_true", help="boot the existing image as-is"
    )
    args = parser.parse_args()

    image = registry.build_root() / f"{args.mod}.wbfs"
    if not args.no_build:
        build(args.mod, image)
    if not image.exists():
        raise SystemExit(f"no image at {image}")

    try:
        dolphin = find_tool(platforms.DOLPHIN)
    except DiscError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"booting {image.name} ...")
    seen = ""
    with Session(image, dolphin) as session:
        start = time.time()
        while time.time() - start < args.seconds:
            time.sleep(3)
            snapshot = session.read(args.probe, args.words, args.watch_gw)
            if snapshot is None:
                continue
            line = snapshot.render()
            if line != seen:
                print(f"[t+{int(time.time() - start):>3}s] {line}")
                seen = line
    print("dolphin stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
