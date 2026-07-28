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

import keys  # noqa: E402  -- scripts/, deliberately not part of the bleck package

from bleck import platforms  # noqa: E402
from bleck.backends.disc import DiscError, find_tool  # noqa: E402
from bleck.mods import registry  # noqa: E402

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

#: `seq_mapchange_wp` (eu0) -- a pointer to the map-change sequence's work.
#: Unlike `seqWork.p0` this survives the transition, so it says which map the
#: game is *in* rather than which one it is on its way to. See D75.
SEQ_MAPCHANGE_WP = 0x805AE0A8

#: `SeqMapChangeWork.mapName`, from `spm/seq_mapchange.h`.
SEQ_MAPCHANGE_MAP_NAME = 0x20

#: `npcdrv_wp` (eu0) -- a pointer to `NPCWork`, the live NPC list.
#:
#: ⚠️ This exists so "how many enemies spawned" stops being a question answered
#: by looking at a screen. Every placement conclusion so far has rested on
#: someone reporting what they saw, and D76 is what that costs when the thing
#: doing the reporting is wrong.
NPCDRV_WP = 0x805AE188

#: `NPCWork`, from `spm/npcdrv.h`: `num` at 0x04, `entries` at 0x08.
NPC_WORK_NUM = 0x04
NPC_WORK_ENTRIES = 0x08

#: `NPCEntry`: `setupFileIndex` at 0x04 (**1-based**, 0 when not from a setup
#: file), `flag8` at 0x08 whose bit 0 is "active", `name` at 0x24.
NPC_ENTRY_SIZE = 0x748
NPC_SETUP_INDEX = 0x04
NPC_FLAGS = 0x08
NPC_NAME = 0x24
NPC_ACTIVE = 0x1

#: A map holds nowhere near this many; the cap only stops a garbage `num` from
#: turning into a million reads.
NPC_SCAN_LIMIT = 256


@dataclass(frozen=True)
class Snapshot:
    """One reading of the running game."""

    sequence: int
    stage: int
    destination: str = ""
    npcs: str = ""
    words: list[int] = field(default_factory=list)
    gw: dict[int, int] = field(default_factory=dict)

    @property
    def sequence_name(self) -> str:
        return SEQUENCES[self.sequence] if 0 <= self.sequence < 6 else str(self.sequence)

    def render(self) -> str:
        parts = [f"seq={self.sequence_name}({self.sequence}) stage={self.stage}"]
        if self.destination:
            parts.append(f"map={self.destination}")
        if self.npcs:
            parts.append(self.npcs)
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
        import dolphin_memory_engine as dme

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
        """Which map the game is in, from `seq_mapchange_wp->mapName`.

        ⚠️ This used to read `seqWork.p0`, and that was wrong in a way that
        produced four wrong conclusions (D75). `p0` is a *parameter to the
        map-change sequence* and only means anything while one is running.
        Between changes it holds whatever was left there, so the field went
        blank and a run that had changed maps looked exactly like one that had
        not. D70, D73 and D74 all rest on that mistake.

        `SeqMapChangeWork` is the map-change sequence's own work struct and
        keeps `mapName` after the change completes, so this answers "where is
        the game" rather than "is a transition in flight right now".

        Layout from `spm/seq_mapchange.h`: `areaName[32]` at 0x00,
        `mapName[32]` at 0x20, `beroName[32]` (the door) at 0x40.
        """
        try:
            work = dme.read_word(SEQ_MAPCHANGE_WP)
            if not 0x80000000 <= work < 0x94000000:
                return ""
            raw = dme.read_bytes(work + SEQ_MAPCHANGE_MAP_NAME, 32)
        except RuntimeError:
            return ""
        end = raw.find(b"\0")
        text = raw[: end if end >= 0 else 32].decode("ascii", "replace")
        # Map names are lowercase ASCII, digits and underscores. Anything else
        # means the struct is not populated yet.
        return text if text and all(c.isalnum() or c == "_" for c in text) else ""

    @staticmethod
    def _npcs(dme) -> str:
        """The live NPC list, as `slot=name` for anything from a setup file.

        `setupFileIndex` is **1-based**, so a `setup` slot 2 shows here as 3.
        It is printed as the slot the manifest names, minus one, because that
        is the number someone is actually holding when they ask why an enemy
        did not appear.
        """
        # ⚠️ Every branch says *something*. An empty string here would make "no
        # enemies spawned" and "the list could not be read" identical, which is
        # precisely the confusion that produced D76 -- and this field exists to
        # answer a question of exactly that shape.
        try:
            work = dme.read_word(NPCDRV_WP)
            if not 0x80000000 <= work < 0x94000000:
                return f"npcs=? (npcdrv_wp is 0x{work:08X})"
            count = _signed(dme.read_word(work + NPC_WORK_NUM))
            entries = dme.read_word(work + NPC_WORK_ENTRIES)
        except RuntimeError as exc:
            return f"npcs=? ({exc})"
        if not 0x80000000 <= entries < 0x94000000:
            return f"npcs=? (entries is 0x{entries:08X})"
        # ⚠️ `num` is the array's *capacity*, not how many are alive. It reads 80
        # from the first frame of the logo onward, long before any map exists.
        # Liveness is `flag8 & 1` per entry, so every slot has to be walked and
        # filtered rather than trusting a count.
        if not 0 < count <= NPC_SCAN_LIMIT:
            return f"npcs=? (num is {count}, outside anything plausible)"
        try:
            block = dme.read_bytes(entries, count * NPC_ENTRY_SIZE)
        except RuntimeError as exc:
            return f"npcs=? ({exc})"

        found: list[str] = []
        for index in range(count):
            at = index * NPC_ENTRY_SIZE
            flags = int.from_bytes(block[at + NPC_FLAGS : at + NPC_FLAGS + 4], "big")
            if not flags & NPC_ACTIVE:
                continue
            setup_index = int.from_bytes(
                block[at + NPC_SETUP_INDEX : at + NPC_SETUP_INDEX + 4], "big"
            )
            raw = block[at + NPC_NAME : at + NPC_NAME + 32]
            end = raw.find(b"\0")
            name = raw[: end if end >= 0 else 32].decode("ascii", "replace")
            # `setupFileIndex` is 1-based; the manifest's slots are 0-based, and
            # the slot number is what someone is holding when they ask why an
            # enemy did not appear.
            where = f"slot{setup_index - 1}" if setup_index else "-"
            found.append(f"{where}:{name}")
        return f"npcs[{len(found)}] " + " ".join(found) if found else "npcs[0]"

    def read(
        self,
        probe: int,
        words: int,
        watch_gw: list[int],
        watch_npcs: bool = False,
    ) -> ReadResult:
        import dolphin_memory_engine as dme

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
                    npcs=self._npcs(dme) if watch_npcs else "",
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
        "--npcs",
        action="store_true",
        help="list live NPCs and which setup slot each came from -- so "
        "\"how many enemies spawned\" is measured rather than eyeballed",
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
        help="press these buttons once gameplay starts, one at a time; "
        "join with + to hold together, e.g. 1+2 "
        "(Windows only, needs an unlocked session -- see scripts/keys.py)",
    )
    parser.add_argument(
        "--press-at",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="wait until this many seconds elapsed before pressing, instead of "
        "pressing the moment gameplay starts. Use it when a boot map means the "
        "first gameplay frame is not the map you want to press in",
    )
    parser.add_argument(
        "--press-gap",
        type=float,
        default=0.9,
        metavar="SECONDS",
        help="pause between presses. Raise it above the 3s poll interval to "
        "see the state each press lands in, rather than only the last one",
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
                import dolphin_memory_engine as dme

                for text_pattern in args.find:
                    pattern = bytes.fromhex(text_pattern)
                    hits = find_bytes(dme, pattern)
                    where = ", ".join(f"0x{a:08X}" for a in hits[:4]) or "not found"
                    say(f"[t+{elapsed:>3}s] {text_pattern}: {len(hits)} hit(s)  {where}")

            result = session.read(args.probe, args.words, args.watch_gw, args.npcs)
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
            if (
                args.press
                and not pressed
                and result.snapshot.sequence == SEQ_GAME
                and elapsed >= args.press_at
            ):
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
                    outcome = keys.press(button, gap=args.press_gap)
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
