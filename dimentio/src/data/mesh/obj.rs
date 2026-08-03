//! The OBJ reader: what `bleck model export` wrote before it wrote glTF.
//!
//! Only `v` and `f` lines are understood, because only those were ever
//! written. A line this does not recognise is skipped rather than rejected, so
//! a mesh carrying normals or materials still loads — untextured, since an OBJ
//! from this exporter never named a material to load.

use super::{Face, Flaw, Mesh, Parts, Vec3};

impl Mesh {
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
