//! Reading values off a headless command line.
//!
//! Shared by `shot` and `reel` so the two commands cannot disagree about what
//! `--size 0` or `--background white` means — a caller comparing a model sheet
//! against an effect sheet would otherwise be measuring the difference.

use crate::render::{self, Background};

/// Bounds on a pixel count. A typo in `--size` would otherwise ask for an
/// allocation no machine has, and the failure would be a kill, not a message.
pub(super) const SIZE_LIMIT: std::ops::RangeInclusive<usize> = 16..=4096;

pub(super) fn number(flag: &str, text: &str) -> Result<usize, String> {
    text.parse()
        .map_err(|_| format!("{flag} wants a whole number, not {text:?}"))
}

/// A background by name, matched against the labels the window shows, with
/// spaces written as dashes. Reusing them keeps the two ways of choosing a
/// backdrop from drifting apart.
pub(super) fn named_background(name: &str) -> Result<Background, String> {
    let wanted = name.trim().to_lowercase().replace(' ', "-");
    render::BACKGROUNDS
        .into_iter()
        .find(|background| background.label().replace(' ', "-") == wanted)
        .ok_or_else(|| {
            let known: Vec<String> = render::BACKGROUNDS
                .iter()
                .map(|background| background.label().replace(' ', "-"))
                .collect();
            format!("unknown background {name:?}; try {}", known.join(", "))
        })
}

/// The message a size outside `SIZE_LIMIT` is refused with.
pub(super) fn size_refusal(size: usize) -> String {
    format!(
        "--size {size} is outside {}..={}",
        SIZE_LIMIT.start(),
        SIZE_LIMIT.end()
    )
}
