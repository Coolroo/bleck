//! The image a model is painted with: decoded once at load, sampled per pixel.
//!
//! Held as RGBA8 in one flat `Vec`, row 0 at the top — which is the order the
//! PNG decoder hands back and the order glTF's texture coordinates assume, so
//! nothing is flipped anywhere between the file and a sampled texel.
//!
//! ⚠️ **How a coordinate outside [0,1] is folded is read from the file, not
//! chosen here** (D247). The exporter used to write REPEAT for everything and
//! the game clamps 92% of its layers; a `Sampling` carries what the glTF
//! sampler said, and REPEAT is only the fallback for a file that says nothing.
//!
//! `Sampling` also carries the `KHR_texture_transform` a layer may declare —
//! offset, rotation and scale about the origin, applied to the coordinate
//! before it is folded.

/// One texel of a decoded image.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Texel {
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: u8,
}

/// A decoded RGBA8 image, addressable by texture coordinate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Texture {
    width: usize,
    height: usize,
    pixels: Vec<u8>,
}

impl Texture {
    /// Decode PNG bytes.
    ///
    /// An image with no pixels is refused: it has no texel to return, and a
    /// sampler that has to invent one would paint every model the same colour
    /// while looking like it worked.
    pub fn decode(bytes: &[u8]) -> Result<Self, String> {
        let decoded = image::load_from_memory(bytes)
            .map_err(|why| format!("texture could not be decoded: {why}"))?
            .to_rgba8();
        let width = decoded.width() as usize;
        let height = decoded.height() as usize;
        if width == 0 || height == 0 {
            return Err("texture has no pixels".into());
        }
        Ok(Self {
            width,
            height,
            pixels: decoded.into_raw(),
        })
    }

    pub fn width(&self) -> usize {
        self.width
    }

    pub fn height(&self) -> usize {
        self.height
    }

    /// The texel at a texture coordinate, nearest-neighbour.
    ///
    /// `u` runs left to right and `v` top to bottom, so (0, 0) is the image's
    /// top-left corner — glTF's convention, not OpenGL's. Flip either and a
    /// model's face lands on the back of its head.
    pub fn sample(&self, u: f32, v: f32, how: &Sampling) -> Texel {
        let (u, v) = how.transform.apply(u, v);
        let x = how.wrap_s.fold(u, self.width);
        let y = how.wrap_t.fold(v, self.height);
        let at = (y * self.width + x) * 4;
        Texel {
            r: self.pixels[at],
            g: self.pixels[at + 1],
            b: self.pixels[at + 2],
            a: self.pixels[at + 3],
        }
    }
}

/// What a coordinate outside the image does, per axis.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Wrap {
    /// The edge row is held, which is what 92% of the disc's layers ask for.
    Clamp,
    #[default]
    Repeat,
    Mirror,
}

impl Wrap {
    /// A glTF sampler's `wrapS`/`wrapT` enum. Anything else falls back to the
    /// specification's own default rather than refusing the file.
    pub fn of(mode: u64) -> Self {
        match mode {
            33071 => Self::Clamp,
            33648 => Self::Mirror,
            _ => Self::Repeat,
        }
    }

    /// A coordinate folded into `limit` texels.
    ///
    /// A coordinate that is not finite lands on texel 0 rather than panicking:
    /// a degenerate triangle can produce one, and a viewport that dies on a bad
    /// model is worse than one that paints a stray pixel.
    pub fn fold(self, value: f32, limit: usize) -> usize {
        if !value.is_finite() {
            return 0;
        }
        let folded = match self {
            Self::Clamp => value.clamp(0.0, 1.0 - f32::EPSILON),
            Self::Repeat => value - value.floor(),
            Self::Mirror => {
                let period = value.rem_euclid(2.0);
                if period > 1.0 {
                    2.0 - period
                } else {
                    period
                }
            }
        };
        ((folded * limit as f32) as usize).min(limit - 1)
    }
}

/// A layer's `KHR_texture_transform`, as the extension defines it: scale, then
/// rotate about the origin, then offset.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Transform {
    pub offset: [f32; 2],
    pub rotation: f32,
    pub scale: [f32; 2],
}

impl Default for Transform {
    fn default() -> Self {
        Self {
            offset: [0.0, 0.0],
            rotation: 0.0,
            scale: [1.0, 1.0],
        }
    }
}

impl Transform {
    pub fn is_identity(&self) -> bool {
        *self == Self::default()
    }

    /// The extension's own matrix, applied to one coordinate.
    pub fn apply(&self, u: f32, v: f32) -> (f32, f32) {
        if self.is_identity() {
            return (u, v);
        }
        let (sin, cos) = self.rotation.sin_cos();
        let (u, v) = (u * self.scale[0], v * self.scale[1]);
        (
            cos * u + sin * v + self.offset[0],
            -sin * u + cos * v + self.offset[1],
        )
    }
}

/// Everything between a texture coordinate and a texel that is not the image.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Sampling {
    pub wrap_s: Wrap,
    pub wrap_t: Wrap,
    pub transform: Transform,
}

/// Encode texels as PNG, so the loader tests can feed the decoder a real file
/// rather than a hand-written byte string.
#[cfg(test)]
pub(crate) fn png(width: u32, height: u32, texels: &[Texel]) -> Vec<u8> {
    let mut raw = Vec::with_capacity(texels.len() * 4);
    for texel in texels {
        raw.extend_from_slice(&[texel.r, texel.g, texel.b, texel.a]);
    }
    let buffer = image::RgbaImage::from_raw(width, height, raw).expect("test image");
    let mut out = std::io::Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(buffer)
        .write_to(&mut out, image::ImageFormat::Png)
        .expect("test png");
    out.into_inner()
}

#[cfg(test)]
mod tests {
    use super::*;

    const RED: Texel = Texel {
        r: 255,
        g: 0,
        b: 0,
        a: 255,
    };
    const GREEN: Texel = Texel {
        r: 0,
        g: 255,
        b: 0,
        a: 255,
    };
    const BLUE: Texel = Texel {
        r: 0,
        g: 0,
        b: 255,
        a: 255,
    };
    const WHITE: Texel = Texel {
        r: 255,
        g: 255,
        b: 255,
        a: 255,
    };

    /// Red top-left, green top-right, blue bottom-left, white bottom-right.
    fn quadrants() -> Texture {
        Texture::decode(&png(2, 2, &[RED, GREEN, BLUE, WHITE])).expect("2x2 png")
    }

    #[test]
    fn a_png_round_trips_through_the_decoder() {
        let texture = quadrants();
        assert_eq!(texture.width(), 2);
        assert_eq!(texture.height(), 2);
    }

    /// Whatever a glTF file that names no sampler gets: the specification's own
    /// default, which is REPEAT on both axes.
    fn plain() -> Sampling {
        Sampling::default()
    }

    /// ⚠️ The orientation test. glTF puts (0, 0) at the image's *top* left, and
    /// a decoder that hands back rows bottom-up — or a sampler that swaps the
    /// axes — passes every coverage test and paints models wrong.
    #[test]
    fn the_origin_is_the_top_left_and_u_is_horizontal() {
        let texture = quadrants();
        assert_eq!(texture.sample(0.25, 0.25, &plain()), RED, "top left");
        assert_eq!(texture.sample(0.75, 0.25, &plain()), GREEN, "top right");
        assert_eq!(texture.sample(0.25, 0.75, &plain()), BLUE, "bottom left");
        assert_eq!(texture.sample(0.75, 0.75, &plain()), WHITE, "bottom right");
    }

    #[test]
    fn coordinates_outside_the_unit_square_wrap_rather_than_clamp() {
        let texture = quadrants();
        let how = plain();
        assert_eq!(texture.sample(1.25, 2.25, &how), RED, "wrapped from above");
        assert_eq!(
            texture.sample(-0.75, -0.75, &how),
            RED,
            "wrapped from below"
        );
        assert_eq!(texture.sample(-0.25, 3.75, &how), WHITE, "mixed signs");
        // Clamping would answer WHITE here; wrapping folds back to the origin.
        assert_eq!(texture.sample(2.0, 2.0, &how), RED, "an exact multiple");
    }

    /// ✅ **The mode is read from the file** (D247), and the three GX offers
    /// answer differently at the same coordinate — which is what makes reading
    /// it worth doing rather than picking one.
    #[test]
    fn the_three_wrap_modes_disagree_where_it_matters() {
        let texture = quadrants();
        let at = |wrap| {
            texture.sample(
                1.25,
                0.25,
                &Sampling {
                    wrap_s: wrap,
                    ..Sampling::default()
                },
            )
        };
        assert_eq!(at(Wrap::Repeat), RED, "1.25 folds back to 0.25");
        assert_eq!(at(Wrap::Clamp), GREEN, "clamping holds the right-hand edge");
        assert_eq!(at(Wrap::Mirror), GREEN, "mirroring reflects to 0.75");
    }

    #[test]
    fn a_clamped_axis_holds_the_edge_at_both_ends() {
        let texture = quadrants();
        let how = Sampling {
            wrap_s: Wrap::Clamp,
            wrap_t: Wrap::Clamp,
            ..Sampling::default()
        };
        assert_eq!(texture.sample(-5.0, -5.0, &how), RED, "below");
        assert_eq!(texture.sample(9.0, 9.0, &how), WHITE, "above");
    }

    /// ⚠️ **The transform is applied before the fold, not after.** A layer that
    /// scales U by -1 is a mirrored door on the disc; folding first would leave
    /// it unmirrored and it would still look like a door.
    #[test]
    fn a_texture_transform_moves_the_coordinate_before_it_is_folded() {
        let texture = quadrants();
        let mirrored = Sampling {
            transform: Transform {
                scale: [-1.0, 1.0],
                ..Transform::default()
            },
            ..Sampling::default()
        };
        assert_eq!(texture.sample(0.25, 0.25, &Sampling::default()), RED);
        assert_eq!(texture.sample(0.25, 0.25, &mirrored), GREEN, "-0.25 wraps");
        assert!(Transform::default().is_identity());
        assert!(!mirrored.transform.is_identity());
    }

    #[test]
    fn a_wild_coordinate_samples_inside_the_image_instead_of_panicking() {
        let texture = quadrants();
        for wrap in [Wrap::Clamp, Wrap::Repeat, Wrap::Mirror] {
            let how = Sampling {
                wrap_s: wrap,
                wrap_t: wrap,
                ..Sampling::default()
            };
            for (u, v) in [
                (f32::NAN, 0.5),
                (0.5, f32::INFINITY),
                (f32::NEG_INFINITY, f32::NAN),
                (1e30, -1e30),
                (f32::MAX, f32::MIN),
            ] {
                let _ = texture.sample(u, v, &how);
            }
        }
    }

    #[test]
    fn something_that_is_not_an_image_is_refused_by_name() {
        let why = Texture::decode(&[0u8, 1, 2, 3]).expect_err("junk is not a png");
        assert!(why.contains("decoded"), "{why}");
    }
}
