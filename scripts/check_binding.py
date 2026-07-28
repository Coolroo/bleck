"""Read back the address `elf2rel` actually bound a game function to.

A `USER_FUNC` target is a raw address filled in at link time; bound wrongly, the
script still runs and silently does nothing (D70). This finds the script array
in the running game and reads the word.

    uv run python scripts/check_binding.py warp-combo warp_home 4 0x8010D0F0

Memory reads only, so it works on a locked machine.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from ingame import Session, find_bytes, running_dolphins  # noqa: E402

from bleck import platforms  # noqa: E402
from bleck.backends.disc import DiscError, find_tool  # noqa: E402
from bleck.mods import registry  # noqa: E402


@dataclass(frozen=True)
class Anchor:
    """A distinctive run of literal words from a script, used to find it in RAM.

    Only literals are usable: `&symbol` entries are exactly what is unknown.
    """

    pattern: bytes
    offset_to_target: int

    @property
    def hex(self) -> str:
        return self.pattern.hex()


def anchor_for(source: str, script: str, index: int) -> Anchor:
    """Build a search pattern from the generated C, up to the word in question."""
    body = re.search(
        rf"const s32 bleck_script_{re.escape(script)}\[\] = \{{(.*?)\}};",
        source,
        re.DOTALL,
    )
    if not body:
        raise SystemExit(f"no script named {script!r} in the generated C")

    words = [w.strip() for w in body.group(1).replace("\n", " ").split(",") if w.strip()]
    if index >= len(words):
        raise SystemExit(f"{script} has {len(words)} words; index {index} is past the end")

    literals = []
    for word in words[:index]:
        if not re.fullmatch(r"-?\d+", word):
            raise SystemExit(
                f"word {len(literals)} of {script} is {word!r}, not a literal.\n"
                "  The search pattern can only use words whose value is known "
                "ahead of time; pick a target index with literals before it."
            )
        literals.append(int(word))
    if not literals:
        raise SystemExit("need at least one literal word before the target")
    return Anchor(
        pattern=b"".join(struct.pack(">i", value) for value in literals),
        offset_to_target=len(literals) * 4,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mod")
    parser.add_argument("script", help="script name as written in the source")
    parser.add_argument("index", type=int, help="word index holding the address")
    parser.add_argument("expected", type=lambda v: int(v, 0), help="what it should be")
    parser.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()

    if running_dolphins():
        raise SystemExit(
            "close Dolphin first -- the reader may attach to the wrong instance"
        )

    generated = registry.build_root() / ".code" / args.mod / "mod.c"
    if not generated.exists():
        raise SystemExit(f"no generated C at {generated}; build the mod first")
    anchor = anchor_for(generated.read_text(encoding="utf-8"), args.script, args.index)
    print(f"searching for {anchor.hex}  (+{anchor.offset_to_target} is the target)")

    image = registry.build_root() / f"{args.mod}.wbfs"
    try:
        dolphin = find_tool(platforms.DOLPHIN)
    except DiscError as exc:
        raise SystemExit(str(exc)) from exc

    import dolphin_memory_engine as dme

    with Session(image, dolphin, unlimited=True) as session:
        start = time.time()
        while time.time() - start < args.seconds:
            time.sleep(3)
            if session.exited:
                raise SystemExit("dolphin exited on its own")
            if not dme.is_hooked():
                dme.hook()
                continue
            hits = find_bytes(dme, anchor.pattern)
            if not hits:
                continue
            print(f"found {len(hits)} copy(ies) at {[hex(a) for a in hits]}")
            for at in hits:
                bound = dme.read_word(at + anchor.offset_to_target)
                verdict = "MATCHES" if bound == args.expected else "*** WRONG ***"
                print(f"  0x{at:08X} -> bound 0x{bound:08X}  {verdict}")
            return 0
    print("never found the script in memory (did the module load?)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
