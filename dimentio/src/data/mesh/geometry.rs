//! The arithmetic a mesh is made of: a point, a triangle's corners, a texture
//! coordinate, and the box a model occupies.
//!
//! Nothing here knows what a model, a material or a manifest is, which is what
//! lets the rasteriser and the effect renderer both build geometry out of it
//! without reaching back into the mesh reader.

/// A point in model space, and the arithmetic the renderer needs from it.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Vec3 {
    pub const ZERO: Self = Self {
        x: 0.0,
        y: 0.0,
        z: 0.0,
    };

    pub const fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    pub fn dot(self, other: Self) -> f32 {
        self.x * other.x + self.y * other.y + self.z * other.z
    }

    pub fn cross(self, other: Self) -> Self {
        Self::new(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )
    }

    pub fn length(self) -> f32 {
        self.dot(self).sqrt()
    }

    pub fn scaled(self, factor: f32) -> Self {
        Self::new(self.x * factor, self.y * factor, self.z * factor)
    }

    /// Unit length, or zero when the vector has no direction to preserve.
    /// Returning zero rather than NaN keeps a degenerate face out of the
    /// shading maths instead of poisoning the pixels it touches.
    pub fn normalised(self) -> Self {
        let length = self.length();
        if length > 0.0 {
            self.scaled(1.0 / length)
        } else {
            Self::ZERO
        }
    }
}

impl std::ops::Add for Vec3 {
    type Output = Self;
    fn add(self, other: Self) -> Self {
        Self::new(self.x + other.x, self.y + other.y, self.z + other.z)
    }
}

impl std::ops::Sub for Vec3 {
    type Output = Self;
    fn sub(self, other: Self) -> Self {
        Self::new(self.x - other.x, self.y - other.y, self.z - other.z)
    }
}

/// Three indices into a mesh's positions.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Face {
    pub a: usize,
    pub b: usize,
    pub c: usize,
}

/// Where a vertex lands on its texture. glTF's convention: (0, 0) is the
/// image's top-left corner, and both axes run outside [0, 1] wherever the art
/// tiles.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Uv {
    pub u: f32,
    pub v: f32,
}

impl Uv {
    pub const fn new(u: f32, v: f32) -> Self {
        Self { u, v }
    }
}

/// The box a model occupies, which is what the camera frames itself against.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Bounds {
    pub min: Vec3,
    pub max: Vec3,
}

impl Bounds {
    /// The box around every point some face refers to.
    ///
    /// ⚠️ Unreferenced positions are excluded, and that is the whole point.
    /// 733 of the 864 models in a real export carry positions no face uses,
    /// and 15 of them draw a handful of triangles out of a pool spanning
    /// hundreds of units — `p_big_mario` uses 3 of its 2,255 positions. A box
    /// around all of them frames empty space and puts the geometry below one
    /// pixel, which looks exactly like a renderer that draws nothing.
    pub(super) fn around(points: &[Vec3], faces: &[Face]) -> Self {
        let mut span: Option<Self> = None;
        let mut swallow = |point: Vec3| {
            span = Some(match span {
                None => Self {
                    min: point,
                    max: point,
                },
                Some(mut bounds) => {
                    bounds.min.x = bounds.min.x.min(point.x);
                    bounds.min.y = bounds.min.y.min(point.y);
                    bounds.min.z = bounds.min.z.min(point.z);
                    bounds.max.x = bounds.max.x.max(point.x);
                    bounds.max.y = bounds.max.y.max(point.y);
                    bounds.max.z = bounds.max.z.max(point.z);
                    bounds
                }
            });
        };

        if faces.is_empty() {
            // Nothing will be drawn, so every point is as good a guess as any.
            points.iter().copied().for_each(&mut swallow);
        } else {
            for face in faces {
                for index in [face.a, face.b, face.c] {
                    if let Some(&point) = points.get(index) {
                        swallow(point);
                    }
                }
            }
        }
        span.unwrap_or_default()
    }

    pub fn centre(self) -> Vec3 {
        (self.min + self.max).scaled(0.5)
    }

    /// Radius of the sphere that contains the box.
    pub fn radius(self) -> f32 {
        (self.max - self.min).scaled(0.5).length()
    }
}
