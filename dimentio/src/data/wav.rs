//! The `.wav` files `bleck sound export` writes beside `sounds.json`.
//!
//! ⚠️ This is not a general WAV reader and must not become one. `bleck` writes
//! 16-bit PCM and nothing else, so every other encoding is **refused by name**
//! rather than read. A reader that guessed would hand a float-encoded file to
//! the mixer as integers and play full-scale noise, which is indistinguishable
//! from a decoding bug in `bleck` itself.
//!
//! Samples come out interleaved as `f32` in [-1, 1] — the layout the mixer and
//! the waveform both want, so nothing converts twice.

use std::path::Path;

/// Canonical RIFF header: `RIFF`, size, `WAVE`, then the first chunk header.
const RIFF_HEADER: usize = 12;

/// Every chunk starts with a four-byte id and a four-byte little-endian size.
const CHUNK_HEADER: usize = 8;

/// Shortest `fmt ` body carrying the fields read below.
const FMT_BODY: usize = 16;

/// The one `wFormatTag` accepted. 3 is IEEE float and 0xFFFE is extensible;
/// both are refused by name.
const PCM: u16 = 1;

/// The one sample width accepted.
const BITS: u16 = 16;

/// Divisor that puts `i16` on [-1, 1). Full-scale negative is -1.0 exactly;
/// dividing by 32767 instead would push full-scale positive above 1.0 and clip
/// in the mixer.
const FULL_SCALE: f32 = 32768.0;

/// Decoded audio: interleaved samples, and what they are played back at.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Audio {
    rate: u32,
    channels: u16,
    samples: Vec<f32>,
}

impl Audio {
    /// Decode a whole WAV file held in memory.
    ///
    /// Every failure names what was wrong with the file, because the window has
    /// to say why a track will not play — "nothing happened" reads as a broken
    /// speaker.
    pub fn read(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() < RIFF_HEADER {
            return Err(format!(
                "truncated: {} bytes, too short for a RIFF header",
                bytes.len()
            ));
        }
        if &bytes[0..4] != b"RIFF" {
            return Err("not a WAV file: no RIFF magic".into());
        }
        if &bytes[8..12] != b"WAVE" {
            return Err("not a WAV file: RIFF, but not WAVE".into());
        }

        let mut format: Option<Format> = None;
        let mut at = RIFF_HEADER;
        while at + CHUNK_HEADER <= bytes.len() {
            let id = &bytes[at..at + 4];
            let size = read_u32(&bytes[at + 4..at + 8]) as usize;
            let body = at + CHUNK_HEADER;
            let end = body.checked_add(size).ok_or_else(|| {
                format!("truncated: chunk at {at} declares an impossible {size} bytes")
            })?;
            if end > bytes.len() {
                return Err(format!(
                    "truncated: chunk at {at} declares {size} bytes, {} are present",
                    bytes.len() - body
                ));
            }
            match id {
                b"fmt " => format = Some(Format::read(&bytes[body..end])?),
                b"data" => {
                    let format =
                        format.ok_or("malformed: the data chunk comes before the fmt chunk")?;
                    return Ok(Self {
                        rate: format.rate,
                        channels: format.channels,
                        samples: pcm16(&bytes[body..end]),
                    });
                }
                _ => {}
            }
            // Chunk bodies are word-aligned: an odd size is followed by a pad
            // byte that is not counted in the size.
            at = end + (size & 1);
        }
        Err("malformed: no data chunk".into())
    }

    pub fn load(path: &Path) -> Result<Self, String> {
        let bytes = std::fs::read(path)
            .map_err(|why| format!("{} could not be read: {why}", path.display()))?;
        Self::read(&bytes)
    }

    pub fn rate(&self) -> u32 {
        self.rate
    }

    pub fn channels(&self) -> u16 {
        self.channels
    }

    /// Interleaved samples: channel 0, channel 1, channel 0, and so on.
    pub fn samples(&self) -> &[f32] {
        &self.samples
    }

    /// Sample frames — one per instant, whatever the channel count.
    pub fn frames(&self) -> usize {
        self.samples.len() / self.channels.max(1) as usize
    }

    pub fn seconds(&self) -> f32 {
        if self.rate == 0 {
            return 0.0;
        }
        self.frames() as f32 / self.rate as f32
    }

    /// The samples from `seconds` in, frame-aligned.
    ///
    /// ⚠️ Alignment is what keeps the channels the right way round. An offset
    /// that lands mid-frame swaps left and right for the rest of the track, and
    /// the result sounds correct on a mono source and inverted on a stereo one.
    pub fn from(&self, seconds: f32) -> Vec<f32> {
        let channels = self.channels.max(1) as usize;
        let frame = (seconds.max(0.0) * self.rate as f32) as usize;
        let at = (frame * channels).min(self.samples.len());
        self.samples[at..].to_vec()
    }
}

/// The `fmt ` fields this reader accepts. Anything else never reaches here.
struct Format {
    channels: u16,
    rate: u32,
}

impl Format {
    fn read(body: &[u8]) -> Result<Self, String> {
        if body.len() < FMT_BODY {
            return Err(format!(
                "truncated: the fmt chunk is {} bytes, {FMT_BODY} are needed",
                body.len()
            ));
        }
        let tag = read_u16(&body[0..2]);
        if tag != PCM {
            return Err(format!(
                "unsupported: format tag {tag}, not PCM ({PCM}) — bleck writes PCM only"
            ));
        }
        let bits = read_u16(&body[14..16]);
        if bits != BITS {
            return Err(format!(
                "unsupported: {bits}-bit samples, not {BITS}-bit — bleck writes {BITS}-bit only"
            ));
        }
        let channels = read_u16(&body[2..4]);
        if channels == 0 {
            return Err("malformed: the fmt chunk declares no channels".into());
        }
        let rate = read_u32(&body[4..8]);
        if rate == 0 {
            return Err("malformed: the fmt chunk declares a sample rate of zero".into());
        }
        Ok(Self { channels, rate })
    }
}

/// Little-endian 16-bit samples as floats. A trailing odd byte is dropped: half
/// a sample has no value, and reading it as a whole one is a click.
fn pcm16(body: &[u8]) -> Vec<f32> {
    body.chunks_exact(2)
        .map(|pair| f32::from(read_u16(pair) as i16) / FULL_SCALE)
        .collect()
}

fn read_u16(bytes: &[u8]) -> u16 {
    u16::from_le_bytes([bytes[0], bytes[1]])
}

fn read_u32(bytes: &[u8]) -> u32 {
    u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
}

/// Build a canonical 44-byte-header WAV, so the reader's tests are fed a real
/// file rather than a hand-written byte string — the same reason
/// `texture::png` exists.
#[cfg(test)]
pub(crate) fn wav(rate: u32, channels: u16, samples: &[i16]) -> Vec<u8> {
    write_wav(rate, channels, samples, PCM, BITS)
}

/// The same, with the two fields the reader refuses on left to the caller, so a
/// float or 24-bit file can be built without hand-assembling one.
#[cfg(test)]
pub(crate) fn write_wav(rate: u32, channels: u16, samples: &[i16], tag: u16, bits: u16) -> Vec<u8> {
    let mut body = Vec::with_capacity(samples.len() * 2);
    for sample in samples {
        body.extend_from_slice(&sample.to_le_bytes());
    }
    let align = channels * bits / 8;
    let mut out = Vec::new();
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&((36 + body.len()) as u32).to_le_bytes());
    out.extend_from_slice(b"WAVEfmt ");
    out.extend_from_slice(&(FMT_BODY as u32).to_le_bytes());
    out.extend_from_slice(&tag.to_le_bytes());
    out.extend_from_slice(&channels.to_le_bytes());
    out.extend_from_slice(&rate.to_le_bytes());
    out.extend_from_slice(&(rate * u32::from(align)).to_le_bytes());
    out.extend_from_slice(&align.to_le_bytes());
    out.extend_from_slice(&bits.to_le_bytes());
    out.extend_from_slice(b"data");
    out.extend_from_slice(&(body.len() as u32).to_le_bytes());
    out.extend_from_slice(&body);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// One second of stereo at 8 kHz, left and right deliberately different so
    /// a reader that dropped a channel or swapped the pair shows it.
    fn stereo() -> Vec<i16> {
        (0..8000)
            .flat_map(|frame| [frame as i16, -(frame as i16)])
            .collect()
    }

    #[test]
    fn a_wav_round_trips_through_the_reader() {
        let audio = Audio::read(&wav(8000, 2, &stereo())).expect("a real wav");
        assert_eq!(audio.rate(), 8000);
        assert_eq!(audio.channels(), 2);
        assert_eq!(audio.samples().len(), 16_000, "interleaved samples");
        assert_eq!(audio.frames(), 8000, "frames, not samples");
        assert!((audio.seconds() - 1.0).abs() < 1e-6, "{}", audio.seconds());
        assert_eq!(audio.samples()[0], 0.0);
        assert_eq!(audio.samples()[2], 1.0 / FULL_SCALE, "left, frame 1");
        assert_eq!(audio.samples()[3], -1.0 / FULL_SCALE, "right, frame 1");
    }

    /// ⚠️ The extremes are what a wrong divisor shows: dividing by 32767 puts
    /// full-scale positive above 1.0, which the mixer clips.
    #[test]
    fn full_scale_samples_land_inside_the_unit_range() {
        let audio = Audio::read(&wav(8000, 1, &[i16::MIN, -1, 0, 1, i16::MAX])).expect("a wav");
        assert_eq!(audio.samples()[0], -1.0, "full-scale negative");
        assert_eq!(audio.samples()[2], 0.0, "silence");
        assert!(
            audio.samples()[4] < 1.0,
            "full-scale positive stays under 1"
        );
        assert!(audio.samples().iter().all(|s| (-1.0..=1.0).contains(s)));
    }

    #[test]
    fn a_truncated_header_is_refused_by_name() {
        let whole = wav(8000, 2, &stereo());
        let why = Audio::read(&whole[..20]).expect_err("half a header is not a file");
        assert!(why.contains("truncated"), "{why}");

        let why = Audio::read(&whole[..8]).expect_err("shorter than the RIFF header");
        assert!(why.contains("truncated"), "{why}");
        assert!(why.contains("RIFF"), "{why}");
    }

    /// A file whose `data` chunk claims more than the file holds is a partial
    /// download, and playing what arrived would be a track that stops early
    /// with no explanation.
    #[test]
    fn a_data_chunk_longer_than_the_file_is_refused_by_name() {
        let mut whole = wav(8000, 2, &stereo());
        whole.truncate(whole.len() - 400);
        let why = Audio::read(&whole).expect_err("the data chunk overruns");
        assert!(why.contains("truncated"), "{why}");
        assert!(why.contains("present"), "{why}");
    }

    #[test]
    fn something_that_is_not_a_wav_is_refused_by_name() {
        let why = Audio::read(&[0u8; 64]).expect_err("zeroes are not a wav");
        assert!(why.contains("RIFF"), "{why}");

        let mut ogg = wav(8000, 1, &[0, 1]);
        ogg[8..12].copy_from_slice(b"AVI ");
        let why = Audio::read(&ogg).expect_err("RIFF, but not WAVE");
        assert!(why.contains("WAVE"), "{why}");
    }

    /// ⚠️ The two that would otherwise play as noise. A float file read as
    /// integers is full-scale hiss; a 24-bit file read two bytes at a time is
    /// the same sound an octave off, and neither looks like a bug in the UI.
    #[test]
    fn a_float_or_24_bit_file_is_refused_rather_than_played() {
        let float = write_wav(8000, 2, &stereo(), 3, 32);
        let why = Audio::read(&float).expect_err("IEEE float is not PCM");
        assert!(why.contains("format tag 3"), "{why}");
        assert!(why.contains("PCM"), "{why}");

        let deep = write_wav(8000, 2, &stereo(), PCM, 24);
        let why = Audio::read(&deep).expect_err("24-bit is not 16-bit");
        assert!(why.contains("24-bit"), "{why}");

        let shallow = write_wav(8000, 1, &stereo(), PCM, 8);
        assert!(Audio::read(&shallow).is_err(), "8-bit is not 16-bit either");
    }

    #[test]
    fn a_nonsense_fmt_chunk_is_refused_by_name() {
        let why = Audio::read(&wav(8000, 0, &[1, 2])).expect_err("no channels");
        assert!(why.contains("channels"), "{why}");

        let why = Audio::read(&wav(0, 1, &[1, 2])).expect_err("no sample rate");
        assert!(why.contains("sample rate"), "{why}");

        let mut short = wav(8000, 1, &[1, 2]);
        short[16..20].copy_from_slice(&8u32.to_le_bytes());
        assert!(Audio::read(&short).is_err(), "an 8-byte fmt chunk");
    }

    /// Chunks other than `fmt ` and `data` are skipped, including odd-sized
    /// ones. ⚠️ Forgetting the pad byte lands the walk one byte into the next
    /// chunk's id and every chunk after it reads as garbage.
    #[test]
    fn unknown_chunks_including_odd_sized_ones_are_stepped_over() {
        let whole = wav(8000, 2, &stereo());
        let mut padded = whole[..RIFF_HEADER].to_vec();
        padded.extend_from_slice(b"LIST");
        padded.extend_from_slice(&5u32.to_le_bytes());
        padded.extend_from_slice(b"INFO\0");
        padded.push(0);
        padded.extend_from_slice(&whole[RIFF_HEADER..]);

        let audio = Audio::read(&padded).expect("the LIST chunk is skipped");
        assert_eq!(audio.rate(), 8000);
        assert_eq!(audio.frames(), 8000);
    }

    #[test]
    fn a_file_with_no_data_chunk_is_refused_by_name() {
        let whole = wav(8000, 2, &[1, 2, 3, 4]);
        let header = &whole[..36];
        let why = Audio::read(header).expect_err("fmt but no data");
        assert!(why.contains("no data chunk"), "{why}");
    }

    /// An empty `data` chunk is a legal file with nothing in it, and the
    /// waveform and the scrubber both divide by its length.
    #[test]
    fn an_empty_track_reads_as_zero_length_rather_than_failing() {
        let audio = Audio::read(&wav(8000, 2, &[])).expect("an empty wav is still a wav");
        assert_eq!(audio.frames(), 0);
        assert_eq!(audio.seconds(), 0.0);
        assert!(audio.from(0.0).is_empty());
        assert!(audio.from(5.0).is_empty());
    }

    /// ⚠️ The offset is rounded down to a frame boundary. Landing mid-frame
    /// swaps the channels for the rest of the track.
    #[test]
    fn an_offset_starts_on_a_frame_boundary() {
        let audio = Audio::read(&wav(8000, 2, &stereo())).expect("a wav");
        let half = audio.from(0.5);
        assert_eq!(half.len(), 8000, "half of 16,000 interleaved samples");
        assert_eq!(half[0], audio.samples()[8000], "left channel, frame 4000");
        assert_eq!(half[1], audio.samples()[8001], "and its right");

        // 0.500_03 s is 4000.24 frames: the offset must round down to 4000
        // rather than to sample 8000.48 and land on a right channel.
        let nudged = audio.from(0.500_03);
        assert_eq!(nudged[0], half[0], "still the left channel");

        assert!(audio.from(99.0).is_empty(), "past the end is empty");
        assert_eq!(audio.from(-1.0).len(), audio.samples().len(), "before zero");
    }
}
