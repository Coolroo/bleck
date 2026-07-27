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

    @property
    def exited(self) -> bool:
        """Whether Dolphin has quit without being asked to."""
        return self.process is not None and self.process.poll() is not None

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


#: The Wii's two RAM regions. A file the game loaded could be in either.
REGIONS = [("MEM1", 0x80000000, 0x01800000), ("MEM2", 0x90000000, 0x04000000)]

#: Big enough that the per-read overhead does not dominate, small enough that a
#: failed read loses little.
CHUNK = 1 << 20


def find_bytes(dme, pattern: bytes) -> list[int]:  # pylint: disable=container-return
    """Every address in the game's RAM holding `pattern`.

    Used to answer "which copy of a file did the game actually load?" without
    knowing anything about how it loads them: mark two candidates differently,
    then look for the marks. See D13.
    """
    hits: list[int] = []
    overlap = len(pattern) - 1
    for _name, base, size in REGIONS:
        offset = 0
        while offset < size:
            try:
                block = dme.read_bytes(base + offset, min(CHUNK, size - offset))
            except RuntimeError:
                offset += CHUNK
                continue
            start = 0
            while True:
                at = block.find(pattern, start)
                if at < 0:
                    break
                hits.append(base + offset + at)
                start = at + 1
            # Step back so a match straddling a chunk boundary is not missed.
            offset += CHUNK - overlap
    return hits


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
    parser.add_argument(
        "--log", help="where to write the full transcript (default: work/build/ingame.log)"
    )
    parser.add_argument(
        "--find",
        nargs="*",
        default=[],
        metavar="HEX",
        help="byte patterns to search RAM for, e.g. 0006a1a1c428c000",
    )
    parser.add_argument(
        "--find-at",
        type=int,
        default=80,
        metavar="SECONDS",
        help="when to run the search (default: 80, i.e. once the game is up)",
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

    # Everything is written here as well as printed. A run costs two to three
    # minutes, and reading the console output through `tail` has already thrown
    # away a probe word that then needed the whole run repeating. The log is
    # always complete, so re-reading is free.
    log_path = Path(args.log) if args.log else registry.build_root() / "ingame.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")

    def say(line: str) -> None:
        print(line)
        log.write(line + "\n")
        log.flush()

    say(f"booting {image.name} ...   (full log: {log_path})")
    seen = ""
    quiet = 0
    searched = False
    with Session(image, dolphin) as session:
        start = time.time()
        while time.time() - start < args.seconds:
            time.sleep(3)
            elapsed = int(time.time() - start)

            # Dolphin exiting on its own is a result, not an inconvenience: it
            # usually means the game crashed. Silently running out the clock
            # here once made a hard crash look like a mod that did nothing.
            if session.exited:
                say(f"[t+{elapsed:>3}s] *** dolphin exited on its own ***")
                break

            if args.find and elapsed >= args.find_at and not searched:
                searched = True
                import dolphin_memory_engine as dme  # noqa: PLC0415

                for text_pattern in args.find:
                    pattern = bytes.fromhex(text_pattern)
                    hits = find_bytes(dme, pattern)
                    where = ", ".join(f"0x{a:08X}" for a in hits[:4]) or "not found"
                    say(f"[t+{elapsed:>3}s] {text_pattern}: {len(hits)} hit(s)  {where}")

            snapshot = session.read(args.probe, args.words, args.watch_gw)
            if snapshot is None:
                continue
            line = snapshot.render()
            # A heartbeat, because "no output" otherwise means both "nothing
            # changed" and "the game froze" -- and telling those apart is
            # usually the whole question.
            if line != seen:
                say(f"[t+{elapsed:>3}s] {line}")
                seen = line
                quiet = elapsed
            elif elapsed - quiet >= 30:
                say(f"[t+{elapsed:>3}s] ... unchanged for {elapsed - quiet}s")
                quiet = elapsed
    say("dolphin stopped")
    log.close()
    print(f"\nfull log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
