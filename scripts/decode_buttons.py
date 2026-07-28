"""Turn `button-probe`'s report block into a verdict on the mask table.

Compares the values `mods/button-probe` recorded from the real controller
against `BUTTON_MASKS` in `bleck/common/config.py`, and prints corrections.

    uv run python scripts/decode_buttons.py --press a b 1 2 plus minus \\
        --ring 0800 0400 0200 0100 0010 1000

`--press` is the press order, `--ring` the recorded values in the same order.

⚠️ A press *missing* from the ring is not a wrong mask — it usually means the
press fell between two frames the probe saw. Re-run rather than guessing.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from bleck.common.config import BUTTON_MASKS  # noqa: E402


@dataclass(frozen=True)
class Reading:
    """One button, as pressed and as recorded."""

    button: str
    observed: int

    @property
    def expected(self) -> int:
        return BUTTON_MASKS.get(self.button, 0)

    @property
    def is_known(self) -> bool:
        return self.button in BUTTON_MASKS

    @property
    def agrees(self) -> bool:
        return self.is_known and self.observed == self.expected

    @property
    def is_single_bit(self) -> bool:
        return bool(self.observed) and not (self.observed & (self.observed - 1))

    def describe(self) -> str:
        if not self.is_known:
            return f"  ?  {self.button:<8} 0x{self.observed:04X}  not in the table"
        mark = "ok " if self.agrees else "!! "
        note = "" if self.agrees else f"  table says 0x{self.expected:04X}"
        extra = "" if self.is_single_bit else "  (more than one bit -- combo?)"
        return f"  {mark}{self.button:<8} 0x{self.observed:04X}{note}{extra}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--press", nargs="+", required=True, metavar="NAME", help="press order"
    )
    parser.add_argument(
        "--ring",
        nargs="+",
        required=True,
        metavar="HEX",
        help="values the probe recorded, same order",
    )
    args = parser.parse_args()

    if len(args.press) != len(args.ring):
        raise SystemExit(
            f"{len(args.press)} buttons but {len(args.ring)} recorded values.\n"
            "  A missing value usually means a press was too short to be seen, "
            "or two buttons overlapped. Re-run rather than aligning by hand."
        )

    readings = [
        Reading(button=name.lower(), observed=int(value, 16))
        for name, value in zip(args.press, args.ring, strict=True)
    ]

    print("button    observed")
    for reading in readings:
        print(reading.describe())

    wrong = [r for r in readings if r.is_known and not r.agrees]
    unknown = [r for r in readings if not r.is_known]
    duplicated = len({r.observed for r in readings}) != len(readings)

    print()
    if duplicated:
        print("!! two buttons recorded the same value -- the presses overlapped")
        return 1
    if not wrong and not unknown:
        print(f"all {len(readings)} masks confirmed against the running game")
        print("BUTTON_MASKS can drop its unverified marker for these entries")
        return 0

    print("corrections for bleck/common/config.py:")
    for reading in wrong + unknown:
        print(f'    "{reading.button}": 0x{reading.observed:04X},')
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
