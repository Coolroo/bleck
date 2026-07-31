//! What `bleck model export` wrote: a manifest, and one Wavefront OBJ per model.
//!
//! The manifest reader and the OBJ parser sit together because a model is only
//! identified by both — the geometry says what to draw, the manifest says what
//! it is — and the end-to-end test at the foot of this file walks the two of
//! them plus the rasteriser in one pass.
//!
//! ⚠️ The manifest is the contract, not the directory listing — the rule for
//! this whole layer, stated once in `data`'s module doc. A `.obj` filename
//! cannot say which disc file the model came from or which Maya shape inside it
//! produced these triangles, and both are how a model is identified.
//!
//! ⚠️ Geometry is read on demand, not at load. The manifest is a few hundred
//! bytes per model; the meshes are not, and a folder of them would sit in
//! memory for the sake of the one that is on screen.
//!
//! Only `v` and `f` lines are understood, because only those are written. A
//! line this does not recognise is skipped rather than rejected, so a mesh
//! carrying normals or materials still loads.

use serde::Deserialize;
use std::path::{Path, PathBuf};

/// The file `bleck model export` writes alongside the meshes.
const MANIFEST: &str = "models.json";

#[derive(Debug, Deserialize)]
struct Manifest {
    models: Vec<Entry>,
}

/// One exported model, as `bleck` described it.
#[derive(Debug, Deserialize, Clone)]
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
    /// Bounds as `bleck` measured them. Shown as facts; the camera fits itself
    /// to the bounds of the geometry actually parsed, so a wrong number here
    /// mis-labels a model rather than mis-framing it.
    #[serde(default)]
    pub min: [f32; 3],
    #[serde(default)]
    pub max: [f32; 3],
}

impl Entry {
    /// Size in the terms that decide whether a model will draw usefully.
    pub fn describe(&self) -> String {
        format!("{} verts, {} tris", self.positions, self.triangles)
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

/// Positions and triangles, with nothing else the format may have carried.
#[derive(Debug, Clone, Default)]
pub struct Mesh {
    positions: Vec<Vec3>,
    faces: Vec<Face>,
    bounds: Bounds,
}

impl Mesh {
    pub fn positions(&self) -> &[Vec3] {
        &self.positions
    }

    pub fn faces(&self) -> &[Face] {
        &self.faces
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

    pub fn load(path: &Path) -> Result<Self, Problem> {
        let text =
            std::fs::read_to_string(path).map_err(|_| Problem::NoMesh(path.to_path_buf()))?;
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

        let bounds = Bounds::around(&positions, &faces);
        Ok(Self {
            positions,
            faces,
            bounds,
        })
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
    pub fn matching(&self, search: &str) -> Vec<usize> {
        let needle = search.to_lowercase();
        self.entries
            .iter()
            .enumerate()
            .filter(|(_, entry)| {
                needle.is_empty()
                    || entry.name.to_lowercase().contains(&needle)
                    || entry.shape.to_lowercase().contains(&needle)
            })
            .map(|(index, _)| index)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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

    /// A directory of our own under the system temp dir, removed on drop, so
    /// the manifest tests touch the real filesystem without a dev-dependency.
    struct Scratch {
        path: PathBuf,
    }

    impl Scratch {
        fn new(tag: &str) -> Self {
            static NEXT: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
            let count = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let path =
                std::env::temp_dir().join(format!("dimentio-{tag}-{}-{count}", std::process::id()));
            std::fs::create_dir_all(&path).expect("scratch dir");
            Self { path }
        }

        fn write(&self, name: &str, text: &str) {
            std::fs::write(self.path.join(name), text).expect("scratch file");
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.path);
        }
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
