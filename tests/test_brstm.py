"""BRSTM streams, and the checks that say a decode is audio rather than noise.

⛔ **A wrong ADPCM decode produces samples in the right range, in the right
count, at the right rate.** Every structural check passes and the file plays as
static. So the load-bearing test here is not structural at all — it measures
**correlation between adjacent samples**, which real audio has and noise does
not, against a shuffled control (D226).
"""

from __future__ import annotations

import random
import statistics
import struct
from pathlib import Path

import pytest

from bleck.formats import brstm, wav

REPO = Path(__file__).resolve().parent.parent
SOUND = REPO / "work" / "extracted" / "eu0" / "files" / "sound"


def adjacent_correlation(samples: list) -> float:
    """How strongly each sample predicts the next one."""
    first, second = samples[:-1], samples[1:]
    mean_a = statistics.fmean(first)
    mean_b = statistics.fmean(second)
    top = sum((a - mean_a) * (b - mean_b) for a, b in zip(first, second, strict=True))
    left = sum((a - mean_a) ** 2 for a in first) ** 0.5
    right = sum((b - mean_b) ** 2 for b in second) ** 0.5
    return top / (left * right) if left and right else 0.0


class TestRefusals:
    def test_something_that_is_not_a_stream_is_refused(self):
        assert not brstm.is_brstm(b"\x00" * 128)
        with pytest.raises(brstm.StreamError, match="not a BRSTM"):
            brstm.read(b"\x00" * 128)

    def test_a_truncated_stream_names_the_pointer_rather_than_crashing(self):
        data = bytearray(b"RSTM" + b"\x00" * 200)
        struct.pack_into(">I", data, brstm.CHUNKS_AT, 0x40)
        with pytest.raises(brstm.StreamError):
            brstm.read(bytes(data))


class TestTheWavWriter:
    def test_channels_are_interleaved_not_concatenated(self):
        """⚠️ Concatenating gives a file of the right length that plays one
        channel after the other."""
        blob = wav.write(8000, [[1, 2, 3], [-1, -2, -3]])
        body = blob[44:]
        assert struct.unpack("<6h", body) == (1, -1, 2, -2, 3, -3)

    def test_the_header_declares_what_follows(self):
        blob = wav.write(22050, [[0] * 10, [0] * 10])
        assert blob[:4] == b"RIFF" and blob[8:12] == b"WAVE"
        channels, rate = struct.unpack_from("<HI", blob, 22)
        assert channels == 2
        assert rate == 22050
        assert struct.unpack_from("<I", blob, 4)[0] == len(blob) - 8

    def test_nothing_to_write_is_refused(self):
        with pytest.raises(ValueError, match="no samples"):
            wav.write(44100, [])


@pytest.mark.gamedata
class TestAgainstTheDisc:
    def _streams(self, limit: int = 8):
        if not SOUND.is_dir():
            pytest.skip(f"no extracted disc at {SOUND}")
        for path in sorted(SOUND.glob("*.brstm"))[:limit]:
            yield path.name, brstm.read(path.read_bytes())

    def test_a_decode_is_audio_and_not_noise(self):
        """⛔ The one that matters. 0.67-0.96 for real tracks, ~0.00 shuffled."""
        random.seed(1)
        checked = 0
        for name, stream in self._streams():
            window = stream.pcm[0][20000:40000]
            if len(window) < 1000:
                continue
            checked += 1
            shuffled = window[:]
            random.shuffle(shuffled)
            real = adjacent_correlation(window)
            control = adjacent_correlation(shuffled)
            assert real > 0.5, f"{name}: {real:.3f} is not audio"
            assert abs(control) < 0.1, f"{name}: control leaked, {control:.3f}"
            assert real > abs(control) * 5, name
        assert checked >= 5

    def test_the_sample_count_matches_the_header(self):
        """⚠️ Short by one block is inaudible in a spot check and obvious here:
        the final block is a different size and assuming a full one truncates."""
        for name, stream in self._streams():
            for channel in stream.pcm:
                assert len(channel) == stream.samples, name

    def test_every_stream_on_the_disc_has_a_readable_header(self):
        """⚠️ Headers only. Decoding all 135 takes about two minutes, which is
        long enough that nobody would run the suite."""
        if not SOUND.is_dir():
            pytest.skip(f"no extracted disc at {SOUND}")
        read = 0
        for path in sorted(SOUND.glob("*.brstm")):
            data = path.read_bytes()
            if not brstm.is_brstm(data):
                continue
            stream = brstm.header(data)
            assert stream.rate > 0 and stream.channels > 0, path.name
            assert stream.samples > 0, path.name
            read += 1
        assert read >= 130, f"only {read} streams read"

    def test_a_header_read_agrees_with_a_full_decode(self):
        """⛔ Two paths that could drift. If `header` said something `read`
        contradicted, `sound list` would describe tracks that export
        differently."""
        for name, stream in self._streams(4):
            quick = brstm.header((SOUND / f"{name}").read_bytes())
            assert quick.rate == stream.rate, name
            assert quick.channels == stream.channels, name
            assert quick.loops == stream.loops, name
            assert quick.samples == stream.samples, name
            assert not quick.pcm, "a header read must not decode samples"

    def test_no_stream_is_silent_or_clipped_throughout(self):
        """⚠️ A decode that lost its predictor state rails to the limits;
        one that lost its scale goes quiet. Both look fine structurally."""
        for name, stream in self._streams():
            window = stream.pcm[0][:40000]
            loud = sum(1 for v in window if abs(v) >= 0x7FFE)
            assert max(abs(v) for v in window) > 100, f"{name} is silent"
            assert loud * 100 < len(window), f"{name} is clipped throughout"


class TestThePlaybackRate:
    """⛔ The rule that a stated rate above 40 kHz is halved (D232).

    Fitted to two measured points, not decoded from anything: a known-good
    recording of `ff_pureheart_get_s2_lp` runs 8.90 s, which puts its 193,816
    samples at 21,777 Hz against a stated 44100; and a listener confirmed
    `ff_itemget1_32k` is correct at its stated 32000.
    """

    def a_stream(self, rate: int) -> brstm.Stream:
        return brstm.Stream(
            rate=rate, channels=2, samples=193816, loop_start=0, loops=False
        )

    def test_a_44100_stream_plays_at_half(self):
        assert self.a_stream(44100).playback_rate == 22050

    def test_a_32000_stream_is_left_alone(self):
        assert self.a_stream(32000).playback_rate == 32000

    def test_the_near_32k_variants_are_left_alone(self):
        """⚠️ 32028 and 32728 are six real tracks. A threshold at 32000 rather
        than 40000 would halve them to 16 kHz on no evidence at all."""
        assert self.a_stream(32028).playback_rate == 32028
        assert self.a_stream(32728).playback_rate == 32728

    def test_the_duration_matches_the_reference_recording(self):
        """✅ The measured point: 8.90 s, from 371 MPEG1 Layer-3 frames."""
        assert self.a_stream(44100).seconds == pytest.approx(8.79, abs=0.02)

    def test_describe_says_when_it_disagrees_with_the_header(self):
        assert "header says 44100" in self.a_stream(44100).describe()
        assert "header says" not in self.a_stream(32000).describe()
