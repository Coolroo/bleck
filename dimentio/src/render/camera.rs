//! Where the camera is, and how a point in model space reaches the screen.
//!
//! An orbit rather than a free camera: dragging then has somewhere obvious to
//! write to, and no input can put the view somewhere it cannot come back from.

use super::Size;
use crate::data::mesh::{Bounds, Vec3};

/// Vertical field of view, in radians. ~40°.
pub(super) const FOV_Y: f32 = 0.7;

/// How much wider than the model the fitted frame is. 1.0 would touch the
/// edges, and a model that touches the edge reads as clipped.
const FRAME_MARGIN: f32 = 1.3;

/// Pitch stops just short of the poles: at exactly ±90° the view direction is
/// parallel to world up, the cross product that builds `right` collapses, and
/// the whole basis goes to zero.
const PITCH_LIMIT: f32 = 1.553;

/// A model with no size still needs a camera distance that is not zero.
const MIN_RADIUS: f32 = 1e-3;

/// Up in model space. `bleck` exports Y-up.
const WORLD_UP: Vec3 = Vec3::new(0.0, 1.0, 0.0);

/// Where the camera is, expressed as an orbit so that dragging has somewhere
/// obvious to write to.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Camera {
    pub target: Vec3,
    pub distance: f32,
    pub yaw: f32,
    pub pitch: f32,
    pub fov_y: f32,
}

impl Default for Camera {
    fn default() -> Self {
        Self::fit(Bounds::default())
    }
}

impl Camera {
    /// Frame `bounds` completely, from a three-quarter view.
    ///
    /// ⚠️ Fitted against the *vertical* field of view only, so a viewport
    /// narrower than it is tall can crop the sides. Viewports are wider than
    /// they are tall in practice, and re-fitting on every resize would undo a
    /// user's zoom whenever they dragged the window edge.
    pub fn fit(bounds: Bounds) -> Self {
        let radius = bounds.radius().max(MIN_RADIUS);
        Self {
            target: bounds.centre(),
            distance: radius / (FOV_Y * 0.5).sin() * FRAME_MARGIN,
            yaw: 0.6,
            pitch: 0.35,
            fov_y: FOV_Y,
        }
    }

    /// Move around the target. Radians.
    pub fn orbit(&mut self, yaw: f32, pitch: f32) {
        self.yaw += yaw;
        self.pitch = (self.pitch + pitch).clamp(-PITCH_LIMIT, PITCH_LIMIT);
    }

    /// Multiply the orbit radius. Below 1 moves in, above 1 moves out; the
    /// clamp stops a fast scroll from reaching zero, which no zoom could undo.
    pub fn zoom(&mut self, factor: f32) {
        self.distance = (self.distance * factor).clamp(MIN_RADIUS, 1e9);
    }
}

/// The camera resolved into the vectors a projection actually uses. `forward`
/// is +z in view space, so depth grows away from the viewer.
pub(super) struct Basis {
    eye: Vec3,
    pub(super) right: Vec3,
    pub(super) up: Vec3,
    pub(super) forward: Vec3,
}

impl Basis {
    pub(super) fn of(camera: &Camera) -> Self {
        let (sin_yaw, cos_yaw) = camera.yaw.sin_cos();
        let (sin_pitch, cos_pitch) = camera.pitch.sin_cos();
        let offset = Vec3::new(cos_pitch * sin_yaw, sin_pitch, cos_pitch * cos_yaw);
        let forward = offset.scaled(-1.0);
        let right = forward.cross(WORLD_UP).normalised();
        Self {
            eye: camera.target + offset.scaled(camera.distance),
            right,
            up: right.cross(forward),
            forward,
        }
    }

    pub(super) fn to_view(&self, point: Vec3) -> Vec3 {
        let offset = point - self.eye;
        Vec3::new(
            offset.dot(self.right),
            offset.dot(self.up),
            offset.dot(self.forward),
        )
    }
}

/// A projected vertex. `inv_z` rather than z because 1/z is what interpolates
/// linearly across a triangle in screen space; interpolating z does not, and
/// the error shows up as surfaces punching through each other.
#[derive(Debug, Clone, Copy)]
pub(super) struct Point {
    pub(super) x: f32,
    pub(super) y: f32,
    pub(super) inv_z: f32,
}

pub(super) struct Lens {
    scale_x: f32,
    scale_y: f32,
    half_width: f32,
    half_height: f32,
}

impl Lens {
    pub(super) fn new(fov_y: f32, size: Size) -> Self {
        let scale_y = 1.0 / (fov_y * 0.5).tan();
        let aspect = size.width as f32 / size.height.max(1) as f32;
        Self {
            scale_x: scale_y / aspect.max(f32::EPSILON),
            scale_y,
            half_width: size.width as f32 * 0.5,
            half_height: size.height as f32 * 0.5,
        }
    }

    pub(super) fn project(&self, view: Vec3) -> Point {
        let inv_z = 1.0 / view.z;
        Point {
            x: (view.x * self.scale_x * inv_z + 1.0) * self.half_width,
            y: (1.0 - view.y * self.scale_y * inv_z) * self.half_height,
            inv_z,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::mesh::Mesh;
    use crate::render::fixtures::{covered, cube, differing, flat, FRAME};
    use crate::render::{render, Background};

    #[test]
    fn a_fitted_cube_covers_a_plausible_share_of_the_frame() {
        let mesh = cube();
        let image = render(&mesh, &flat(Camera::fit(mesh.bounds())), FRAME);
        let share = covered(&image) as f32 / FRAME.pixels() as f32;
        assert!(
            (0.10..0.55).contains(&share),
            "cube covered {share} of the frame"
        );
    }

    #[test]
    fn a_fitted_model_never_reaches_the_corners() {
        let mesh = cube();
        let image = render(&mesh, &flat(Camera::fit(mesh.bounds())), FRAME);
        let sky = Background::DarkGrey.pixel(0, 0, FRAME);
        let last_x = FRAME.width - 1;
        let last_y = FRAME.height - 1;
        for (x, y) in [(0, 0), (last_x, 0), (0, last_y), (last_x, last_y)] {
            assert_eq!(image.pixel(x, y), sky, "corner {x},{y} was drawn over");
        }
    }

    #[test]
    fn a_fitted_model_sits_in_the_middle_of_the_frame() {
        let mesh = cube();
        let image = render(&mesh, &flat(Camera::fit(mesh.bounds())), FRAME);
        let sky = Background::DarkGrey.pixel(0, 0, FRAME);
        let (mut sum_x, mut sum_y, mut count) = (0.0f64, 0.0f64, 0.0f64);
        for y in 0..FRAME.height {
            for x in 0..FRAME.width {
                if image.pixel(x, y) != sky {
                    sum_x += x as f64;
                    sum_y += y as f64;
                    count += 1.0;
                }
            }
        }
        assert!(count > 0.0, "nothing was drawn");
        let (centre_x, centre_y) = (sum_x / count, sum_y / count);
        assert!(
            (centre_x - 99.5).abs() < 15.0 && (centre_y - 99.5).abs() < 15.0,
            "centroid at {centre_x},{centre_y}"
        );
    }

    #[test]
    fn orbiting_the_camera_changes_the_frame() {
        let mesh = cube();
        let fitted = Camera::fit(mesh.bounds());
        let before = render(&mesh, &flat(fitted), FRAME);
        let mut turned = fitted;
        turned.orbit(0.9, 0.2);
        let after = render(&mesh, &flat(turned), FRAME);
        let moved = differing(&before, &after);
        assert!(
            moved > FRAME.pixels() / 20,
            "only {moved} pixels changed after orbiting"
        );
    }

    #[test]
    fn pitch_stops_short_of_the_pole() {
        let mut camera = Camera::fit(cube().bounds());
        camera.orbit(0.0, 100.0);
        assert!(camera.pitch <= PITCH_LIMIT);
        // Past the pole the basis would collapse and nothing would draw.
        assert!(covered(&render(&cube(), &flat(camera), FRAME)) > 0);
    }

    #[test]
    fn zooming_in_covers_more_and_zooming_out_covers_less() {
        let mesh = cube();
        let fitted = Camera::fit(mesh.bounds());
        let middle = covered(&render(&mesh, &flat(fitted), FRAME));

        let mut near = fitted;
        near.zoom(0.5);
        let mut far = fitted;
        far.zoom(2.0);

        assert!(covered(&render(&mesh, &flat(near), FRAME)) > middle);
        assert!(covered(&render(&mesh, &flat(far), FRAME)) < middle);
    }

    /// ⚠️ Regression for 15 models in a real export that drew nothing. Their
    /// faces use a handful of positions out of thousands, and framing the
    /// whole position pool put the geometry under one pixel. A renderer that
    /// draws a speck and a renderer that draws nothing look identical.
    #[test]
    fn a_few_triangles_in_a_huge_position_pool_are_still_framed() {
        let mut text = String::from("v 0 0 0\nv 1 0 0\nv 0 1 0\n");
        for step in 0..500 {
            text.push_str(&format!("v {0} {0} {0}\n", step as f32 * 3.0));
        }
        text.push_str("f 1 2 3\n");

        let mesh = Mesh::parse(&text).expect("parses");
        assert_eq!(mesh.positions().len(), 503);
        let image = render(&mesh, &flat(Camera::fit(mesh.bounds())), FRAME);
        let share = covered(&image) as f32 / FRAME.pixels() as f32;
        assert!(share > 0.05, "the one triangle covered only {share}");
    }
}
