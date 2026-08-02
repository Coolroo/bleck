"""Effect animation curves, and the rotation maths that consumes them.

Split from `effdata` for the reason `effgeom` was: none of it needs the node
walk, and `effdata` was the repo's first module to reach pylint's 1,000-line
ceiling. `effdata` supplies the node and the command list; this says what a
curve is worth at a frame, and turns three angles into a matrix.

✅ **Transcribed from the game's own evaluator** at `0x8005f2d4` (D266), branch
for branch, rather than pattern-matched out of the file. The same loop appears
three times in `eff_sub.c` — once for a material's RGBA, once for a texture's
UV animation, once for a node's transform — and all three read this layout.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from bleck.formats.effgeom import section

#: Section 2 holds the samples; a section 10 offset is relative to it.
CURVE_SECTION = 2

#: The header before a curve's samples.
CURVE_HEADER = 12

#: What `+0x0A` means when it is zero: the samples are `f32`. Anything else and
#: they are single bytes, which the game converts to float as-is — no `/255`.
CURVE_FLOAT = 0


@dataclass(frozen=True)
class Curve:
    """A sampled curve out of section 2, one value per frame.

    ```
    +0x00 u32  length in frames -- and the modulus when `loop` is set
    +0x04 u16  the first frame this curve has anything to say
    +0x06 u16  the last one
    +0x08 u16  loop flag
    +0x0A u16  sample format: 0 for f32, anything else for u8
    +0x0C      the samples
    ```

    ⛔ **The earlier reading of this header is superseded.** It took `+0x06` for
    a sample count when it is the **last frame**, and `+0x08` for an always-zero
    word. Reading `+0x06` as a count is what made a third of the offsets look
    like they pointed *inside* other records, and reading `u8` samples as floats
    is where the `-FLT_MAX` came from — a byte pattern, not a sentinel.
    """

    offset: int
    length: int
    start: int
    end: int
    loop: int
    byte_samples: int
    samples: tuple

    def value_at(self, frame: float) -> float | None:
        """This curve at `frame`, or `None` when it has nothing to say yet.

        ⚠️ **`None` is not zero.** A curve that has not started leaves the
        node's own static value in place; substituting zero would collapse every
        scale that is waiting to begin — and 44% of the file's draws are waiting
        at frame 0 (D265).
        """
        if self.length <= 0:
            return None
        time = float(frame)
        if self.loop:
            # ⚠️ `length << 6`, which is what the game adds. A plain `+= length`
            # is the obvious guess and is not what the code does.
            while time < 0.0:
                time += float(self.length << 6)
            time = float(int(time) % self.length)
        else:
            if frame < 0.0:
                time = 0.0
            if time >= float(self.length):
                time = float(self.length - 1)
        if time < float(self.start):
            return None
        # Past the end it holds rather than wrapping or vanishing.
        time = min(time, float(self.end))
        at = int(time - float(self.start))
        if at < 0 or at >= len(self.samples):
            return None
        return float(self.samples[at])


def curve_at(data: bytes, offset: int) -> Curve:
    """One curve record, by its section-2-relative offset.

    ⚠️ A curve holds `end - start + 1` samples, **not** a count of its own. The
    span is what the evaluator indexes, and reading a count where the end frame
    sits is what made records appear to overlap.
    """
    start_at, end_at = section(data, CURVE_SECTION)
    at = start_at + offset
    if offset < 0 or at + CURVE_HEADER > end_at:
        return Curve(offset, 0, 0, 0, 0, 0, ())
    length, first, last, loop, kind = struct.unpack_from(">IHHHH", data, at)
    held = max(last - first + 1, 0)
    width = 1 if kind != CURVE_FLOAT else 4
    if at + CURVE_HEADER + held * width > end_at:
        held = max((end_at - at - CURVE_HEADER) // width, 0)
    body = at + CURVE_HEADER
    if kind != CURVE_FLOAT:
        samples = tuple(float(v) for v in data[body : body + held])
    else:
        samples = struct.unpack_from(f">{held}f", data, body)
    return Curve(offset, length, first, last, loop, kind, samples)


def turn(which: int, degrees: float) -> list:  # pylint: disable=container-return
    """A 3x3 rotation about axis 0, 1 or 2, in degrees."""
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    if which == 0:
        return [1.0, 0.0, 0.0, 0.0, cos, -sin, 0.0, sin, cos]
    if which == 1:
        return [cos, 0.0, sin, 0.0, 1.0, 0.0, -sin, 0.0, cos]
    return [cos, -sin, 0.0, sin, cos, 0.0, 0.0, 0.0, 1.0]


def product(a: list, b: list) -> list:  # pylint: disable=container-return
    """Two 3x3 matrices, row-major and flat."""
    return [
        sum(a[row * 3 + k] * b[k * 3 + col] for k in range(3))
        for row in range(3)
        for col in range(3)
    ]
