//! The image a model is painted with: decoded once at load, sampled per pixel.
//!
//! Held as RGBA8 in one flat `Vec`, row 0 at the top — which is the order the
//! PNG decoder hands back and the order glTF's texture coordinates assume, so
//! nothing is flipped anywhere between the file and a sampled texel.
//!
//! ⚠️ Sampling wraps rather than clamps. The exporter writes `wrapS`/`wrapT` as
//! REPEAT and a fifth of real models have coordinates outside [0,1]; clamping
//! those smears the edge row across whole faces.

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

    /// The texel at a texture coordinate, nearest-neighbour and wrapping.
    ///
    /// `u` runs left to right and `v` top to bottom, so (0, 0) is the image's
    /// top-left corner — glTF's convention, not OpenGL's. Flip either and a
    /// model's face lands on the back of its head.
    pub fn sample(&self, u: f32, v: f32) -> Texel {
        let x = wrapped(u, self.width);
        let y = wrapped(v, self.height);
        let at = (y * self.width + x) * 4;
        Texel {
            r: self.pixels[at],
            g: self.pixels[at + 1],
            b: self.pixels[at + 2],
            a: self.pixels[at + 3],
        }
    }
}

/// A coordinate folded into the image, as REPEAT wrapping defines it.
///
/// A coordinate that is not finite lands on texel 0 rather than panicking: a
/// degenerate triangle can produce one, and a viewport that dies on a bad
/// model is worse than one that paints a stray pixel.
fn wrapped(value: f32, limit: usize) -> usize {
    if !value.is_finite() {
        return 0;
    }
    let fraction = value - value.floor();
    ((fraction * limit as f32) as usize).min(limit - 1)
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

    /// ⚠️ The orientation test. glTF puts (0, 0) at the image's *top* left, and
    /// a decoder that hands back rows bottom-up — or a sampler that swaps the
    /// axes — passes every coverage test and paints models wrong.
    #[test]
    fn the_origin_is_the_top_left_and_u_is_horizontal() {
        let texture = quadrants();
        assert_eq!(texture.sample(0.25, 0.25), RED, "top left");
        assert_eq!(texture.sample(0.75, 0.25), GREEN, "top right");
        assert_eq!(texture.sample(0.25, 0.75), BLUE, "bottom left");
        assert_eq!(texture.sample(0.75, 0.75), WHITE, "bottom right");
    }

    #[test]
    fn coordinates_outside_the_unit_square_wrap_rather_than_clamp() {
        let texture = quadrants();
        assert_eq!(texture.sample(1.25, 2.25), RED, "wrapped from above");
        assert_eq!(texture.sample(-0.75, -0.75), RED, "wrapped from below");
        assert_eq!(texture.sample(-0.25, 3.75), WHITE, "mixed signs");
        // Clamping would answer WHITE here; wrapping folds back to the origin.
        assert_eq!(texture.sample(2.0, 2.0), RED, "an exact multiple");
    }

    #[test]
    fn a_wild_coordinate_samples_inside_the_image_instead_of_panicking() {
        let texture = quadrants();
        for (u, v) in [
            (f32::NAN, 0.5),
            (0.5, f32::INFINITY),
            (f32::NEG_INFINITY, f32::NAN),
            (1e30, -1e30),
            (f32::MAX, f32::MIN),
        ] {
            let _ = texture.sample(u, v);
        }
    }

    #[test]
    fn something_that_is_not_an_image_is_refused_by_name() {
        let why = Texture::decode(&[0u8, 1, 2, 3]).expect_err("junk is not a png");
        assert!(why.contains("decoded"), "{why}");
    }
}
