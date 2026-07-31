"""BRSTM: the 135 streamed music tracks in `files/sound/`.

The disc's music is `RSTM`, Nintendo's Wii streaming container, holding
**DSP-ADPCM** — the GameCube/Wii hardware codec. 162 MB of it, against 15 MB of
`BRSAR` for the sound effects, which is a different and much larger problem.

⛔ **No audio ships with `bleck`.** This decodes whatever disc the user
extracted, exactly like every texture and model path. `work/` stays git-ignored.

## The container

    RSTM header -> HEAD (what it is) / ADPC (seek table) / DATA (the samples)

`HEAD` carries three parts: the stream description, a per-channel table, and
the ADPCM coefficients. ⚠️ **Every part offset inside `HEAD` is relative to
`HEAD + 8`**, not to the file and not to the chunk — a reader that treats them
as file offsets lands in the middle of the audio and decodes noise.

## The codec

Each **8-byte frame decodes to 14 samples**: one header byte, then 7 bytes of
packed 4-bit deltas. The header byte carries a predictor index and a scale, and
each sample is a delta plus a weighted sum of the previous two — so a frame
cannot be decoded without the two samples before it.

Samples are stored in **blocks, interleaved by channel**: the whole first block
of channel 0, then of channel 1, and so on. ⚠️ The final block is short, and its
size is given separately; assuming a full one reads past the end of DATA.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from bleck.common.errors import BleckError

MAGIC = b"RSTM"
HEAD = b"HEAD"
DATA = b"DATA"

#: Where the chunk table sits in the RSTM header, and how many entries this
#: reader needs from it.
CHUNKS_AT = 0x10

#: `HEAD`'s three part offsets, and the base they are measured from.
PART_TABLE_AT = 0x0C
PART_BASE = 8
PARTS = 3

#: The only codec the disc uses. 0 and 1 are 8- and 16-bit PCM, which nothing
#: in `files/sound/` is.
DSP_ADPCM = 2

#: `HEAD`'s third part: a channel count, then one `(marker, offset)` pair per
#: channel. ⚠️ **Two hops, not one** — the pair points at a channel-info struct
#: whose *own* second word points at the coefficients, and both offsets are
#: measured from `HEAD + 8`.
CHANNEL_TABLE_SKIP = 4
CHANNEL_ENTRY = 8

#: 16 coefficients, then gain, predictor state and two history samples.
COEFFICIENT_BLOCK = 0x28


#: Above this a stated rate is halved (D232). The Wii's AX mixer is natively
#: 32 kHz, and the disc uses four rates: 32000, 32028, 32728 and 44100.
#:
#: ⚠️ **The threshold sits at 40000, not 32000.** 32028 and 32728 are
#: near-32k variants -- six tracks -- and a threshold of 32000 would halve them
#: to 16 kHz on no evidence at all. Only 44100 is measured (D232), so only
#: 44100 is halved.
HALVE_ABOVE = 40000


#: A frame is one header byte plus seven of packed nibbles.
FRAME_BYTES = 8
FRAME_SAMPLES = 14

#: The fixed-point shift the codec's weighted sum uses.
PREDICTOR_SHIFT = 11
PREDICTOR_ROUND = 1 << (PREDICTOR_SHIFT - 1)

SAMPLE_MIN = -0x8000
SAMPLE_MAX = 0x7FFF


class StreamError(BleckError):
    """A BRSTM could not be read."""


@dataclass(frozen=True)
class Channel:
    """One channel's ADPCM state: the coefficients, and where it starts."""

    coefficients: tuple
    history1: int = 0
    history2: int = 0


@dataclass(frozen=True)
class Stream:
    """A decoded stream, and what the header said about it."""

    rate: int
    channels: int
    samples: int
    loop_start: int
    loops: bool
    pcm: list = field(default_factory=list)  # pylint: disable=container-return
    """One list of signed 16-bit samples per channel."""

    @property
    def playback_rate(self) -> int:
        """The rate the track is actually heard at, which is not always `rate`.

        ✅ **Measured against a known-good recording** (D232). A reference of
        `ff_pureheart_get_s2_lp` runs **8.90 s**; the file holds 193,816 samples
        per channel, so it plays at 193,816 / 8.90 = **21,777 Hz** -- 22050,
        exactly half the 44100 its header states.

        ⚠️ A listener separately confirmed `ff_itemget1_32k` is correct at its
        stated 32000. Those two files are structurally identical -- same RSAR
        entry shape, same stream spec, same block layout -- and differ only in
        this field, so the rule keys off the field itself.

        ⛔ **This is a rule fitted to two points**, not a decoded one. Nothing
        in the DOL, `wiimario_snd.dat` or the sound archive was found to encode
        it (D230): no rate override, no pitch modifier, and the one promising
        flag correlates with rate without selecting it.
        """
        return self.rate // 2 if self.rate > HALVE_ABOVE else self.rate

    @property
    def seconds(self) -> float:
        rate = self.playback_rate
        return self.samples / rate if rate else 0.0

    def describe(self) -> str:
        kind = "looping" if self.loops else "one-shot"
        rate = self.playback_rate
        halved = f" (header says {self.rate})" if rate != self.rate else ""
        return f"{rate} Hz{halved}, {self.channels}ch, {self.seconds:.1f}s, {kind}"


def is_brstm(data: bytes) -> bool:
    return len(data) > CHUNKS_AT + 24 and data[:4] == MAGIC


@dataclass(frozen=True)
class FinalBlock:
    """The short block at the end, which is described by three separate fields.

    ⛔ **These three are easy to transpose and the transposition is audible.**
    They sit at `+0x20`, `+0x24` and `+0x28`, in the order size, samples,
    padded — reading them as size, padded, samples truncates every track by its
    last fraction of a second (D226).
    """

    size: int
    samples: int
    padded: int
    """⚠️ The stride between channels in the final block, which is **not** its
    byte size -- the block is padded and the channels sit that far apart."""


@dataclass(frozen=True)
class Layout:
    """Where the samples are and how they are grouped."""

    codec: int
    loops: bool
    channels: int
    rate: int
    loop_start: int
    samples: int
    data_at: int
    blocks: int
    block_bytes: int
    block_samples: int
    final: FinalBlock


def _layout(data: bytes, head: int) -> Layout:
    if data[head : head + 4] != HEAD:
        raise StreamError(f"no HEAD chunk at {head:#x}")
    base = head + PART_BASE
    first = struct.unpack_from(">I", data, head + PART_TABLE_AT)[0]
    at = base + first
    codec, loops, channels = struct.unpack_from(">3B", data, at)
    rate = struct.unpack_from(">H", data, at + 4)[0]
    (
        loop_start,
        samples,
        data_at,
        blocks,
        block_bytes,
        block_samples,
        last_block_bytes,
        last_block_samples,
        last_block_padded,
    ) = struct.unpack_from(">9I", data, at + 8)
    if codec != DSP_ADPCM:
        raise StreamError(f"codec {codec} is not DSP-ADPCM; nothing decodes it")
    return Layout(
        codec=codec,
        loops=bool(loops),
        channels=channels,
        rate=rate,
        loop_start=loop_start,
        samples=samples,
        data_at=data_at,
        blocks=blocks,
        block_bytes=block_bytes,
        block_samples=block_samples,
        final=FinalBlock(
            size=last_block_bytes,
            samples=last_block_samples,
            padded=last_block_padded,
        ),
    )


def _channels(data: bytes, head: int, count: int) -> list:
    # pylint: disable=container-return
    """Each channel's 16 coefficients, followed through two pointer hops.

    ⚠️ Part 3 holds a pointer *per channel*, and each of those points at a
    small record whose own second word points at the coefficients. Both hops
    are relative to `HEAD + 8`.
    """
    base = head + PART_BASE
    third = struct.unpack_from(">I", data, head + PART_TABLE_AT + 16)[0]
    found = []
    for index in range(count):
        entry = base + third + CHANNEL_TABLE_SKIP + index * CHANNEL_ENTRY
        info = base + _word(data, entry + 4)
        coefficients_at = base + _word(data, info + 4)
        if coefficients_at + COEFFICIENT_BLOCK > len(data):
            raise StreamError(
                f"channel {index} points its coefficients past the end of the file"
            )
        found.append(
            Channel(
                coefficients=struct.unpack_from(">16h", data, coefficients_at),
                history1=struct.unpack_from(">h", data, coefficients_at + 0x24)[0],
                history2=struct.unpack_from(">h", data, coefficients_at + 0x26)[0],
            )
        )
    return found


def _word(data: bytes, at: int) -> int:
    if at + 4 > len(data):
        raise StreamError(f"a pointer at {at:#x} runs past the end of the file")
    return struct.unpack_from(">I", data, at)[0]


def _decode(block: bytes, channel: Channel, wanted: int) -> list:
    # pylint: disable=container-return
    """One block of frames into signed 16-bit samples."""
    out: list[int] = []
    history1, history2 = channel.history1, channel.history2
    for start in range(0, len(block), FRAME_BYTES):
        frame = block[start : start + FRAME_BYTES]
        if len(frame) < 2 or len(out) >= wanted:
            break
        control = frame[0]
        scale = 1 << (control & 0x0F)
        index = (control >> 4) & 0x07
        even = channel.coefficients[index * 2]
        odd = channel.coefficients[index * 2 + 1]
        for step in range(FRAME_SAMPLES):
            if len(out) >= wanted:
                break
            byte = frame[1 + step // 2] if 1 + step // 2 < len(frame) else 0
            nibble = (byte >> 4) if step % 2 == 0 else (byte & 0x0F)
            if nibble > 7:
                nibble -= 16
            value = (
                nibble * scale * (1 << PREDICTOR_SHIFT)
                + even * history1
                + odd * history2
                + PREDICTOR_ROUND
            ) >> PREDICTOR_SHIFT
            value = max(SAMPLE_MIN, min(SAMPLE_MAX, value))
            history2, history1 = history1, value
            out.append(value)
    return out


def header(data: bytes) -> Stream:
    """What a stream *is*, without decoding a single sample.

    ⚠️ Decoding is the expensive part -- 135 tracks take about two minutes in
    Python -- and listing them needs none of it. `pcm` comes back empty, which
    is why `Stream.samples` is taken from the header rather than measured.
    """
    if not is_brstm(data):
        raise StreamError("not a BRSTM: no RSTM magic")
    plan = _layout(data, struct.unpack_from(">I", data, CHUNKS_AT)[0])
    return Stream(
        rate=plan.rate,
        channels=plan.channels,
        samples=plan.samples,
        loop_start=plan.loop_start,
        loops=plan.loops,
    )


def read(data: bytes) -> Stream:
    """Decode a BRSTM to one sample list per channel."""
    if not is_brstm(data):
        raise StreamError("not a BRSTM: no RSTM magic")
    head = struct.unpack_from(">I", data, CHUNKS_AT)[0]
    plan = _layout(data, head)
    voices = _channels(data, head, plan.channels)

    pcm = [[] for _ in range(plan.channels)]
    state = list(voices)
    for block in range(plan.blocks):
        last = block == plan.blocks - 1
        size = plan.final.size if last else plan.block_bytes
        wanted = plan.final.samples if last else plan.block_samples
        for channel in range(plan.channels):
            stride = plan.final.padded if last else plan.block_bytes
            at = (
                plan.data_at + block * plan.block_bytes * plan.channels + channel * stride
            )
            chunk = data[at : at + size]
            if not chunk:
                continue
            decoded = _decode(chunk, state[channel], wanted)
            pcm[channel] += decoded
            if decoded:
                # ⚠️ A frame depends on the two samples before it, so the tail
                # of one block seeds the next. Restarting from zero clicks at
                # every block boundary -- 26 times in an eight-second track.
                state[channel] = Channel(
                    state[channel].coefficients,
                    decoded[-1],
                    decoded[-2] if len(decoded) > 1 else 0,
                )
    return Stream(
        rate=plan.rate,
        channels=plan.channels,
        samples=min(plan.samples, min((len(c) for c in pcm), default=0)),
        loop_start=plan.loop_start,
        loops=plan.loops,
        pcm=pcm,
    )
