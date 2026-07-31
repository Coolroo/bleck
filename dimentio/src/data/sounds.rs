//! What `bleck sound export` wrote: the track list, and the transport that
//! moves through one. **This is the data layer** — the panels that draw it are
//! in `app::sounds`, and the samples behind a track are read by `data::wav`.
//!
//! ⚠️ The manifest is the contract, not the directory listing — the rule for
//! this whole layer, stated once in `data`'s module doc. Nothing here reads
//! BRSTM; `bleck` owns that format and is tested against a real disc.
//!
//! ⚠️ **`capped` means the file on disk is shorter than the game's track.** The
//! export truncates at `--seconds`, so every duration below is the duration of
//! the *export*. A window that showed it as the track's length would state a
//! measured fact that is not one.

use serde::Deserialize;
use std::path::{Path, PathBuf};

/// The file `bleck sound export` writes alongside the WAVs.
const MANIFEST: &str = "sounds.json";

/// Loudest the volume control goes. 1.0 is the samples as decoded; above that
/// the mixer clips, so nothing is gained by offering more.
pub const MAX_VOLUME: f32 = 1.0;

/// Where the volume starts. Below full scale because the export is normalised
/// music and a first click at full volume is unpleasant.
const OPENING_VOLUME: f32 = 0.7;

#[derive(Debug, Deserialize)]
struct Manifest {
    sounds: Vec<Entry>,
}

/// One exported track, as `bleck` described it.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Entry {
    /// The track's own name, which is what the disc file is called.
    pub name: String,
    /// The WAV, relative to the export folder. Made absolute on load.
    #[serde(rename = "file")]
    pub path: PathBuf,
    /// The disc file it was decoded from.
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub rate: u32,
    #[serde(default)]
    pub channels: u16,
    /// Duration **of the exported file**, which `capped` says may be shorter
    /// than the game's own track.
    #[serde(default)]
    pub seconds: f32,
    /// Whether the game loops this track rather than playing it once.
    #[serde(default)]
    pub loops: bool,
    /// Sample frame the game's loop returns to.
    #[serde(default)]
    pub loop_start: u64,
    /// The export stopped early, so the file is not the whole track.
    #[serde(default)]
    pub capped: bool,
}

impl Entry {
    /// The facts that decide whether a track is worth opening.
    pub fn describe(&self) -> String {
        format!(
            "{:.2}s · {} Hz · {}{}{}",
            self.seconds,
            self.rate,
            channel_name(self.channels),
            if self.loops { " · loops" } else { "" },
            if self.capped { " · capped" } else { "" },
        )
    }

    /// The loop point in seconds, for the tracks that have one. `loop_start` is
    /// counted in sample frames, so it means nothing without the rate.
    pub fn loop_seconds(&self) -> Option<f32> {
        if !self.loops || self.rate == 0 {
            return None;
        }
        Some(self.loop_start as f32 / self.rate as f32)
    }
}

/// What a channel count is called, so a panel says "stereo" rather than "2".
pub fn channel_name(channels: u16) -> &'static str {
    match channels {
        1 => "mono",
        2 => "stereo",
        _ => "multichannel",
    }
}

/// What the transport is doing. Distinct from a bare `playing` flag because
/// paused and stopped differ: one keeps its position and one does not.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Motion {
    #[default]
    Stopped,
    Playing,
    Paused,
}

/// Where playback is, whether it is moving, and how loud.
///
/// ⚠️ Kept apart from both the window and the mixer on purpose. Nothing in
/// here opens an audio device, so the whole state machine can be tested on a
/// machine with no sound card — which is the only evidence this program has
/// that play, pause and stop do different things.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Transport {
    pub time: f32,
    pub motion: Motion,
    pub volume: f32,
}

impl Default for Transport {
    fn default() -> Self {
        Self {
            time: 0.0,
            motion: Motion::default(),
            volume: OPENING_VOLUME,
        }
    }
}

impl Transport {
    /// Start, or resume from where a pause left off.
    ///
    /// ⚠️ It does **not** rewind. Pausing and playing again must continue, and
    /// a `play` that reset `time` would be indistinguishable from `stop` on
    /// every track short enough to notice.
    pub fn play(&mut self) {
        self.motion = Motion::Playing;
    }

    /// Hold position. No effect unless something is playing, so a pause on a
    /// stopped transport cannot leave it holding a position it never reached.
    pub fn pause(&mut self) {
        if self.motion == Motion::Playing {
            self.motion = Motion::Paused;
        }
    }

    /// Back to silence at the start. This is the one thing that discards the
    /// position, and it is also what a new selection does.
    pub fn stop(&mut self) {
        self.motion = Motion::Stopped;
        self.time = 0.0;
    }

    pub fn playing(&self) -> bool {
        self.motion == Motion::Playing
    }

    /// Move to a point in the track, clamped to it.
    pub fn seek(&mut self, time: f32, span: f32) {
        self.time = time.clamp(0.0, span.max(0.0));
    }

    /// Advance `dt` seconds. Reaching the end stops rather than wrapping: a
    /// track is not a loop the way an effect is, and one that restarted by
    /// itself could not be left alone.
    pub fn advance(&mut self, dt: f32, span: f32) {
        if self.motion != Motion::Playing {
            return;
        }
        if span <= 0.0 {
            self.stop();
            return;
        }
        self.time += dt.max(0.0);
        if self.time >= span {
            self.stop();
        }
    }
}

/// Why a folder produced no sounds, so the window can say which.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Problem {
    NoManifest(PathBuf),
    Unreadable(String),
}

impl Problem {
    pub fn describe(&self) -> String {
        match self {
            // ⚠️ Names the file it wanted. "Nothing here" sends someone
            // looking in the wrong place.
            Self::NoManifest(path) => format!(
                "No {MANIFEST} in {}.\nRun: bleck sound export --out {}",
                path.display(),
                path.display()
            ),
            Self::Unreadable(why) => format!("{MANIFEST} could not be read:\n{why}"),
        }
    }
}

/// Every track the export folder declares.
#[derive(Default)]
pub struct Library {
    entries: Vec<Entry>,
    problem: Option<Problem>,
}

impl Library {
    /// Read the manifest in `root`.
    ///
    /// A failure is recorded rather than returned, for the same reason as
    /// `Catalog::load`: the window is already open and needs to be told what
    /// to do about it, which `Problem` carries and a `Result` would not.
    pub fn load(root: &Path) -> Self {
        let text = match std::fs::read_to_string(root.join(MANIFEST)) {
            Ok(text) => text,
            Err(_) => {
                return Self {
                    problem: Some(Problem::NoManifest(root.to_path_buf())),
                    ..Default::default()
                }
            }
        };
        let manifest: Manifest = match serde_json::from_str(&text) {
            Ok(manifest) => manifest,
            Err(why) => {
                return Self {
                    problem: Some(Problem::Unreadable(why.to_string())),
                    ..Default::default()
                }
            }
        };
        let entries = manifest
            .sounds
            .into_iter()
            .map(|mut entry| {
                entry.path = root.join(&entry.path);
                entry
            })
            .collect();
        Self {
            entries,
            problem: None,
        }
    }

    pub fn entries(&self) -> &[Entry] {
        &self.entries
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Paired with `len` because clippy asks for it; the UI branches on
    /// `problem()` and the match count instead, so only the tests call this.
    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn problem(&self) -> Option<&Problem> {
        self.problem.as_ref()
    }

    /// Indices matching a search, in manifest order. The disc path is searched
    /// as well as the name, because a track found in the game's code is found
    /// by its file rather than by the name the export gives it.
    pub fn matching(&self, search: &str) -> Vec<usize> {
        let needle = search.to_lowercase();
        self.entries
            .iter()
            .enumerate()
            .filter(|(_, entry)| {
                needle.is_empty()
                    || entry.name.to_lowercase().contains(&needle)
                    || entry.source.to_lowercase().contains(&needle)
            })
            .map(|(index, _)| index)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::scratch::Scratch;

    /// The manifest as `bleck sound export` writes it today, keys and all.
    ///
    /// ⚠️ Unknown keys must stay tolerated. `models.json` gained three after
    /// its reader was written, and a stricter one would have refused every
    /// export the day they landed.
    const LIVE_MANIFEST: &str = r#"{"schema": 1, "sounds": [
      {"name": "b_happy_flower_44k_lp", "file": "b_happy_flower_44k_lp.wav",
       "source": "files/sound/b_happy_flower_44k_lp.brstm",
       "rate": 44100, "channels": 2, "seconds": 8.193,
       "loops": false, "loop_start": 0, "capped": true},
      {"name": "b_mini_gameover1_32k_lp", "file": "b_mini_gameover1_32k_lp.wav",
       "source": "files/sound/b_mini_gameover1_32k_lp.brstm",
       "rate": 32028, "channels": 2, "seconds": 20.0,
       "loops": true, "loop_start": 272384, "capped": true,
       "something_added_later": [1, 2, 3]}
    ]}"#;

    fn library() -> (Scratch, Library) {
        let scratch = Scratch::new("snd-live");
        scratch.write("sounds.json", LIVE_MANIFEST);
        let library = Library::load(&scratch.path);
        (scratch, library)
    }

    #[test]
    fn reads_the_manifest_the_exporter_writes_today() {
        let (scratch, library) = library();
        assert_eq!(library.problem(), None);
        assert_eq!(library.len(), 2);

        let flower = &library.entries()[0];
        assert_eq!(flower.rate, 44100);
        assert_eq!(flower.channels, 2);
        assert!(flower.capped, "the export truncated it");
        assert!(!flower.loops);
        assert_eq!(flower.loop_seconds(), None, "a track that does not loop");
        assert!(
            flower.describe().contains("stereo"),
            "{}",
            flower.describe()
        );
        assert!(
            flower.describe().contains("capped"),
            "{}",
            flower.describe()
        );
        assert_eq!(
            flower.path,
            scratch.path.join("b_happy_flower_44k_lp.wav"),
            "the manifest's relative path is made absolute"
        );
    }

    /// `loop_start` is a sample frame, and means nothing without the rate.
    #[test]
    fn a_loop_point_is_reported_in_seconds() {
        let (_scratch, library) = library();
        let gameover = &library.entries()[1];
        let at = gameover.loop_seconds().expect("this one loops");
        assert!(
            (at - 8.5049).abs() < 1e-3,
            "272384 frames at 32028 Hz: {at}"
        );
        assert!(gameover.describe().contains("loops"));
    }

    #[test]
    fn a_missing_manifest_names_the_folder_and_the_command() {
        let scratch = Scratch::new("snd-bare");
        let library = Library::load(&scratch.path);
        assert_eq!(
            library.problem(),
            Some(&Problem::NoManifest(scratch.path.clone()))
        );
        let said = library.problem().expect("a problem").describe();
        assert!(said.contains("bleck sound export"), "{said}");
        assert!(said.contains(&scratch.path.display().to_string()), "{said}");
    }

    #[test]
    fn broken_json_is_reported_not_panicked() {
        let scratch = Scratch::new("snd-broken");
        scratch.write("sounds.json", "{\"sounds\": [");
        let library = Library::load(&scratch.path);
        assert!(matches!(library.problem(), Some(Problem::Unreadable(_))));
        assert!(library.is_empty());
    }

    #[test]
    fn search_matches_a_name_or_the_disc_file_it_came_from() {
        let (_scratch, library) = library();
        assert_eq!(library.matching(""), vec![0, 1]);
        assert_eq!(library.matching("FLOWER"), vec![0]);
        assert_eq!(library.matching("brstm"), vec![0, 1], "the disc path");
        assert!(library.matching("dimentio").is_empty());
    }

    #[test]
    fn a_channel_count_is_named_rather_than_numbered() {
        assert_eq!(channel_name(1), "mono");
        assert_eq!(channel_name(2), "stereo");
        assert_eq!(channel_name(6), "multichannel");
    }

    /// ⚠️ The transport's whole reason for existing. Pause then play must
    /// **resume**: a `play` that rewound would be indistinguishable from
    /// `stop`, and the difference is only visible on a track long enough to
    /// hear it — which is not something this machine can check.
    #[test]
    fn pause_then_play_resumes_rather_than_restarting() {
        let mut transport = Transport::default();
        transport.play();
        transport.advance(2.0, 10.0);
        assert_eq!(transport.time, 2.0);

        transport.pause();
        assert_eq!(transport.motion, Motion::Paused);
        transport.advance(5.0, 10.0);
        assert_eq!(transport.time, 2.0, "a paused transport does not move");

        transport.play();
        assert_eq!(transport.time, 2.0, "resumed where it was, not at zero");
        transport.advance(1.0, 10.0);
        assert_eq!(transport.time, 3.0);
    }

    #[test]
    fn stop_resets_to_the_start() {
        let mut transport = Transport::default();
        transport.play();
        transport.advance(4.0, 10.0);
        transport.stop();
        assert_eq!(transport.motion, Motion::Stopped);
        assert_eq!(transport.time, 0.0);

        // And a stopped transport is not secretly paused: playing again runs
        // from the start.
        transport.play();
        transport.advance(1.0, 10.0);
        assert_eq!(transport.time, 1.0);
    }

    /// A pause on something that was never playing must not manufacture a
    /// paused position out of a stopped one.
    #[test]
    fn pausing_a_stopped_transport_leaves_it_stopped() {
        let mut transport = Transport::default();
        transport.pause();
        assert_eq!(transport.motion, Motion::Stopped);
    }

    /// Reaching the end stops rather than wrapping. An effect loops; a track
    /// that restarted by itself could not be left alone.
    #[test]
    fn reaching_the_end_stops_instead_of_wrapping() {
        let mut transport = Transport::default();
        transport.play();
        transport.advance(9.0, 10.0);
        assert_eq!(transport.time, 9.0);
        transport.advance(2.0, 10.0);
        assert_eq!(transport.motion, Motion::Stopped);
        assert_eq!(transport.time, 0.0);
    }

    /// A track with no samples has nothing to play, and its scrubber would be
    /// a slider over an empty range.
    #[test]
    fn a_zero_length_track_stops_instead_of_dividing_by_its_length() {
        let mut transport = Transport::default();
        transport.play();
        transport.advance(0.1, 0.0);
        assert_eq!(transport.motion, Motion::Stopped);
        assert_eq!(transport.time, 0.0);
        transport.seek(5.0, 0.0);
        assert_eq!(transport.time, 0.0);
    }

    #[test]
    fn a_seek_is_clamped_to_the_track() {
        let mut transport = Transport::default();
        transport.seek(3.5, 10.0);
        assert_eq!(transport.time, 3.5);
        transport.seek(99.0, 10.0);
        assert_eq!(transport.time, 10.0, "past the end");
        transport.seek(-4.0, 10.0);
        assert_eq!(transport.time, 0.0, "before the start");
    }

    #[test]
    fn the_volume_starts_below_full_scale_and_full_scale_is_the_ceiling() {
        let transport = Transport::default();
        assert!(transport.volume > 0.0);
        assert!(transport.volume <= MAX_VOLUME);
        assert_eq!(MAX_VOLUME, 1.0, "above 1.0 the mixer clips");
    }
}

/// Against the folder `bleck sound export` actually wrote, when there is one.
///
/// ⚠️ The fixtures above are written by this crate's own tests, so a reader
/// that disagreed with `bleck` about a real file would agree with itself all
/// day. These are the only tests that could catch that.
#[cfg(test)]
mod real_export_tests {
    use super::*;
    use crate::data::wav::Audio;
    use crate::render::wave::Envelope;

    fn export() -> Option<PathBuf> {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()?
            .join("work")
            .join("export");
        root.join(MANIFEST).is_file().then_some(root)
    }

    #[test]
    fn every_wav_the_manifest_names_actually_decodes() {
        let Some(root) = export() else {
            eprintln!("no work/export on this machine; skipped");
            return;
        };
        let library = Library::load(&root);
        assert!(!library.is_empty(), "the manifest named nothing");

        let mut failed = Vec::new();
        for entry in library.entries() {
            match Audio::load(&entry.path) {
                Ok(audio) if audio.frames() > 0 => {}
                Ok(_) => failed.push(format!("{}: no samples", entry.name)),
                Err(why) => failed.push(format!("{}: {why}", entry.name)),
            }
        }
        assert!(
            failed.is_empty(),
            "{} of {} failed, e.g. {:?}",
            failed.len(),
            library.len(),
            &failed[..failed.len().min(3)]
        );
    }

    /// ⚠️ The check that the two halves of the export agree. A manifest that
    /// said 44,100 Hz over a file recorded at 32,028 would play at the wrong
    /// pitch, and the scrubber would run out before the sound did.
    #[test]
    fn a_real_file_holds_what_its_manifest_row_claims() {
        let Some(root) = export() else {
            eprintln!("no work/export on this machine; skipped");
            return;
        };
        let library = Library::load(&root);
        for entry in library.entries().iter().take(24) {
            let audio = Audio::load(&entry.path).expect("a real wav");
            assert_eq!(audio.rate(), entry.rate, "{} sample rate", entry.name);
            assert_eq!(audio.channels(), entry.channels, "{} channels", entry.name);
            let drift = (audio.seconds() - entry.seconds).abs();
            assert!(
                drift < 0.01,
                "{}: the file is {:.3}s, the manifest says {:.3}s",
                entry.name,
                audio.seconds(),
                entry.seconds
            );
        }
    }

    /// Real music is not silence and is not clipped flat, so its envelope has
    /// to vary. A summariser that returned a constant would pass every fixture
    /// above, because a fixture is a constant.
    #[test]
    fn a_real_track_summarises_into_a_varying_envelope() {
        let Some(root) = export() else {
            eprintln!("no work/export on this machine; skipped");
            return;
        };
        let library = Library::load(&root);
        let entry = &library.entries()[0];
        let audio = Audio::load(&entry.path).expect("a real wav");
        let envelope = Envelope::of(audio.samples(), 512);
        assert_eq!(envelope.columns().len(), 512);

        let peak = envelope.peak();
        assert!(peak > 0.05, "{} is near silent: peak {peak}", entry.name);
        assert!(peak <= 1.0, "{} exceeds full scale: {peak}", entry.name);
        let quietest = envelope
            .columns()
            .iter()
            .map(|column| column.height())
            .fold(f32::INFINITY, f32::min);
        let loudest = envelope
            .columns()
            .iter()
            .map(|column| column.height())
            .fold(0.0, f32::max);
        assert!(
            loudest > quietest * 1.5,
            "{} draws as a flat band: {quietest} to {loudest}",
            entry.name
        );
    }
}
