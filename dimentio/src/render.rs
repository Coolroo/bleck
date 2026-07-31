//! A software rasteriser: a mesh and a camera in, RGBA pixels out.
//!
//! ⚠️ There is no GPU here on purpose. Every pixel below is produced by plain
//! arithmetic against a `Vec<u8>`, so the tests at the foot of this file can
//! assert on the result with no window, no driver and no display — which is the
//! only way this can be checked on a machine that cannot show, or capture, its
//! own screen. Moving it onto `wgpu` would remove that.
//!
//! ⚠️ Nothing is back-face culled. Exported meshes carry no guaranteed winding,
//! and culling one would open holes in it; hidden surfaces are removed by the
//! depth buffer alone, and every face is lit from whichever side is visible.
//! Remove the two-sided flip in `Basis::shade` and half of a model goes black.
//!
//! ⚠️ The light is fixed in *view* space, so it travels with the camera. A
//! world-fixed light is more realistic and leaves the far side of a model an
//! unreadable silhouette, which is the wrong trade for something whose whole
//! job is to let a model be looked at.

use crate::mesh::{Bounds, Mesh, Vec3};

/// Vertical field of view, in radians. ~40°.
const FOV_Y: f32 = 0.7;

/// How much wider than the model the fitted frame is. 1.0 would touch the
/// edges, and a model that touches the edge reads as clipped.
const FRAME_MARGIN: f32 = 1.3;

/// Anything at or in front of the camera plane is dropped. A projected vertex
/// at z <= 0 has no meaningful screen position, and interpolating through it
/// smears a triangle across the frame.
const NEAR: f32 = 1e-4;

/// Pitch stops just short of the poles: at exactly ±90° the view direction is
/// parallel to world up, the cross product that builds `right` collapses, and
/// the whole basis goes to zero.
const PITCH_LIMIT: f32 = 1.553;

/// A model with no size still needs a camera distance that is not zero.
const MIN_RADIUS: f32 = 1e-3;

/// Light that reaches a face turned fully away from it, so nothing is pure
/// black and a silhouette still shows its shape.
const AMBIENT: f32 = 0.25;

/// Up in model space. `bleck` exports Y-up.
const WORLD_UP: Vec3 = Vec3::new(0.0, 1.0, 0.0);

/// Light direction in view space: over the viewer's left shoulder.
const LIGHT: Vec3 = Vec3::new(-0.4, 0.6, -0.7);

/// Untextured surface colour. Models export without materials, so every face
/// differs only by how it is lit.
const SURFACE: Rgba = Rgba::new(214, 208, 196);

/// Pixel dimensions of a render.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Size {
    pub width: usize,
    pub height: usize,
}

impl Size {
    pub const fn new(width: usize, height: usize) -> Self {
        Self { width, height }
    }

    pub fn pixels(self) -> usize {
        self.width * self.height
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rgba {
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: u8,
}

impl Rgba {
    pub const fn new(r: u8, g: u8, b: u8) -> Self {
        Self { r, g, b, a: 255 }
    }

    /// Scaled towards black. Saturating, so an intensity above 1 clamps
    /// instead of wrapping round to a dark pixel.
    fn shaded(self, intensity: f32) -> Self {
        let scale = |channel: u8| (f32::from(channel) * intensity).clamp(0.0, 255.0) as u8;
        Self { r: scale(self.r), g: scale(self.g), b: scale(self.b), a: self.a }
    }
}

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
pub const BACKGROUNDS: [Background; 3] =
    [Background::DarkGrey, Background::Checkerboard, Background::Gradient];

/// Edge of one checkerboard square, in pixels.
const CHECK: usize = 16;

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
struct Basis {
    eye: Vec3,
    right: Vec3,
    up: Vec3,
    forward: Vec3,
}

impl Basis {
    fn of(camera: &Camera) -> Self {
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

    fn to_view(&self, point: Vec3) -> Vec3 {
        let offset = point - self.eye;
        Vec3::new(
            offset.dot(self.right),
            offset.dot(self.up),
            offset.dot(self.forward),
        )
    }

    /// Flat shading from the face's own normal — one colour for the whole
    /// triangle, which is what makes facets readable on an untextured model.
    fn shade(&self, corners: &[Vec3; 3]) -> Rgba {
        let normal = (corners[1] - corners[0])
            .cross(corners[2] - corners[0])
            .normalised();
        let mut facing = Vec3::new(
            normal.dot(self.right),
            normal.dot(self.up),
            normal.dot(self.forward),
        );
        // Two-sided: a normal pointing away from the viewer is turned round,
        // so a face lit from behind is shaded rather than left black.
        if facing.z > 0.0 {
            facing = facing.scaled(-1.0);
        }
        let lit = facing.dot(LIGHT.normalised()).max(0.0);
        SURFACE.shaded(AMBIENT + (1.0 - AMBIENT) * lit)
    }
}

/// A projected vertex. `inv_z` rather than z because 1/z is what interpolates
/// linearly across a triangle in screen space; interpolating z does not, and
/// the error shows up as surfaces punching through each other.
#[derive(Debug, Clone, Copy)]
struct Point {
    x: f32,
    y: f32,
    inv_z: f32,
}

struct Lens {
    scale_x: f32,
    scale_y: f32,
    half_width: f32,
    half_height: f32,
}

impl Lens {
    fn new(fov_y: f32, size: Size) -> Self {
        let scale_y = 1.0 / (fov_y * 0.5).tan();
        let aspect = size.width as f32 / size.height.max(1) as f32;
        Self {
            scale_x: scale_y / aspect.max(f32::EPSILON),
            scale_y,
            half_width: size.width as f32 * 0.5,
            half_height: size.height as f32 * 0.5,
        }
    }

    fn project(&self, view: Vec3) -> Point {
        let inv_z = 1.0 / view.z;
        Point {
            x: (view.x * self.scale_x * inv_z + 1.0) * self.half_width,
            y: (1.0 - view.y * self.scale_y * inv_z) * self.half_height,
            inv_z,
        }
    }
}

/// An RGBA8 frame, in the layout `egui::ColorImage::from_rgba_unmultiplied`
/// wants: four bytes per pixel, rows top to bottom.
#[derive(Debug, Clone)]
pub struct Image {
    size: Size,
    pixels: Vec<u8>,
}

impl Image {
    fn filled(size: Size, background: Background) -> Self {
        let mut pixels = Vec::with_capacity(size.pixels() * 4);
        for y in 0..size.height {
            for x in 0..size.width {
                let colour = background.pixel(x, y, size);
                pixels.extend_from_slice(&[colour.r, colour.g, colour.b, colour.a]);
            }
        }
        Self { size, pixels }
    }

    pub fn size(&self) -> Size {
        self.size
    }

    pub fn as_rgba(&self) -> &[u8] {
        &self.pixels
    }

    pub fn pixel(&self, x: usize, y: usize) -> Rgba {
        let at = (y * self.size.width + x) * 4;
        Rgba {
            r: self.pixels[at],
            g: self.pixels[at + 1],
            b: self.pixels[at + 2],
            a: self.pixels[at + 3],
        }
    }

    fn set(&mut self, x: usize, y: usize, colour: Rgba) {
        let at = (y * self.size.width + x) * 4;
        self.pixels[at] = colour.r;
        self.pixels[at + 1] = colour.g;
        self.pixels[at + 2] = colour.b;
        self.pixels[at + 3] = colour.a;
    }
}

/// Camera plus backdrop: everything about a render that is not the mesh.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct View {
    pub camera: Camera,
    pub background: Background,
}

impl View {
    /// A view that frames `bounds` on the default backdrop.
    pub fn fitted(bounds: Bounds) -> Self {
        Self { camera: Camera::fit(bounds), background: Background::default() }
    }
}

/// Draw `mesh` through `view` at `size`.
///
/// Always returns a full frame: an empty mesh, a zero size or geometry entirely
/// behind the camera produce the background rather than a failure, because the
/// caller is a window that has to draw something.
pub fn render(mesh: &Mesh, view: &View, size: Size) -> Image {
    let mut image = Image::filled(size, view.background);
    if size.pixels() == 0 || mesh.is_empty() {
        return image;
    }

    let basis = Basis::of(&view.camera);
    let lens = Lens::new(view.camera.fov_y, size);
    let mut depth = vec![f32::NEG_INFINITY; size.pixels()];
    let positions = mesh.positions();

    for face in mesh.faces() {
        let (Some(&a), Some(&b), Some(&c)) = (
            positions.get(face.a),
            positions.get(face.b),
            positions.get(face.c),
        ) else {
            continue;
        };
        let corners = [a, b, c];
        let viewed = corners.map(|corner| basis.to_view(corner));
        if viewed.iter().any(|corner| corner.z <= NEAR) {
            continue;
        }
        let screen = viewed.map(|corner| lens.project(corner));
        raster(&mut image, &mut depth, &screen, basis.shade(&corners));
    }
    image
}

/// Half the cross product of two triangle edges: positive on one side of the
/// line a→b, negative on the other. Doubles as the barycentric weight.
fn edge(a: Point, b: Point, x: f32, y: f32) -> f32 {
    (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x)
}

/// The pixel columns or rows a triangle can touch, clipped to the frame.
struct Span {
    start: usize,
    end: usize,
}

fn span(low: f32, high: f32, limit: usize) -> Option<Span> {
    if !low.is_finite() || !high.is_finite() || high < 0.0 || low >= limit as f32 {
        return None;
    }
    let start = low.floor().max(0.0) as usize;
    let end = (high.ceil() as usize).min(limit.saturating_sub(1));
    if start > end {
        return None;
    }
    Some(Span { start, end })
}

fn raster(image: &mut Image, depth: &mut [f32], triangle: &[Point; 3], colour: Rgba) {
    let area = edge(triangle[0], triangle[1], triangle[2].x, triangle[2].y);
    if area.abs() < 1e-9 {
        return;
    }
    // Winding is not guaranteed, so the sign is normalised instead of culled.
    let turn = if area < 0.0 { -1.0 } else { 1.0 };
    let area = area * turn;

    let xs = triangle.map(|corner| corner.x);
    let ys = triangle.map(|corner| corner.y);
    let size = image.size();
    let (Some(columns), Some(rows)) = (
        span(fold_min(&xs), fold_max(&xs), size.width),
        span(fold_min(&ys), fold_max(&ys), size.height),
    ) else {
        return;
    };

    for y in rows.start..=rows.end {
        let at_y = y as f32 + 0.5;
        for x in columns.start..=columns.end {
            let at_x = x as f32 + 0.5;
            let w0 = edge(triangle[1], triangle[2], at_x, at_y) * turn;
            let w1 = edge(triangle[2], triangle[0], at_x, at_y) * turn;
            let w2 = edge(triangle[0], triangle[1], at_x, at_y) * turn;
            if w0 < 0.0 || w1 < 0.0 || w2 < 0.0 {
                continue;
            }
            let near = (w0 * triangle[0].inv_z
                + w1 * triangle[1].inv_z
                + w2 * triangle[2].inv_z)
                / area;
            let slot = y * size.width + x;
            // Larger 1/z is nearer, so this keeps the closest fragment
            // regardless of the order faces arrive in.
            if near <= depth[slot] {
                continue;
            }
            depth[slot] = near;
            image.set(x, y, colour);
        }
    }
}

fn fold_min(values: &[f32; 3]) -> f32 {
    values.iter().copied().fold(f32::INFINITY, f32::min)
}

fn fold_max(values: &[f32; 3]) -> f32 {
    values.iter().copied().fold(f32::NEG_INFINITY, f32::max)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mesh::Mesh;

    /// A cube of side 2 about the origin. Its winding is deliberately
    /// inconsistent, which is what a face-culling renderer would show holes in.
    const CUBE: &str = "\
v -1 -1 -1
v 1 -1 -1
v 1 1 -1
v -1 1 -1
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 1 2 3
f 1 3 4
f 5 6 7
f 5 7 8
f 1 2 6
f 1 6 5
f 2 3 7
f 2 7 6
f 3 4 8
f 3 8 7
f 4 1 5
f 4 5 8
";

    const FRAME: Size = Size::new(200, 200);

    fn cube() -> Mesh {
        Mesh::parse(CUBE).expect("the cube parses")
    }

    fn flat(camera: Camera) -> View {
        View { camera, background: Background::DarkGrey }
    }

    /// Pixels that are not the flat background colour — i.e. the model.
    fn covered(image: &Image) -> usize {
        let sky = Background::DarkGrey.pixel(0, 0, image.size());
        let mut count = 0;
        for y in 0..image.size().height {
            for x in 0..image.size().width {
                if image.pixel(x, y) != sky {
                    count += 1;
                }
            }
        }
        count
    }

    fn differing(one: &Image, two: &Image) -> usize {
        one.as_rgba()
            .chunks(4)
            .zip(two.as_rgba().chunks(4))
            .filter(|(a, b)| a != b)
            .count()
    }

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

    /// Camera on +Z looking down -Z, so a test can place geometry at a known
    /// depth without solving for the orbit.
    fn head_on() -> Camera {
        Camera {
            target: Vec3::ZERO,
            distance: 8.0,
            yaw: 0.0,
            pitch: 0.0,
            fov_y: FOV_Y,
        }
    }

    /// Facing the camera at z = +1, covering the middle of the frame.
    const NEAR_QUAD: &str = "v -2 -2 1\nv 2 -2 1\nv 2 2 1\nv -2 2 1\nf 1 2 3 4\n";

    /// Tilted, and behind the near quad everywhere it overlaps it.
    const FAR_QUAD: &str = "v -2 -2 -1\nv 2 -2 -5\nv 2 2 -5\nv -2 2 -1\nf 1 2 3 4\n";

    fn centre_of(text: &str) -> Rgba {
        let mesh = Mesh::parse(text).expect("quad parses");
        let image = render(&mesh, &flat(head_on()), FRAME);
        image.pixel(FRAME.width / 2, FRAME.height / 2)
    }

    #[test]
    fn the_depth_buffer_keeps_the_nearer_face_whatever_the_draw_order() {
        // ⚠️ The instrument first: unless the two quads shade differently,
        // every assertion below would pass without a depth buffer at all.
        let near = centre_of(NEAR_QUAD);
        let far = centre_of(FAR_QUAD);
        let sky = Background::DarkGrey.pixel(0, 0, FRAME);
        assert_ne!(near, sky, "the near quad did not draw");
        assert_ne!(far, sky, "the far quad did not draw");
        assert_ne!(near, far, "the two quads are indistinguishable");

        // Far face second: a painter's-algorithm renderer would end up
        // showing it, because it is drawn last.
        let mut both = String::from(NEAR_QUAD);
        both.push_str(&shifted(FAR_QUAD, 4));
        assert_eq!(centre_of(&both), near, "the far quad painted over the near");

        let mut reversed = String::from(FAR_QUAD);
        reversed.push_str(&shifted(NEAR_QUAD, 4));
        assert_eq!(centre_of(&reversed), near, "draw order changed the result");
    }

    /// Re-index a mesh's faces so it can be appended after `offset` vertices.
    fn shifted(text: &str, offset: usize) -> String {
        text.lines()
            .map(|line| {
                if let Some(face) = line.strip_prefix("f ") {
                    let corners: Vec<String> = face
                        .split_whitespace()
                        .map(|index| {
                            (index.parse::<usize>().expect("index") + offset).to_string()
                        })
                        .collect();
                    format!("f {}\n", corners.join(" "))
                } else {
                    format!("{line}\n")
                }
            })
            .collect()
    }

    #[test]
    fn an_empty_mesh_renders_only_the_background() {
        let mesh = Mesh::parse("").expect("nothing parses");
        let image = render(&mesh, &flat(Camera::fit(mesh.bounds())), FRAME);
        assert_eq!(covered(&image), 0);
        assert_eq!(image.as_rgba().len(), FRAME.pixels() * 4);
    }

    #[test]
    fn a_zero_area_face_draws_nothing() {
        let collapsed = Mesh::parse("v 0 0 0\nv 1 1 1\nv 2 2 2\nf 1 2 3\n").expect("parses");
        let image = render(&collapsed, &flat(Camera::fit(collapsed.bounds())), FRAME);
        assert_eq!(covered(&image), 0);

        let point = Mesh::parse("v 1 1 1\nv 1 1 1\nv 1 1 1\nf 1 2 3\n").expect("parses");
        let image = render(&point, &flat(Camera::fit(point.bounds())), FRAME);
        assert_eq!(covered(&image), 0);
    }

    #[test]
    fn geometry_behind_the_camera_is_dropped() {
        // The camera sits at z = 8 looking towards -z; this quad is behind it.
        let mesh = Mesh::parse("v -2 -2 40\nv 2 -2 40\nv 2 2 40\nf 1 2 3\n").expect("parses");
        assert_eq!(covered(&render(&mesh, &flat(head_on()), FRAME)), 0);
    }

    #[test]
    fn a_zero_sized_frame_is_empty_rather_than_a_panic() {
        let mesh = cube();
        let view = flat(Camera::fit(mesh.bounds()));
        assert!(render(&mesh, &view, Size::new(0, 0)).as_rgba().is_empty());
        assert!(render(&mesh, &view, Size::new(0, 32)).as_rgba().is_empty());
        assert_eq!(render(&mesh, &view, Size::new(1, 1)).as_rgba().len(), 4);
    }

    #[test]
    fn each_background_looks_different_from_the_others() {
        let empty = Mesh::default();
        let frames: Vec<Image> = BACKGROUNDS
            .iter()
            .map(|&background| {
                let view = View { camera: Camera::default(), background };
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
            let view = View { camera: Camera::fit(mesh.bounds()), background };
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

    #[test]
    fn shading_darkens_a_face_turned_away_from_the_light() {
        let basis = Basis::of(&head_on());
        let facing = basis.shade(&[
            Vec3::new(-1.0, -1.0, 0.0),
            Vec3::new(1.0, -1.0, 0.0),
            Vec3::new(1.0, 1.0, 0.0),
        ]);
        // Same triangle wound the other way: two-sided shading must give the
        // same colour, or half a model with mixed winding would go dark.
        let reversed = basis.shade(&[
            Vec3::new(1.0, 1.0, 0.0),
            Vec3::new(1.0, -1.0, 0.0),
            Vec3::new(-1.0, -1.0, 0.0),
        ]);
        assert_eq!(facing, reversed);

        // Edge-on to the camera, so it catches almost none of the light.
        let edge_on = basis.shade(&[
            Vec3::new(0.0, -1.0, -1.0),
            Vec3::new(0.0, -1.0, 1.0),
            Vec3::new(0.0, 1.0, 1.0),
        ]);
        assert!(edge_on.r < facing.r, "{edge_on:?} vs {facing:?}");
        assert!(edge_on.r >= SURFACE.shaded(AMBIENT).r, "ambient floor lost");
    }
}
