"""`sound` commands: the game's music, out as WAV.

`files/sound/` holds **135 BRSTM streams**, 162 MB of DSP-ADPCM. This decodes
them to something every operating system plays, and writes `sounds.json` at the
export root — the same contract shape as `texture`, `model` and `effect`. The
WAVs themselves go under `sounds/`, mirroring the disc; see
`bleck/common/exportlayout.py`.

⛔ **No audio ships with `bleck`.** These come off whatever disc the user
extracted; `work/` is git-ignored and stays that way.

⚠️ **WAV is uncompressed**, so 162 MB of ADPCM becomes **566 MB** of 16-bit
PCM. That is the whole disc's music and is the right default to export.

⛔ **`--seconds` is for a quick look, not for browsing.** 103 of the 135 tracks
run longer than 20 seconds and every one of them loops, so a cap truncates most
of the library mid-phrase. It exists because an earlier export ran at double
the rate (D232) and was heading for 1.5 GB; that is no longer the case.

⛔ **The 15 MB `BRSAR` is not touched.** It holds the sound *effects* in a
nested archive format, and guessing at it would produce noise that plays.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from bleck.cli.types import AddCommand
from bleck.common import exportlayout
from bleck.common.errors import UserError
from bleck.formats import brstm, wav
from bleck.mods import registry

CATEGORY = "inspection"

#: Written at the export root. Dimentio reads this, not the directory listing.
MANIFEST = "sounds.json"

#: The subtree the WAVs go under, keeping them clear of the other kinds.
KIND = "sounds"

#: Where the streams live on the disc.
SOUND_DIR = "files/sound"


@dataclass(frozen=True)
class Found:
    """One stream, and where on the disc it came from."""

    disc_path: str
    stream: brstm.Stream

    @property
    def name(self) -> str:
        return Path(self.disc_path).stem

    @property
    def relative(self) -> str:
        """Where the WAV lands, relative to the export root."""
        directory = PurePosixPath(self.disc_path).parent.as_posix()
        return exportlayout.place(KIND, directory, f"{self.name}.wav")


def _base() -> Path:
    base = registry.base_root()
    if not base.is_dir():
        raise UserError(
            f"no extracted base at {base}\n"
            "  run `bleck extract <disc>` first, or set BLECK_BASE_DIR"
        )
    return base


def _walk(base: Path, pattern: str, seconds: float, decode: bool = True) -> list:
    # pylint: disable=container-return
    """Every stream that reads, capped at `seconds` when asked.

    ⚠️ `decode=False` reads headers only. Decoding all 135 tracks takes about
    two minutes in Python, and listing them needs none of it.
    """
    found: list[Found] = []
    directory = base / SOUND_DIR
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if pattern and pattern not in relative:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not brstm.is_brstm(data):
            continue
        try:
            stream = brstm.read(data) if decode else brstm.header(data)
        except brstm.StreamError:
            # ⚠️ Skipped, never guessed at. A stream this cannot read would
            # otherwise export as something that plays and is wrong.
            continue
        found.append(Found(relative, _capped(stream, seconds)))
    return found


def _capped(stream: brstm.Stream, seconds: float) -> brstm.Stream:
    if seconds <= 0 or stream.seconds <= seconds:
        return stream
    keep = int(seconds * stream.playback_rate)
    return brstm.Stream(
        rate=stream.rate,
        channels=stream.channels,
        samples=keep,
        loop_start=stream.loop_start,
        loops=stream.loops,
        pcm=[channel[:keep] for channel in stream.pcm],
    )


def cmd_list(args: argparse.Namespace) -> int:
    found = _walk(_base(), args.search or "", 0.0, decode=False)
    if not found:
        print("no streams matched")
        return 0
    total = 0.0
    for entry in found[: args.limit]:
        print(f"{entry.name:<40} {entry.stream.describe()}")
    for entry in found:
        total += entry.stream.seconds
    if len(found) > args.limit:
        print(f"... and {len(found) - args.limit} more (raise --limit)")
    print(f"\n{len(found)} stream(s), {total / 60:.1f} minutes in total")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    out = Path(args.out)
    tree = exportlayout.Tree(out)

    found = _walk(_base(), args.search or "", args.seconds)
    entries: list[dict] = []
    written = 0
    for entry in found:
        try:
            data = wav.write(entry.stream.playback_rate, entry.stream.pcm)
        except ValueError:
            continue
        tree.write(entry.relative, data)
        written += len(data)
        entries.append(
            {
                "name": entry.name,
                "file": entry.relative,
                "source": entry.disc_path,
                "rate": entry.stream.playback_rate,
                "header_rate": entry.stream.rate,
                "channels": entry.stream.channels,
                "seconds": round(entry.stream.seconds, 3),
                "loops": entry.stream.loops,
                "loop_start": entry.stream.loop_start,
                "capped": bool(args.seconds),
            }
        )

    (out / MANIFEST).write_text(
        json.dumps({"schema": 1, "sounds": entries}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} WAV(s) under {out / KIND} and {MANIFEST} to {out}")
    print(f"  {written / 1e6:.0f} MB of 16-bit PCM")
    if args.seconds:
        print(f"  ! each track capped at {args.seconds:g}s, and the manifest says so")
    return 0


def register(add: AddCommand) -> None:
    parser = add("sound", help="the game's music")
    sub = parser.add_subparsers(dest="sound_command", required=True)

    listing = sub.add_parser("list", help="every stream and what it is")
    listing.add_argument("--search", help="only paths containing this")
    listing.add_argument("--limit", type=int, default=40)
    listing.set_defaults(func=cmd_list)

    export = sub.add_parser("export", help="write the music out as WAV")
    export.add_argument("--out", default="work/export", help="where to write them")
    export.add_argument("--search", help="only paths containing this")
    export.add_argument(
        "--seconds",
        type=float,
        default=0.0,
        help="cap each track for a quick look; the full 566 MB is the default",
    )
    export.set_defaults(func=cmd_export)
