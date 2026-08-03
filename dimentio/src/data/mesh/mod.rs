//! What `bleck model export` wrote: a manifest, and one mesh file per model.
//!
//! The manifest reader and the mesh sit together because a model is only
//! identified by both — the geometry says what to draw, the manifest says what
//! it is — and the end-to-end test in `real_export_tests` walks the two of them
//! plus the rasteriser in one pass. The binary glTF the exporter writes is
//! decoded next door in `gltf`; `obj` is what came before it.
//!
//! # Shape
//!
//! | module | what it owns |
//! |---|---|
//! | `geometry` | points, triangles, texture coordinates, bounds |
//! | `paint` | shapes, images, blend modes, the surface a batch draws with |
//! | `obj` | reading the older text format |
//! | `library` | the `models.json` manifest and its rows |
//!
//! ⚠️ **Each reads from the ones above it and never back.** `geometry` knows
//! nothing of materials, `paint` nothing of files, and this file is the only
//! place that joins a manifest row to a mesh on disk.

use std::path::{Path, PathBuf};

use super::gltf;
use super::morph::Animation;
use library::MANIFEST;

mod geometry;
mod library;
mod obj;
mod paint;

pub use geometry::{Bounds, Face, Uv, Vec3};
pub use library::{Entry, Library};
pub use paint::{Batch, Blend, Mask, Modulate, Paint, Shape, Surface};

/// Why a folder, or one mesh in it, produced nothing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Problem {
    NoManifest(PathBuf),
    Unreadable(String),
    NoMesh(PathBuf),
    BadMesh {
        file: PathBuf,
        line: usize,
        why: String,
    },
}

impl Problem {
    pub fn describe(&self) -> String {
        match self {
            // ⚠️ Names the file it wanted. "Nothing here" sends someone
            // looking in the wrong place.
            Self::NoManifest(path) => format!(
                "No {MANIFEST} in {}.\nRun: bleck model export --out {}",
                path.display(),
                path.display()
            ),
            Self::Unreadable(why) => format!("{MANIFEST} could not be read:\n{why}"),
            Self::NoMesh(path) => format!("Mesh file is missing:\n{}", path.display()),
            Self::BadMesh { file, line, why } => {
                format!("{}:{line}: {why}", file.display())
            }
        }
    }
}

/// A rejected OBJ line, before the file it came from is known.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Flaw {
    pub line: usize,
    pub why: String,
}
/// Everything a mesh file can carry, before bounds are measured from it.
///
/// The glTF reader builds this and hands it back rather than a `Mesh`, so that
/// `Bounds::around` stays the one place a model's extent is decided.
pub(crate) struct Parts {
    pub(crate) positions: Vec<Vec3>,
    pub(crate) faces: Vec<Face>,
    /// One per glTF primitive, in file order. Never empty when `faces` is not.
    pub(crate) shapes: Vec<Shape>,
    /// One per position, when the file carried `TEXCOORD_0`.
    pub(crate) uvs: Option<Vec<Uv>>,
    /// One per position, when any primitive carried `COLOR_0`. The game
    /// multiplies this into whatever the shape draws with (D251).
    pub(crate) colours: Option<Vec<[u8; 4]>>,
    /// Every image some shape reaches, decoded once each. A shape's `paint`
    /// indexes this.
    pub(crate) paints: Vec<Paint>,
    /// The morph targets and clips the file carried, when it carried any.
    pub(crate) animation: Option<Animation>,
}

impl Parts {
    /// Everything a file that carries only geometry produces.
    ///
    /// One shape over all of it: an OBJ never named a group, and a viewer that
    /// offered nothing to toggle would look like the control had broken.
    pub(crate) fn bare(positions: Vec<Vec3>, faces: Vec<Face>) -> Self {
        let shapes = vec![Shape {
            first: 0,
            count: faces.len(),
            visible: true,
            paint: None,
        }];
        Self {
            positions,
            faces,
            shapes,
            uvs: None,
            colours: None,
            paints: Vec::new(),
            animation: None,
        }
    }

    pub(crate) fn into_mesh(self) -> Mesh {
        let bounds = Bounds::around(&self.positions, &self.faces);
        Mesh {
            positions: self.positions,
            posed: Vec::new(),
            drawn: self.faces.clone(),
            faces: self.faces,
            shapes: self.shapes,
            hidden: 0,
            bounds,
            uvs: self.uvs,
            colours: self.colours,
            paints: self.paints,
            animation: self.animation,
        }
    }
}
/// Positions and triangles, plus the texture the file named if it named one.
#[derive(Debug, Clone, Default)]
pub struct Mesh {
    positions: Vec<Vec3>,
    /// The rest positions displaced by whichever pose is being held. Empty
    /// whenever nothing is posed, which is every mesh that carries no
    /// animation and every animated one before a clip is picked.
    posed: Vec<Vec3>,
    faces: Vec<Face>,
    /// The faces of the shapes currently shown. Read only while something is
    /// hidden; `hidden` is what decides which list `faces` hands back.
    drawn: Vec<Face>,
    shapes: Vec<Shape>,
    hidden: usize,
    bounds: Bounds,
    uvs: Option<Vec<Uv>>,
    colours: Option<Vec<[u8; 4]>>,
    paints: Vec<Paint>,
    animation: Option<Animation>,
}

impl Mesh {
    /// What to draw: the pose being held, or the rest positions when none is.
    pub fn positions(&self) -> &[Vec3] {
        if self.posed.is_empty() {
            &self.positions
        } else {
            &self.posed
        }
    }

    /// The positions as the file recorded them, whatever is posed on top.
    ///
    /// Only the tests read this: the window draws whatever is posed, and the
    /// evidence that a pose *is* a displacement of the rest positions rather
    /// than a separate mesh has to compare the two.
    #[allow(dead_code)]
    pub fn rest_positions(&self) -> &[Vec3] {
        &self.positions
    }

    /// The clips this mesh can play, or `None` when it carries none — which
    /// 646 of 864 exported models do.
    pub fn animation(&self) -> Option<&Animation> {
        self.animation.as_ref()
    }

    /// Hold the pose `time` seconds into `clip`.
    ///
    /// ⚠️ **The bounds do not move with it.** They are measured once, from the
    /// rest pose, and the camera is framed from them — a box that followed the
    /// animation would zoom the viewport in and out on every frame.
    pub fn pose(&mut self, clip: usize, time: f32) {
        let Some(animation) = &self.animation else {
            return;
        };
        self.posed = animation.displace(&self.positions, clip, time);
    }

    /// Drop the held pose and draw the file's own positions again.
    ///
    /// Paired with `pose` and read only by the tests — the window replaces the
    /// whole mesh when the selection changes, so it never needs to undo one.
    #[allow(dead_code)]
    pub fn unpose(&mut self) {
        self.posed = Vec::new();
    }

    /// The triangles to draw: every one, or only the shapes still shown.
    ///
    /// The renderer walks `batches` instead, because a triangle alone does not
    /// say which image it samples. This is the same set flattened, and a test
    /// next door holds the two to each other.
    #[allow(dead_code)]
    pub fn faces(&self) -> &[Face] {
        if self.hidden == 0 {
            &self.faces
        } else {
            &self.drawn
        }
    }

    /// The shapes the file was split into, in primitive order.
    pub fn shapes(&self) -> &[Shape] {
        &self.shapes
    }

    pub fn hidden_shapes(&self) -> usize {
        self.hidden
    }

    /// Show or hide one shape.
    ///
    /// ⚠️ **The bounds do not move**, for the same reason posing does not move
    /// them: hiding a limb would refit the camera and read as the model jumping
    /// rather than as a part disappearing.
    pub fn set_shape_visible(&mut self, index: usize, visible: bool) {
        let Some(shape) = self.shapes.get_mut(index) else {
            return;
        };
        if shape.visible == visible {
            return;
        }
        shape.visible = visible;
        self.redraw();
    }

    /// Show every shape again.
    pub fn show_all_shapes(&mut self) {
        for shape in &mut self.shapes {
            shape.visible = true;
        }
        self.redraw();
    }

    fn redraw(&mut self) {
        self.hidden = self.shapes.iter().filter(|shape| !shape.visible).count();
        self.drawn = self
            .shapes
            .iter()
            .filter(|shape| shape.visible)
            .flat_map(|shape| {
                self.faces
                    .get(shape.first..shape.first + shape.count)
                    .unwrap_or_default()
            })
            .copied()
            .collect();
    }

    /// Every image this mesh draws with, in the order its shapes first reach
    /// them. Empty when it is untextured — 41 of 864 real models are, and they
    /// are drawn flat-shaded.
    pub fn paints(&self) -> &[Paint] {
        &self.paints
    }

    /// The triangles to draw, grouped by the image each shape samples.
    ///
    /// ⚠️ Hidden shapes are left out, so this and `faces` describe the same
    /// triangles — `redraw` concatenates exactly these runs.
    pub fn batches(&self) -> impl Iterator<Item = Batch<'_>> + '_ {
        self.shapes
            .iter()
            .filter(|shape| shape.visible)
            .map(move |shape| Batch {
                faces: self
                    .faces
                    .get(shape.first..shape.first + shape.count)
                    .unwrap_or_default(),
                surface: self.surface_of(*shape),
                tints: self.colours.as_deref(),
            })
    }

    /// What one shape is painted with, or `None` when it draws flat.
    ///
    /// Only handed out when the image and the coordinates are both there, so
    /// the rasteriser cannot reach a half-textured shape.
    fn surface_of(&self, shape: Shape) -> Option<Surface<'_>> {
        let paint = self.paints.get(shape.paint?)?;
        Some(Surface {
            texture: &paint.texture,
            uvs: self.uvs.as_deref()?,
            blend: paint.blend,
            masked: paint.masked,
            cutoff: paint.cutoff,
            sampling: &paint.sampling,
            modulate: paint.modulate,
            mask: paint.mask.as_ref(),
        })
    }

    /// The box around the geometry that will actually be drawn — not around
    /// every position in the file. Zero-sized when there are no points at all,
    /// which the camera treats as a model too small to frame, not an error.
    pub fn bounds(&self) -> Bounds {
        self.bounds
    }

    pub fn is_empty(&self) -> bool {
        self.faces.is_empty()
    }

    /// Read a mesh, in whichever of the two shapes the exporter wrote.
    ///
    /// ⚠️ **Sniffed by content, not by extension.** `bleck` moved from OBJ to
    /// glTF and a reader that trusted the suffix would have to be changed again
    /// next time; the first four bytes are decisive and cost nothing.
    ///
    /// ⛔ A `.glb` is **binary**, so it must not go through `read_to_string`.
    /// It did, once: the UTF-8 failure surfaced as `NoMesh` and every model in
    /// the folder reported "Mesh file is missing" while sitting on disk.
    pub fn load(path: &Path) -> Result<Self, Problem> {
        let raw = std::fs::read(path).map_err(|_| Problem::NoMesh(path.to_path_buf()))?;
        if raw.starts_with(gltf::MAGIC) {
            return gltf::parse(&raw)
                .map(Parts::into_mesh)
                .map_err(|why| Problem::BadMesh {
                    file: path.to_path_buf(),
                    line: 0,
                    why,
                });
        }
        let text = String::from_utf8(raw).map_err(|_| Problem::BadMesh {
            file: path.to_path_buf(),
            line: 0,
            why: "not glTF, and not text either".into(),
        })?;
        Self::parse(&text).map_err(|flaw| Problem::BadMesh {
            file: path.to_path_buf(),
            line: flaw.line,
            why: flaw.why,
        })
    }
}

#[cfg(test)]
mod tests;

/// Loading the real export, when one happens to be on this machine.
///
/// ⚠️ `work/` is git-ignored, so these skip rather than fail on a fresh clone
/// or in CI. They exist because the fixture in `tests` is one triangle written
/// by this crate — it cannot catch a disagreement between what
/// `bleck.formats.gltf` writes and what this reads, and that disagreement is
/// exactly what shipped once.
#[cfg(test)]
mod real_export_tests;
