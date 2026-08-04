//! A software rasteriser: a mesh and a camera in, RGBA pixels out.
//!
//! ⚠️ There is no GPU here on purpose. Every pixel is produced by plain
//! arithmetic against a `Vec<u8>`, so the tests across this module can assert
//! on the result with no window, no driver and no display — which is the only
//! way this can be checked on a machine that cannot show, or capture, its own
//! screen. Moving it onto `wgpu` would remove that.
//!
//! `camera` places the viewer and projects; `raster` fills triangles, keeps the
//! depth buffer and shades; `background` draws what sits behind; `effect` turns
//! an effect's running parts into quads to hand back in. `render` and `scene`
//! below are the only ways in, and the test fixtures they need are shared with
//! all four.
//!
//! `wave` is the exception: a track has no geometry, so it fills columns into
//! the same `Image` directly rather than going through the triangle filler.

mod background;
mod camera;
pub mod effect;
mod raster;
pub mod wave;

pub use background::{Background, BACKGROUNDS};
pub use camera::Camera;
pub use raster::Image;
pub use raster::{FAINT_CUTOFF, MASK_CUTOFF};

use crate::data::mesh::Mesh;
use camera::{Basis, Lens};

/// Anything at or in front of the camera plane is dropped. A projected vertex
/// at z <= 0 has no meaningful screen position, and interpolating through it
/// smears a triangle across the frame.
const NEAR: f32 = 1e-4;

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
        Self {
            r: scale(self.r),
            g: scale(self.g),
            b: scale(self.b),
            a: self.a,
        }
    }
}

/// Camera plus backdrop: everything about a render that is not the mesh.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct View {
    pub camera: Camera,
    pub background: Background,
}

/// One drawable in a scene: geometry, plus the colour its untextured faces
/// take.
///
/// A mesh that carries a texture is painted with it and ignores `flat`; a mesh
/// that does not is filled with `flat` and shaded by the same lighting term.
#[derive(Debug, Clone, Copy)]
pub struct Piece<'a> {
    pub mesh: &'a Mesh,
    pub flat: Rgba,
}

impl<'a> Piece<'a> {
    /// A mesh in the default surface colour — what a model with no material
    /// draws as, and what the model viewport asks for.
    pub fn plain(mesh: &'a Mesh) -> Self {
        Self {
            mesh,
            flat: raster::SURFACE,
        }
    }
}

/// Draw `mesh` through `view` at `size`.
///
/// Always returns a full frame: an empty mesh, a zero size or geometry entirely
/// behind the camera produce the background rather than a failure, because the
/// caller is a window that has to draw something.
pub fn render(mesh: &Mesh, view: &View, size: Size) -> Image {
    scene(&[Piece::plain(mesh)], view, size)
}

/// Draw several pieces through one camera into one frame.
///
/// ⚠️ One depth buffer covers all of them, so a piece behind another is hidden
/// by it. Rendering each piece into its own frame and compositing the results
/// would order them by draw order instead, which is the bug the depth buffer
/// exists to prevent.
pub fn scene(pieces: &[Piece], view: &View, size: Size) -> Image {
    cut_into(pieces, view, size, None)
}

/// `scene`, with the number of bands forced.
///
/// ⚠️ Only the invariance test passes a count. It exists so that test can put
/// the *same* frame through every split there is — the picture must not depend
/// on how many threads happened to draw it, and a machine's core count is not
/// something a test can vary.
fn cut_into(pieces: &[Piece], view: &View, size: Size, bands: Option<usize>) -> Image {
    let mut image = Image::filled(size, view.background);
    if size.pixels() == 0 {
        return image;
    }
    let basis = Basis::of(&view.camera);
    let lens = Lens::new(view.camera.fov_y, size);
    let mut placed = Placement::default();
    for piece in pieces {
        place(&basis, &lens, piece, size, &mut placed);
    }

    let mut depth = vec![f32::NEG_INFINITY; size.pixels()];
    {
        let count = bands.unwrap_or_else(|| crews(size, placed.reach));
        let mut bands = image.bands(&mut depth, count);
        match bands.as_mut_slice() {
            [only] => fill(only, &placed.shapes),
            many => std::thread::scope(|crew| {
                for band in many {
                    let shapes = &placed.shapes;
                    crew.spawn(move || fill(band, shapes));
                }
            }),
        }
    }
    image
}

/// How many bands a frame is cut into, and so how many threads fill it.
///
/// ⚠️ **A band is a thread, so this is the core count and not the row count.**
/// Every band walks the whole triangle list to find what lands in its own rows,
/// so cutting finer than the machine can run at once pays for that walk again
/// and buys nothing.
///
/// ⚠️ **Gated on the work, not on the frame.** A large viewport holding one
/// small sprite is most of this program's output — 11 of the export's 139
/// effects — and spawning eight threads to fill a few thousand pixels costs
/// more than filling them.
fn crews(size: Size, reach: usize) -> usize {
    if reach < THREADED {
        return 1;
    }
    static CORES: std::sync::OnceLock<usize> = std::sync::OnceLock::new();
    let cores =
        *CORES.get_or_init(|| std::thread::available_parallelism().map_or(1, |count| count.get()));
    cores.min(size.height).max(1)
}

/// Pixels a frame has to be able to touch before it is worth splitting up.
///
/// ⛔ **A switch, not a rate.** Handing out threads in proportion to `reach`
/// reads better and is worse: reach is a bound on bounding boxes, and the
/// effects that cost most are fans of small triangles whose boxes barely
/// overlap the pixels they fill — `heart_dance` measured 6.6 ms on every core
/// and 8.4 ms on the two its reach asked for. Above the bar, take the machine.
const THREADED: usize = 100_000;

/// One triangle placed on the screen, and what paints it.
///
/// ⚠️ **Projected once, filled once per band.** The bands share this list rather
/// than each re-deriving it, and it is what makes the split safe: every band
/// walks the same triangles in the same order, so which fragment wins a pixel
/// cannot depend on how the frame was cut up.
struct Placed<'a> {
    screen: [camera::Point; 3],
    paint: raster::Paint<'a>,
}

/// Every triangle of a frame, and how many pixels they can between them reach.
#[derive(Default)]
struct Placement<'a> {
    shapes: Vec<Placed<'a>>,
    /// The triangles' bounding boxes summed and clipped to the frame — an upper
    /// bound on the fill, worked out here because the projection already has the
    /// corners in hand.
    reach: usize,
}

fn fill(band: &mut raster::Band, placed: &[Placed]) {
    for shape in placed {
        raster::raster(band, &shape.screen, &shape.paint);
    }
}

/// How many pixels of `size` a projected triangle's bounding box covers.
fn box_of(screen: &[camera::Point; 3], size: Size) -> usize {
    let reach = |low: f32, high: f32, limit: usize| {
        if !low.is_finite() || !high.is_finite() {
            return 0;
        }
        let low = low.max(0.0);
        let high = high.min(limit as f32);
        if high <= low {
            0
        } else {
            (high - low) as usize + 1
        }
    };
    let xs = screen.map(|corner| corner.x);
    let ys = screen.map(|corner| corner.y);
    let across = reach(
        xs.iter().copied().fold(f32::INFINITY, f32::min),
        xs.iter().copied().fold(f32::NEG_INFINITY, f32::max),
        size.width,
    );
    let down = reach(
        ys.iter().copied().fold(f32::INFINITY, f32::min),
        ys.iter().copied().fold(f32::NEG_INFINITY, f32::max),
        size.height,
    );
    across * down
}

fn place<'a>(basis: &Basis, lens: &Lens, piece: &Piece<'a>, size: Size, into: &mut Placement<'a>) {
    let mesh = piece.mesh;
    if mesh.is_empty() {
        return;
    }
    let positions = mesh.positions();

    // ⚠️ Per shape, not per mesh. The surface is resolved once for a whole run
    // of faces — asking per face would re-check 3,500 times a frame — but a
    // mesh carries as many images as its shapes reach, and taking one of them
    // for all of them paints 68 of `e_lui_robo`'s parts with the wrong texture
    // (D246).
    for batch in mesh.batches() {
        for face in batch.faces {
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
            let intensity = raster::lighting(basis, &corners);
            // A face whose corners the UV list does not reach falls back to
            // flat, so a short TEXCOORD_0 accessor loses a triangle's texture
            // rather than the whole model.
            // ⚠️ Read for the textured and the flat path alike. A shape
            // with no image is drawn with its vertex colour alone, which is
            // the `GX_PASSCLR` branch of the game's own TEV (D247, D251).
            let tint = batch
                .tints
                .and_then(|all| Some([*all.get(face.a)?, *all.get(face.b)?, *all.get(face.c)?]));
            let paint = match batch.surface.and_then(|surface| {
                surface
                    .corners(*face)
                    .map(|corners| raster::Paint::Textured {
                        blend: surface.blend,
                        texture: surface.texture,
                        corners,
                        tint,
                        intensity,
                        masked: surface.masked,
                        cutoff: surface.cutoff,
                        sampling: surface.sampling,
                        modulate: surface.modulate,
                        mask: surface.mask,
                    })
            }) {
                Some(textured) => textured,
                None => raster::Paint::Flat {
                    colour: piece.flat.shaded(intensity),
                    tint,
                },
            };
            into.reach += box_of(&screen, size);
            into.shapes.push(Placed { screen, paint });
        }
    }
}

/// The geometry and the measurements every part of the renderer tests against,
/// kept in one place so `camera`, `raster` and `background` read the same frame
/// the same way rather than each defining its own cube.
#[cfg(test)]
mod fixtures {
    use super::{Background, Camera, Image, Size, View};
    use crate::data::mesh::{Mesh, Vec3};

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

    pub(super) const FRAME: Size = Size::new(200, 200);

    pub(super) fn cube() -> Mesh {
        Mesh::parse(CUBE).expect("the cube parses")
    }

    pub(super) fn flat(camera: Camera) -> View {
        View {
            camera,
            background: Background::DarkGrey,
        }
    }

    /// Camera on +Z looking down -Z, so a test can place geometry at a known
    /// depth without solving for the orbit.
    pub(super) fn head_on() -> Camera {
        Camera {
            target: Vec3::ZERO,
            distance: 8.0,
            yaw: 0.0,
            pitch: 0.0,
            fov_y: super::camera::FOV_Y,
        }
    }

    /// Pixels that are not the flat background colour — i.e. the model.
    pub(super) fn covered(image: &Image) -> usize {
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

    pub(super) fn differing(one: &Image, two: &Image) -> usize {
        one.as_rgba()
            .chunks(4)
            .zip(two.as_rgba().chunks(4))
            .filter(|(a, b)| a != b)
            .count()
    }
}

#[cfg(test)]
mod tests {
    use super::fixtures::{covered, cube, flat, head_on, FRAME};
    use super::*;
    use crate::data::mesh::Mesh;

    #[test]
    fn an_empty_mesh_renders_only_the_background() {
        let mesh = Mesh::parse("").expect("nothing parses");
        let image = render(&mesh, &flat(Camera::fit(mesh.bounds())), FRAME);
        assert_eq!(covered(&image), 0);
        assert_eq!(image.as_rgba().len(), FRAME.pixels() * 4);
    }

    #[test]
    fn geometry_behind_the_camera_is_dropped() {
        // The camera sits at z = 8 looking towards -z; this quad is behind it.
        let mesh = Mesh::parse("v -2 -2 40\nv 2 -2 40\nv 2 2 40\nf 1 2 3\n").expect("parses");
        assert_eq!(covered(&render(&mesh, &flat(head_on()), FRAME)), 0);
    }

    /// ⚠️ **The frame must not depend on how many threads drew it.** Bands are
    /// filled at the same time and each keeps its own depth, so a triangle
    /// straddling a seam is the case that would show a split: one row too many
    /// or too few, or a depth test taken against the wrong slice. Every count
    /// from one to more bands than there are rows has to agree with one thread.
    #[test]
    fn splitting_the_frame_into_bands_does_not_change_a_pixel_of_it() {
        let mesh = cube();
        let view = flat(Camera::fit(mesh.bounds()));
        let pieces = [Piece::plain(&mesh)];
        let alone = cut_into(&pieces, &view, FRAME, Some(1));
        assert!(covered(&alone) > 0, "the control drew nothing");
        for count in [2, 3, 5, 8, 13, FRAME.height, FRAME.height * 2] {
            let split = cut_into(&pieces, &view, FRAME, Some(count));
            assert_eq!(
                split.as_rgba(),
                alone.as_rgba(),
                "{count} bands drew a different frame"
            );
        }
    }

    #[test]
    fn a_zero_sized_frame_is_empty_rather_than_a_panic() {
        let mesh = cube();
        let view = flat(Camera::fit(mesh.bounds()));
        assert!(render(&mesh, &view, Size::new(0, 0)).as_rgba().is_empty());
        assert!(render(&mesh, &view, Size::new(0, 32)).as_rgba().is_empty());
        assert_eq!(render(&mesh, &view, Size::new(1, 1)).as_rgba().len(), 4);
    }
}
