//! What `bleck model export` wrote: a manifest, and one mesh file per model.
//!
//! The manifest reader and the mesh sit together because a model is only
//! identified by both — the geometry says what to draw, the manifest says what
//! it is — and the end-to-end test at the foot of this file walks the two of
//! them plus the rasteriser in one pass. The binary glTF the exporter writes is
//! decoded next door in `gltf`; the OBJ parser below is what came before it.
//!
//! ⚠️ The manifest is the contract, not the directory listing — the rule for
//! this whole layer, stated once in `data`'s module doc. A filename cannot say
//! which disc file the model came from or which Maya shape inside it produced
//! these triangles, and both are how a model is identified.
//!
//! ⚠️ Geometry is read on demand, not at load. The manifest is a few hundred
//! bytes per model; the meshes are not, and a folder of them would sit in
//! memory for the sake of the one that is on screen.
//!
//! In OBJ only `v` and `f` lines are understood, because only those were ever
//! written. A line this does not recognise is skipped rather than rejected, so
//! a mesh carrying normals or materials still loads — untextured, since an OBJ
//! from this exporter never named a material to load.

use serde::Deserialize;
use std::path::{Path, PathBuf};

use super::gltf;
use super::morph::{Animation, ClipEntry};
use super::texture::Texture;

/// The file `bleck model export` writes alongside the meshes.
const MANIFEST: &str = "models.json";

#[derive(Debug, Deserialize)]
struct Manifest {
    models: Vec<Entry>,
}

/// One exported model, as `bleck` described it.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct Entry {
    /// Stable identifier: the disc file the model came from.
    pub name: String,
    /// The Maya shape within that file — one disc file holds several.
    #[serde(default)]
    pub shape: String,
    /// The OBJ, relative to the export folder. Made absolute on load.
    #[serde(rename = "file")]
    pub path: PathBuf,
    /// The disc file the model was read out of.
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub positions: usize,
    #[serde(default)]
    pub faces: usize,
    #[serde(default)]
    pub triangles: usize,
    /// Share of the file's vertices the exported faces actually reach.
    #[serde(default)]
    pub coverage: f32,
    /// ⚠️ Set when the export is one shape record out of a file that holds
    /// many, which is currently every model. The viewport shows exactly what
    /// the OBJ contains, so a fragment looks like a broken model unless the
    /// window says otherwise.
    #[serde(default)]
    pub fragment: bool,
    /// ⚠️ Set when `bleck --guess-textures` gave a multi-shape model image 0
    /// anyway. The image is almost certainly the wrong one, so a test asserting
    /// what a texture *looks like* must skip these (D229).
    #[serde(default)]
    pub texture_guessed: bool,
    /// Bounds as `bleck` measured them. Shown as facts; the camera fits itself
    /// to the bounds of the geometry actually parsed, so a wrong number here
    /// mis-labels a model rather than mis-framing it.
    #[serde(default)]
    pub min: [f32; 3],
    #[serde(default)]
    pub max: [f32; 3],
    /// Clips written into the `.glb`, so a list can say how many a model has
    /// without opening it.
    #[serde(default)]
    pub animations: usize,
    /// ⚠️ Clips the exporter's per-file budget left out. Reported, because a
    /// model that exported 3 of its 94 clips otherwise reads as a model with
    /// three animations.
    #[serde(default)]
    pub animations_dropped: usize,
    /// Every clip the file holds, written or not.
    #[serde(default)]
    pub clips: Vec<ClipEntry>,
}

impl Entry {
    /// Size in the terms that decide whether a model will draw usefully.
    pub fn describe(&self) -> String {
        format!("{} verts, {} tris", self.positions, self.triangles)
    }

    /// What a copy puts on the clipboard.
    ///
    /// ⚠️ The disc file's name, not the exported OBJ's path. `name` is what
    /// this model is called everywhere else; the OBJ is a temporary file on
    /// one machine.
    pub fn copy_text(&self) -> String {
        self.name.clone()
    }

    /// The disc file the model was read out of, for the exports that recorded
    /// one.
    pub fn source_text(&self) -> Option<String> {
        (!self.source.is_empty()).then(|| self.source.clone())
    }

    /// The extent `bleck` recorded, which says what units a model is in.
    pub fn extent(&self) -> String {
        format!(
            "{:.1} x {:.1} x {:.1}",
            self.max[0] - self.min[0],
            self.max[1] - self.min[1],
            self.max[2] - self.min[2]
        )
    }
}

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
    fn around(points: &[Vec3], faces: &[Face]) -> Self {
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

/// Everything a mesh file can carry, before bounds are measured from it.
///
/// The glTF reader builds this and hands it back rather than a `Mesh`, so that
/// `Bounds::around` stays the one place a model's extent is decided.
pub(crate) struct Parts {
    pub(crate) positions: Vec<Vec3>,
    pub(crate) faces: Vec<Face>,
    /// One per position, when the file carried `TEXCOORD_0`.
    pub(crate) uvs: Option<Vec<Uv>>,
    pub(crate) texture: Option<Texture>,
    /// The material declared `alphaMode: "MASK"` — cut-out art, where a texel
    /// below the cutoff is not drawn at all.
    pub(crate) masked: bool,
    /// The morph targets and clips the file carried, when it carried any.
    pub(crate) animation: Option<Animation>,
}

impl Parts {
    /// Everything a file that carries only geometry produces.
    pub(crate) fn bare(positions: Vec<Vec3>, faces: Vec<Face>) -> Self {
        Self {
            positions,
            faces,
            uvs: None,
            texture: None,
            masked: false,
            animation: None,
        }
    }

    pub(crate) fn into_mesh(self) -> Mesh {
        let bounds = Bounds::around(&self.positions, &self.faces);
        Mesh {
            positions: self.positions,
            posed: Vec::new(),
            faces: self.faces,
            bounds,
            uvs: self.uvs,
            texture: self.texture,
            masked: self.masked,
            animation: self.animation,
        }
    }
}

/// The texture a mesh is painted with, and the coordinates that index it.
///
/// Only ever handed out when both are present, so the rasteriser cannot reach
/// a half-textured mesh — UVs with no image would sample nothing, and an image
/// with no UVs has no coordinate to sample it at.
#[derive(Debug, Clone, Copy)]
pub struct Surface<'a> {
    pub texture: &'a Texture,
    pub uvs: &'a [Uv],
    pub masked: bool,
}

impl Surface<'_> {
    /// The three coordinates a face samples at, or `None` when the UV list does
    /// not reach one of its corners — which leaves that face flat-shaded rather
    /// than dropping it.
    pub fn corners(&self, face: Face) -> Option<[Uv; 3]> {
        Some([
            *self.uvs.get(face.a)?,
            *self.uvs.get(face.b)?,
            *self.uvs.get(face.c)?,
        ])
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
    bounds: Bounds,
    uvs: Option<Vec<Uv>>,
    texture: Option<Texture>,
    masked: bool,
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

    pub fn faces(&self) -> &[Face] {
        &self.faces
    }

    /// What to paint this mesh with, or `None` when it is untextured — 277 of
    /// 864 real models are, and they are drawn flat-shaded.
    pub fn surface(&self) -> Option<Surface<'_>> {
        Some(Surface {
            texture: self.texture.as_ref()?,
            uvs: self.uvs.as_deref()?,
            masked: self.masked,
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

    /// Read OBJ text. Faces with more than three corners are fanned into
    /// triangles, because everything downstream rasterises triangles only.
    pub fn parse(text: &str) -> Result<Self, Flaw> {
        let mut positions: Vec<Vec3> = Vec::new();
        let mut faces: Vec<Face> = Vec::new();

        for (offset, raw) in text.lines().enumerate() {
            let line = offset + 1;
            let mut words = raw.split_whitespace();
            match words.next() {
                Some("v") => positions.push(read_position(words, line)?),
                Some("f") => {
                    let corners = read_corners(words, positions.len(), line)?;
                    for window in corners[1..].windows(2) {
                        faces.push(Face {
                            a: corners[0],
                            b: window[0],
                            c: window[1],
                        });
                    }
                }
                _ => {}
            }
        }

        Ok(Parts::bare(positions, faces).into_mesh())
    }
}

fn read_position<'a>(words: impl Iterator<Item = &'a str>, line: usize) -> Result<Vec3, Flaw> {
    let mut numbers = [0.0f32; 3];
    let mut seen = 0;
    for word in words.take(3) {
        numbers[seen] = word.parse().map_err(|_| Flaw {
            line,
            why: format!("`{word}` is not a number"),
        })?;
        seen += 1;
    }
    if seen < 3 {
        return Err(Flaw {
            line,
            why: format!("a vertex needs 3 numbers, got {seen}"),
        });
    }
    Ok(Vec3::new(numbers[0], numbers[1], numbers[2]))
}

/// OBJ indices are 1-based, and negative ones count back from the newest
/// vertex — so a face is only resolvable against the vertices seen *so far*,
/// which is why this takes the running count rather than the final one.
fn read_corners<'a>(
    words: impl Iterator<Item = &'a str>,
    positions: usize,
    line: usize,
) -> Result<Vec<usize>, Flaw> {
    let mut corners = Vec::new();
    for word in words {
        // `v`, `v/vt` and `v/vt/vn` all lead with the position index.
        let field = word.split('/').next().unwrap_or(word);
        let index: i64 = field.parse().map_err(|_| Flaw {
            line,
            why: format!("`{field}` is not a vertex index"),
        })?;
        let resolved = if index > 0 {
            index - 1
        } else if index < 0 {
            positions as i64 + index
        } else {
            return Err(Flaw {
                line,
                why: "vertex index 0 is not valid".into(),
            });
        };
        if resolved < 0 || resolved >= positions as i64 {
            return Err(Flaw {
                line,
                why: format!("vertex {index} is outside the {positions} declared"),
            });
        }
        corners.push(resolved as usize);
    }
    if corners.len() < 3 {
        return Err(Flaw {
            line,
            why: format!("a face needs 3 corners, got {}", corners.len()),
        });
    }
    Ok(corners)
}

/// Every model the export folder declares.
#[derive(Default)]
pub struct Library {
    entries: Vec<Entry>,
    problem: Option<Problem>,
}

impl Library {
    /// Read the manifest in `root`.
    ///
    /// A failure is recorded rather than returned, for the same reason as
    /// `Catalog::load`: the window is already open and needs to say what to do
    /// about it, which `Problem` carries and a `Result` would not.
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

        let entries: Vec<Entry> = manifest
            .models
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

    /// Indices matching a search, in manifest order. Shape names are searched
    /// as well as model names: one disc file holds several shapes, and the
    /// shape is what tells them apart.
    #[cfg(test)]
    pub fn matching(&self, search: &str) -> Vec<usize> {
        self.filtered(search, false)
    }

    /// Models matching the search, optionally only the whole ones.
    ///
    /// ⚠️ **A fragment does not look like missing data, it looks like a
    /// rendering fault** — a corner torn into the middle of an otherwise
    /// recognisable character. 732 of 864 exported models are fragments
    /// (D211), so hiding them is the difference between a viewer that looks
    /// broken and one that looks partial.
    pub fn filtered(&self, search: &str, whole_only: bool) -> Vec<usize> {
        let needle = search.to_lowercase();
        self.entries
            .iter()
            .enumerate()
            .filter(|(_, entry)| !whole_only || !entry.fragment)
            .filter(|(_, entry)| {
                needle.is_empty()
                    || entry.name.to_lowercase().contains(&needle)
                    || entry.shape.to_lowercase().contains(&needle)
            })
            .map(|(index, _)| index)
            .collect()
    }

    /// How many models the whole-only filter would keep.
    pub fn whole(&self) -> usize {
        self.entries.iter().filter(|entry| !entry.fragment).count()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::scratch::Scratch;

    const TRIANGLE: &str = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";

    #[test]
    fn parses_positions_and_faces() {
        let mesh = Mesh::parse(TRIANGLE).expect("triangle parses");
        assert_eq!(mesh.positions().len(), 3);
        assert_eq!(mesh.faces(), [Face { a: 0, b: 1, c: 2 }]);
        assert_eq!(mesh.positions()[1], Vec3::new(1.0, 0.0, 0.0));
    }

    #[test]
    fn ignores_lines_the_format_does_not_promise() {
        let text = "# a comment\nmtllib none.mtl\nvn 0 0 1\nvt 0 0\no thing\n";
        let mesh = Mesh::parse(&format!("{text}{TRIANGLE}")).expect("extras are skipped");
        assert_eq!(mesh.faces().len(), 1);
    }

    #[test]
    fn accepts_slash_forms_and_negative_indices() {
        let mesh =
            Mesh::parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1/1 -2/2 -1\n").expect("index forms parse");
        assert_eq!(mesh.faces(), [Face { a: 0, b: 1, c: 2 }]);
    }

    #[test]
    fn fans_a_quad_into_two_triangles() {
        let mesh =
            Mesh::parse("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n").expect("quad parses");
        assert_eq!(
            mesh.faces(),
            [Face { a: 0, b: 1, c: 2 }, Face { a: 0, b: 2, c: 3 }]
        );
    }

    fn manifest_row(name: &str, source: &str) -> Entry {
        Entry {
            name: name.to_owned(),
            shape: "kuriboShape".to_owned(),
            path: PathBuf::from("0001.obj"),
            source: source.to_owned(),
            positions: 3,
            faces: 1,
            triangles: 1,
            coverage: 1.0,
            fragment: false,
            texture_guessed: false,
            min: [0.0; 3],
            max: [1.0; 3],
            ..Default::default()
        }
    }

    /// ⚠️ The name, not the OBJ. The exported file is a temporary on one
    /// machine, so a clipboard full of those paths names nothing anyone else
    /// can look up.
    #[test]
    fn a_model_copies_its_name_and_the_disc_file_behind_it() {
        let shown = manifest_row("files/a/e_kuribo.dat", "files/a/e_kuribo.dat");
        assert_eq!(shown.copy_text(), "files/a/e_kuribo.dat");
        assert_eq!(shown.source_text(), Some("files/a/e_kuribo.dat".to_owned()));
        assert_ne!(
            shown.copy_text(),
            shown.path.display().to_string(),
            "the export's own file is not what names this model"
        );
        assert_ne!(shown.copy_text(), shown.shape, "nor is the Maya shape");
    }

    /// A "Copy source path" that put nothing on the clipboard reads as a copy
    /// that failed.
    #[test]
    fn a_model_with_no_source_offers_nothing_for_it() {
        assert_eq!(manifest_row("files/a/loose.dat", "").source_text(), None);
    }

    #[test]
    fn rejects_an_index_past_the_end() {
        let flaw = Mesh::parse("v 0 0 0\nf 1 2 3\n").expect_err("index 2 does not exist");
        assert_eq!(flaw.line, 2);
        assert!(flaw.why.contains("outside"), "{}", flaw.why);
    }

    #[test]
    fn rejects_a_short_vertex() {
        let flaw = Mesh::parse("v 1 2\n").expect_err("two numbers is not a point");
        assert_eq!(flaw.line, 1);
    }

    #[test]
    fn empty_text_is_an_empty_mesh_not_an_error() {
        let mesh = Mesh::parse("").expect("nothing is not a failure");
        assert!(mesh.is_empty());
        assert_eq!(mesh.bounds(), Bounds::default());
    }

    #[test]
    fn bounds_span_every_point() {
        let mesh = Mesh::parse("v -2 0 1\nv 4 3 -5\nv 0 0 0\nf 1 2 3\n").expect("parses");
        assert_eq!(mesh.bounds().min, Vec3::new(-2.0, 0.0, -5.0));
        assert_eq!(mesh.bounds().max, Vec3::new(4.0, 3.0, 1.0));
        assert_eq!(mesh.bounds().centre(), Vec3::new(1.0, 1.5, -2.0));
    }

    /// ⚠️ Real exports do this constantly: 733 of 864 models carry positions
    /// no face refers to. Bounding them all frames empty space, and the model
    /// ends up too small to see.
    #[test]
    fn bounds_ignore_positions_no_face_refers_to() {
        let mesh =
            Mesh::parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 900 900 900\nf 1 2 3\n").expect("parses");
        assert_eq!(mesh.positions().len(), 4);
        assert_eq!(mesh.bounds().max, Vec3::new(1.0, 1.0, 0.0));
    }

    /// With nothing drawn there is nothing to frame, so every point counts —
    /// which keeps a mesh of loose vertices from claiming a zero-size box at
    /// the origin it has no points near.
    #[test]
    fn bounds_fall_back_to_every_point_when_there_are_no_faces() {
        let mesh = Mesh::parse("v 5 5 5\nv 7 9 5\n").expect("parses");
        assert!(mesh.is_empty());
        assert_eq!(mesh.bounds().min, Vec3::new(5.0, 5.0, 5.0));
        assert_eq!(mesh.bounds().max, Vec3::new(7.0, 9.0, 5.0));
    }

    const MANIFEST_TEXT: &str = r#"{"models": [
      {"name": "p_wii_mario", "shape": "R_Arm_skinShape", "file": "p_wii_mario.obj",
       "positions": 3, "faces": 1, "triangles": 1,
       "min": [-30.0, -14.7, 0.0], "max": [10.8, 58.7, 3.2]}
    ]}"#;

    /// The manifest as `bleck model export` writes it today, keys and all.
    /// ⚠️ Unknown keys must stay tolerated: `schema`, `coverage` and
    /// `fragment` all arrived after this reader was written, and a stricter
    /// one would have refused every export the day they landed.
    const LIVE_MANIFEST: &str = r#"{"schema": 1, "models": [
      {"name": "p_big_mario", "shape": "zentaiShape", "file": "p_big_mario.obj",
       "source": "files/a/p_big_mario", "positions": 2255, "faces": 3529,
       "triangles": 3529, "coverage": 0.0013, "fragment": true,
       "min": [-73.5, -1.2, -36.0], "max": [73.5, 147.0, 36.0],
       "something_added_later": [1, 2, 3]}
    ]}"#;

    #[test]
    fn reads_the_manifest_the_exporter_writes_today() {
        let scratch = Scratch::new("live");
        scratch.write("models.json", LIVE_MANIFEST);
        let library = Library::load(&scratch.path);
        assert_eq!(library.problem(), None);
        let entry = &library.entries()[0];
        assert_eq!(entry.source, "files/a/p_big_mario");
        assert!(entry.fragment);
        assert_eq!(entry.coverage, 0.0013);
    }

    /// The face form the exporter emits now that it carries normals, mixed
    /// with corners that have none.
    #[test]
    fn accepts_the_position_double_slash_normal_form() {
        let mesh = Mesh::parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 1\nf 1//1 2//1 3\n")
            .expect("the exporter's own output parses");
        assert_eq!(mesh.faces(), [Face { a: 0, b: 1, c: 2 }]);
    }

    #[test]
    fn reads_the_manifest_and_absolutises_paths() {
        let scratch = Scratch::new("manifest");
        scratch.write("models.json", MANIFEST_TEXT);
        scratch.write("p_wii_mario.obj", TRIANGLE);

        let library = Library::load(&scratch.path);
        assert_eq!(library.problem(), None);
        assert_eq!(library.len(), 1);
        let entry = &library.entries()[0];
        assert_eq!(entry.shape, "R_Arm_skinShape");
        assert_eq!(entry.path, scratch.path.join("p_wii_mario.obj"));
        assert_eq!(entry.describe(), "3 verts, 1 tris");
        assert_eq!(entry.extent(), "40.8 x 73.4 x 3.2");
        assert!(!entry.fragment, "the manifest did not claim one");

        let mesh = Mesh::load(&entry.path).expect("the mesh beside it loads");
        assert_eq!(mesh.faces().len(), 1);
    }

    /// The whole path a model takes through this program: an export folder on
    /// disk, through the manifest, through the OBJ, to lit pixels. Each step
    /// has its own test above; this is the one that fails if they stop
    /// fitting together.
    #[test]
    fn an_export_folder_reaches_the_rasteriser() {
        let scratch = Scratch::new("endtoend");
        scratch.write(
            "models.json",
            r#"{"models": [{"name": "p_wii_mario", "shape": "zentaiShape",
                 "file": "sub/p_wii_mario.obj", "positions": 4, "faces": 2,
                 "triangles": 2, "min": [-1,-1,-1], "max": [1,1,1]}]}"#,
        );
        std::fs::create_dir_all(scratch.path.join("sub")).expect("subfolder");
        std::fs::write(
            scratch.path.join("sub/p_wii_mario.obj"),
            "v -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\nf 1 2 3\nf 1 3 4\n",
        )
        .expect("mesh file");

        let library = Library::load(&scratch.path);
        let entry = &library.entries()[library.matching("zentai")[0]];
        let mesh = Mesh::load(&entry.path).expect("mesh loads");

        let view = crate::render::View {
            camera: crate::render::Camera::fit(mesh.bounds()),
            background: crate::render::Background::DarkGrey,
        };
        let size = crate::render::Size::new(120, 120);
        let image = crate::render::render(&mesh, &view, size);

        let sky = crate::render::Background::DarkGrey.pixel(0, 0, size);
        let drawn = (0..size.height)
            .flat_map(|y| (0..size.width).map(move |x| (x, y)))
            .filter(|&(x, y)| image.pixel(x, y) != sky)
            .count();
        assert!(drawn > 500, "only {drawn} pixels of the square were drawn");
    }

    #[test]
    fn a_missing_manifest_names_the_folder_and_the_command() {
        let scratch = Scratch::new("bare");
        let library = Library::load(&scratch.path);
        assert_eq!(
            library.problem(),
            Some(&Problem::NoManifest(scratch.path.clone()))
        );
        let said = library.problem().expect("a problem").describe();
        assert!(said.contains("bleck model export"), "{said}");
        assert!(said.contains(&scratch.path.display().to_string()), "{said}");
    }

    #[test]
    fn broken_json_is_reported_not_panicked() {
        let scratch = Scratch::new("broken");
        scratch.write("models.json", "{\"models\": [");
        let library = Library::load(&scratch.path);
        assert!(matches!(library.problem(), Some(Problem::Unreadable(_))));
        assert!(library.is_empty());
    }

    #[test]
    fn a_missing_mesh_file_names_itself() {
        let scratch = Scratch::new("gone");
        let path = scratch.path.join("absent.obj");
        let problem = Mesh::load(&path).expect_err("nothing is there to read");
        assert_eq!(problem, Problem::NoMesh(path.clone()));
        assert!(problem.describe().contains("absent.obj"), "{problem:?}");
    }

    #[test]
    fn a_broken_mesh_file_reports_its_line() {
        let scratch = Scratch::new("badobj");
        scratch.write("bad.obj", "v 0 0 0\nv 1 0 0\nf 1 2 9\n");
        let path = scratch.path.join("bad.obj");
        let problem = Mesh::load(&path).expect_err("index 9 does not exist");
        assert!(problem.describe().contains(":3:"), "{}", problem.describe());
    }

    #[test]
    fn search_matches_name_or_shape() {
        let scratch = Scratch::new("search");
        scratch.write("models.json", MANIFEST_TEXT);
        let library = Library::load(&scratch.path);
        assert_eq!(library.matching(""), vec![0]);
        assert_eq!(library.matching("MARIO"), vec![0]);
        assert_eq!(library.matching("r_arm"), vec![0]);
        assert!(library.matching("luigi").is_empty());
    }
}

/// Loading the real export, when one happens to be on this machine.
///
/// ⚠️ `work/` is git-ignored, so these skip rather than fail on a fresh clone
/// or in CI. They exist because the fixture above is one triangle written by
/// this file's own test — it cannot catch a disagreement between what
/// `bleck.formats.gltf` writes and what this reads, and that disagreement is
/// exactly what shipped once.
#[cfg(test)]
#[path = "mesh_real_tests.rs"]
mod real_export_tests;
