//! What sits behind the model.

use super::{Rgba, Size};

/// Edge of one checkerboard square, in pixels.
const CHECK: usize = 16;

/// What sits behind the model. Presets rather than a colour picker: the point
/// is to see a model against light, dark and busy without choosing anything.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Background {
    #[default]
    DarkGrey,
    Checkerboard,
    Gradient,
}

/// Every preset, in the order the picker offers them.
pub const BACKGROUNDS: [Background; 3] = [
    Background::DarkGrey,
    Background::Checkerboard,
    Background::Gradient,
];

impl Background {
    pub fn label(self) -> &'static str {
        match self {
            Self::DarkGrey => "dark grey",
            Self::Checkerboard => "checkerboard",
            Self::Gradient => "gradient",
        }
    }

    /// The colour at one pixel. Backgrounds are functions of position rather
    /// than stored images, so a viewport can be resized without reallocating
    /// anything but the frame itself.
    pub fn pixel(self, x: usize, y: usize, size: Size) -> Rgba {
        match self {
            Self::DarkGrey => Rgba::new(38, 40, 44),
            Self::Checkerboard => {
                if (x / CHECK + y / CHECK) % 2 == 0 {
                    Rgba::new(56, 58, 63)
                } else {
                    Rgba::new(38, 40, 44)
                }
            }
            Self::Gradient => {
                let top = Rgba::new(46, 52, 74);
                let bottom = Rgba::new(12, 13, 18);
                let fall = if size.height > 1 {
                    y as f32 / (size.height - 1) as f32
                } else {
                    0.0
                };
                let mix = |high: u8, low: u8| {
                    (f32::from(high) + (f32::from(low) - f32::from(high)) * fall) as u8
                };
                Rgba::new(
                    mix(top.r, bottom.r),
                    mix(top.g, bottom.g),
                    mix(top.b, bottom.b),
                )
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::mesh::Mesh;
    use crate::render::fixtures::{cube, differing, FRAME};
    use crate::render::{render, Camera, Image, View};

    #[test]
    fn each_background_looks_different_from_the_others() {
        let empty = Mesh::default();
        let frames: Vec<Image> = BACKGROUNDS
            .iter()
            .map(|&background| {
                let view = View {
                    camera: Camera::default(),
                    background,
                };
                render(&empty, &view, FRAME)
            })
            .collect();

        assert!(differing(&frames[0], &frames[1]) > 0);
        assert!(differing(&frames[0], &frames[2]) > 0);

        let plain = &frames[0];
        assert_eq!(plain.pixel(0, 0), plain.pixel(199, 199));

        let checks = &frames[1];
        assert_ne!(checks.pixel(0, 0), checks.pixel(CHECK, 0));
        assert_eq!(checks.pixel(0, 0), checks.pixel(CHECK, CHECK));

        let gradient = &frames[2];
        assert_ne!(gradient.pixel(0, 0), gradient.pixel(0, 199));
        assert_eq!(gradient.pixel(0, 40), gradient.pixel(199, 40));
    }

    #[test]
    fn the_model_draws_over_every_background() {
        let mesh = cube();
        for background in BACKGROUNDS {
            let view = View {
                camera: Camera::fit(mesh.bounds()),
                background,
            };
            let drawn = render(&mesh, &view, FRAME);
            let bare = render(&Mesh::default(), &view, FRAME);
            let share = differing(&drawn, &bare) as f32 / FRAME.pixels() as f32;
            assert!(
                share > 0.05,
                "{} left only {share} of the frame changed",
                background.label()
            );
        }
    }
}
