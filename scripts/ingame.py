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

Button presses
--------------
`--press a b 1 2` sends keystrokes to Dolphin once gameplay starts, so a
button-triggered feature can be checked without a person tapping keys on cue.

⚠️ **Attended only.** D48 measured `SendKeys` and `PostMessage`, which post to
a message queue Dolphin never reads — that finding stands. `scripts/keys.py`
uses `SendInput`, which injects below DirectInput's polling and does work, but
still needs an unlocked session with Dolphin in the foreground. On a locked
machine there is no foreground window to give it to, so the unattended limit in
D48 is unchanged.

⚠️ It lives in `scripts/`, **not** in the `bleck` package, and must stay there.
Synthesising input is a reasonable thing for a test harness to do on the
machine of the person running it, and not something a modding toolkit should
ship to other people's computers. `tests/test_boundaries.py` enforces the
split.
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

import keys  # noqa: E402  -- scripts/, deliberately not part of the bleck package

#: Unused TRK interrupt vector table. Free, and at the same address in every
#: region -- which is why `spm-loaders` reserves this range too. The Gecko
#: loader parks a memcpy at 0x80004000, well below it.
DEFAULT_PROBE = 0x80005000

#: `seqWork` (eu0). `seq` at +0x00, `stage` at +0x04.
SEQ_WORK = 0x80512360

#: `evtGetWork()`'s return, a fixed global. `gw[]` starts at +0x04.
EVT_WORK = 0x8050C990

SEQUENCES = ["LOGO", "TITLE", "GAME", "MAPCHANGE", "GAMEOVER", "LOAD"]
SEQ_GAME = 2


@dataclass(frozen=True)
class Snapshot:
    """One reading of the running game."""

    sequence: int
    stage: int
    destination: str = ""
    words: list[int] = field(default_factory=list)
    gw: dict[int, int] = field(default_factory=dict)

    @property
    def sequence_name(self) -> str:
        return SEQUENCES[self.sequence] if 0 <= self.sequence < 6 else str(self.sequence)

    def render(self) -> str:
        parts = [f"seq={self.sequence_name}({self.sequence}) stage={self.stage}"]
        if self.destination:
            parts.append(f"map={self.destination}")
        if self.gw:
            parts.append(" ".join(f"gw[{n}]={v}" for n, v in sorted(self.gw.items())))
        if self.words:
            shown = " ".join(f"{w:08X}" for w in self.words)
            parts.append(f"probe: {shown}")
        return "  ".join(parts)


@dataclass(frozen=True)
class ReadResult:
    """One poll of the running game: what was read, or why nothing was.

    The `problem` half exists because silence used to mean four different
    things — no Dolphin, wrong Dolphin, game not up yet, game hung — and the
    run printed the same nothing for all of them. A whole session was lost to
    that. Reporting *why* a read failed turns a dead end into a diagnosis.
    """

    snapshot: Snapshot | None = None
    problem: str = ""

    @property
    def ok(self) -> bool:
        return self.snapshot is not None


def _signed(value: int) -> int:
    return value - 0x100000000 if value >= 0x80000000 else value


class Session:
    """A booted Dolphin, and the memory reads that make it observable."""

    def __init__(
        self,
        image: Path,
        dolphin: str,
        unlimited: bool = False,
        state: Path | None = None,
    ) -> None:
        self.image = image
        self.dolphin = dolphin
        self.unlimited = unlimited
        self.state = state
        self.process: subprocess.Popen | None = None

    def command(self) -> list[str]:
        # `-b` boots straight into the game rather than opening the game list.
        args = [self.dolphin, "-b", "-e", str(self.image)]
        if self.unlimited:
            # 0 means "no limit". Gameplay is reached ~45s in at 100% speed, and
            # almost all of that is logos nobody is watching.
            args += ["-C", "Dolphin.Core.EmulationSpeed=0"]
        if self.state is not None:
            # Skips the boot entirely, and carries a save with it -- which is
            # what stops Mario being invisible for want of a profile.
            args += ["-s", str(self.state)]
        return args

    def __enter__(self) -> Session:
        self.process = subprocess.Popen(self.command())
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

    @staticmethod
    def _destination(dme) -> str:
        """Where the game says it is going, from `seqWork.p0`.

        This is the same field the map-hook machinery watches, and reading it
        here is what turns "the game is in SEQ_GAME" into "the game is in
        Lineland". Without it, a boot map that quietly did nothing and one that
        worked produce identical output — both just say `seq=GAME`.

        `p0` is only meaningful during a map change; the game leaves the old
        pointer in place afterwards, which is useful rather than stale, because
        the last destination *is* where you are.
        """
        pointer = dme.read_word(SEQ_WORK + 8)
        if not 0x80000000 <= pointer < 0x94000000:
            return ""
        try:
            raw = dme.read_bytes(pointer, 16)
        except RuntimeError:
            return ""
        end = raw.find(b"\0")
        name = raw[: end if end >= 0 else 16]
        # Map names are lowercase ASCII with digits and underscores. Anything
        # else means the pointer is not pointing at a name right now.
        text = name.decode("ascii", "replace")
        return text if text and all(c.isalnum() or c == "_" for c in text) else ""

    def read(self, probe: int, words: int, watch_gw: list[int]) -> ReadResult:
        import dolphin_memory_engine as dme  # noqa: PLC0415

        if not dme.is_hooked():
            dme.hook()
            if not dme.is_hooked():
                return ReadResult(
                    problem="not attached to any Dolphin process yet "
                    "(is one running? is another instance in the way?)"
                )
            return ReadResult(problem="attached; waiting for emulated memory")
        try:
            return ReadResult(
                snapshot=Snapshot(
                    sequence=_signed(dme.read_word(SEQ_WORK)),
                    stage=_signed(dme.read_word(SEQ_WORK + 4)),
                    destination=self._destination(dme),
                    words=[dme.read_word(probe + 4 * i) for i in range(words)],
                    gw={n: dme.read_word(EVT_WORK + 4 + 4 * n) for n in watch_gw},
                )
            )
        except RuntimeError as exc:
            # Attached to the process, but the emulated address space is not
            # readable. Normal for a second or two after launch; if it persists,
            # the game never started -- which is a *result*, and used to be
            # indistinguishable from the tool failing to attach at all.
            return ReadResult(problem=f"attached, but memory is unreadable: {exc}")


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


def running_dolphins() -> list[int]:
    """PIDs of Dolphin processes already running.

    ⚠️ An existing instance breaks a run in a way that reads as the mod being
    broken. `dolphin-memory-engine` attaches to *a* Dolphin process, not to the
    one this script launched -- and if it picks an idle one, with no game
    emulating, `hook()` simply fails and every read reports nothing.

    An idle Dolphin left over from an earlier session cost two rounds of
    debugging exactly this way. `docs/handoff.md` has warned about it for a
    while; a warning nobody is shown at the moment it matters is not a control.
    """
    try:
        found = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []  # not Windows, or no tasklist -- not worth failing over
    pids = []
    for line in found.stdout.splitlines():
        parts = [field.strip('"') for field in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


def build(mod: str, image: Path, boot_map: str = "") -> None:
    command = ["uv", "run", "bleck", "mod", "build", mod, str(image), "--force"]
    if boot_map:
        # The disc drives itself to the map, so the run stays unattended --
        # which is the only kind of run this script can do (D48).
        command += ["--map", boot_map]
    result = subprocess.run(
        command,
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
        "--map",
        metavar="NAME|ID",
        default="",
        help="start the game at this map instead of the attract demo",
    )
    parser.add_argument(
        "--slow",
        action="store_true",
        help="run at normal speed; the default is unlimited, which boots faster",
    )
    parser.add_argument(
        "--state", help="a Dolphin save state to load instead of booting cold"
    )
    parser.add_argument(
        "--allow-other-dolphins",
        action="store_true",
        help="start even if Dolphin is already running (the reader may attach "
        "to the wrong one, and report nothing at all)",
    )
    parser.add_argument(
        "--press",
        nargs="*",
        default=[],
        metavar="BUTTON",
        help="press these buttons once gameplay starts, one at a time "
        "(Windows only, needs an unlocked session -- see scripts/keys.py)",
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

    if args.map and args.no_build:
        raise SystemExit("--map has to be built in; drop --no-build")

    image = registry.build_root() / f"{args.mod}.wbfs"
    if not args.no_build:
        build(args.mod, image, args.map)
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

    existing = running_dolphins()
    if existing:
        listed = ", ".join(str(pid) for pid in existing)
        say(f"*** {len(existing)} Dolphin process(es) already running: {listed}")
        say("    The memory reader attaches to *a* Dolphin, not necessarily the")
        say("    one this launches. If one of those is idle, every read fails and")
        say("    the run reports nothing. Close them:")
        say(f"      Stop-Process -Id {existing[0]} -Force")
        if not args.allow_other_dolphins:
            raise SystemExit("refusing to start; pass --allow-other-dolphins to override")

    say(f"booting {image.name} ...   (full log: {log_path})")
    seen = ""
    quiet = 0
    searched = False
    pressed = False
    with Session(
        image,
        dolphin,
        unlimited=not args.slow,
        state=Path(args.state) if args.state else None,
    ) as session:
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

            result = session.read(args.probe, args.words, args.watch_gw)
            if not result.ok:
                # Say why, and keep saying it if it persists. A run that prints
                # nothing for three minutes teaches nothing; one that says
                # "attached, but memory is unreadable" for three minutes says
                # the game never started.
                if result.problem != seen:
                    say(f"[t+{elapsed:>3}s] {result.problem}")
                    seen = result.problem
                    quiet = elapsed
                elif elapsed - quiet >= 15:
                    say(f"[t+{elapsed:>3}s] ... still: {result.problem}")
                    quiet = elapsed
                continue
            # Buttons are pressed once gameplay is actually up, not on a timer:
            # the game reaching SEQ_GAME is the only reliable signal that it is
            # listening, and a timer would drift with load times.
            if args.press and not pressed and result.snapshot.sequence == SEQ_GAME:
                pressed = True
                say(f"[t+{elapsed:>3}s] ready to press {' '.join(args.press)}")
                # Politely first; Windows usually refuses a background process,
                # so fall back to waiting for a human to click the window. Keys
                # are never sent to an unfocused Dolphin -- they would land in
                # whatever *is* focused, which is nobody's idea of a test.
                if not keys.focus(session.process.pid) and not keys.is_foreground(
                    session.process.pid
                ):
                    say("    >>> CLICK THE DOLPHIN WINDOW NOW (waiting up to 30s)")
                    if not keys.wait_until_foreground(session.process.pid, 30):
                        say("    Dolphin never came to the front; sent nothing")
                        continue
                for button in args.press:
                    outcome = keys.press(button)
                    say(f"    {button}: {'sent' if outcome.sent else outcome.problem}")

            line = result.snapshot.render()
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
