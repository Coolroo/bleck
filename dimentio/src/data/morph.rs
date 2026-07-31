//! Morph-target animation: the poses a `.glb` carries, and the positions they
//! displace the mesh to at a moment in time.
//!
//! ⛔ **There is no skeleton.** The game adds per-vertex offsets to a copy of
//! the position array rather than transforming joints (D217), and `bleck`
//! exports exactly that as glTF morph targets. So playing a clip is a weighted
//! sum of position deltas, not a matrix palette.
//!
//! ⚠️ **glTF has one target list per mesh, not one per animation.** Every clip
//! in a file drives the same weights array and holds the other clips' targets
//! at zero, which is why `Key` carries a weight for every target in the file
//! and not only for its own.
//!
//! ⚠️ **The exporter writes one pose at weight 1 at a time, and this does not
//! assume that.** Weights are interpolated between the surrounding keyframes
//! the way glTF's `LINEAR` says to, so a file written by anything else — or by
//! a future exporter that blends — plays correctly rather than snapping.

use serde::Deserialize;

use super::mesh::Vec3;

/// One animation clip, as `models.json` describes it.
///
/// ⚠️ **The manifest's view, not the file's.** It lists every clip a disc file
/// holds, including the ones the exporter's budget left out — which is how a
/// window can say "12 clips not exported" instead of quietly showing fewer.
/// `Clip` below is what the `.glb` actually carries.
#[derive(Debug, Deserialize, Clone, Default)]
pub struct ClipEntry {
    pub name: String,
    /// Morph poses in the clip. Zero means the clip decoded but moves nothing,
    /// which is why it is not in the `.glb`.
    #[serde(default)]
    pub poses: usize,
    #[serde(default)]
    pub seconds: f32,
    /// Whether this clip is one of the ones in the `.glb`.
    #[serde(default)]
    pub written: bool,
}

/// Below this a weight contributes nothing worth the multiply. Most weights in
/// an exported file are exactly zero, and a clip may carry hundreds of targets.
const NEGLIGIBLE: f32 = 1e-6;

/// One morph target: a delta per mesh position.
///
/// ⚠️ **Dense here whatever the file said.** A `.glb` may encode a target as a
/// sparse accessor, as a full buffer view, or as no buffer view at all;
/// `gltf_accessor::read_vec3` flattens all three into one delta per position
/// before it reaches this type. Playing a clip walks every position anyway, so
/// keeping the sparsity would buy a branch per vertex and nothing else.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Pose {
    pub deltas: Vec<Vec3>,
}

/// One keyframe: when it happens, and what every target weighs then.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Key {
    pub time: f32,
    pub weights: Vec<f32>,
}

/// One named animation over the file's shared target list.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Clip {
    pub name: String,
    pub keys: Vec<Key>,
}

impl Clip {
    /// How long the clip runs, which is its last keyframe.
    ///
    /// ⚠️ Not the difference between first and last. A clip whose first key is
    /// at 0.3 s still plays from zero, and a scrubber over `0..=span` that
    /// started at 0.3 could not reach the beginning.
    pub fn seconds(&self) -> f32 {
        self.keys.last().map_or(0.0, |key| key.time)
    }

    /// What the file says this clip is, for a list to show.
    pub fn describe(&self) -> String {
        format!("{} · {:.2}s", self.name, self.seconds())
    }
}

/// A mesh's morph animation: the targets, and the clips that drive them.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Animation {
    targets: Vec<Pose>,
    clips: Vec<Clip>,
}

impl Animation {
    /// Build one, keeping only what can actually be played.
    ///
    /// A clip with no keyframes is dropped: it would show as a playable
    /// animation whose scrubber has nowhere to go.
    pub fn new(targets: Vec<Pose>, clips: Vec<Clip>) -> Option<Self> {
        if targets.is_empty() {
            return None;
        }
        let clips: Vec<Clip> = clips
            .into_iter()
            .filter(|clip| !clip.keys.is_empty())
            .collect();
        (!clips.is_empty()).then_some(Self { targets, clips })
    }

    pub fn clips(&self) -> &[Clip] {
        &self.clips
    }

    pub fn targets(&self) -> usize {
        self.targets.len()
    }

    /// Every target's weight `time` seconds into `clip`.
    ///
    /// Interpolated the way glTF's `LINEAR` sampler is defined: held at the
    /// first key before the clip starts, held at the last key after it ends,
    /// and mixed in proportion in between.
    ///
    /// An unknown clip weighs nothing, which draws the mesh at rest rather
    /// than refusing to draw it.
    pub fn weights_at(&self, clip: usize, time: f32) -> Vec<f32> {
        let zero = vec![0.0; self.targets.len()];
        let Some(clip) = self.clips.get(clip) else {
            return zero;
        };
        let Some(first) = clip.keys.first() else {
            return zero;
        };
        if time <= first.time {
            return first.weights.clone();
        }
        let Some(last) = clip.keys.last() else {
            return zero;
        };
        if time >= last.time {
            return last.weights.clone();
        }
        let at = clip
            .keys
            .windows(2)
            .find(|pair| time >= pair[0].time && time <= pair[1].time);
        let Some(pair) = at else {
            return last.weights.clone();
        };
        let span = pair[1].time - pair[0].time;
        // Two keys at the same instant: the later one wins, rather than
        // dividing by the zero between them.
        if span <= 0.0 {
            return pair[1].weights.clone();
        }
        let across = (time - pair[0].time) / span;
        mix(&pair[0].weights, &pair[1].weights, across)
    }

    /// `rest` displaced by the weights `time` seconds into `clip`.
    ///
    /// ⚠️ A target shorter than the mesh displaces the vertices it reaches and
    /// leaves the rest alone. A file that disagrees with itself is worth
    /// drawing partly; it is not worth a panic.
    pub fn displace(&self, rest: &[Vec3], clip: usize, time: f32) -> Vec<Vec3> {
        let weights = self.weights_at(clip, time);
        let mut out = rest.to_vec();
        for (target, weight) in self.targets.iter().zip(weights) {
            if weight.abs() < NEGLIGIBLE {
                continue;
            }
            for (point, delta) in out.iter_mut().zip(&target.deltas) {
                *point = *point + delta.scaled(weight);
            }
        }
        out
    }
}

/// `from` and `to` blended `across` of the way from one to the other.
///
/// Runs to the shorter of the two: a keyframe carrying fewer weights than the
/// file has targets is a file that disagrees with itself, and the targets it
/// does name still play.
fn mix(from: &[f32], to: &[f32], across: f32) -> Vec<f32> {
    from.iter()
        .zip(to)
        .map(|(start, end)| start + (end - start) * across)
        .collect()
}

#[cfg(test)]
pub(crate) mod fixtures {
    use super::*;

    /// Two targets over a three-vertex mesh: the first lifts vertex 0 by 1 on
    /// Y, the second pushes vertex 1 by 2 on X.
    pub(crate) fn two_targets() -> Vec<Pose> {
        vec![
            Pose {
                deltas: vec![Vec3::new(0.0, 1.0, 0.0), Vec3::ZERO, Vec3::ZERO],
            },
            Pose {
                deltas: vec![Vec3::ZERO, Vec3::new(2.0, 0.0, 0.0), Vec3::ZERO],
            },
        ]
    }

    /// The clip `bleck` writes: one pose at weight 1 at a time, stepping.
    pub(crate) fn stepping() -> Clip {
        Clip {
            name: "wave".into(),
            keys: vec![
                Key {
                    time: 0.0,
                    weights: vec![1.0, 0.0],
                },
                Key {
                    time: 1.0,
                    weights: vec![0.0, 1.0],
                },
            ],
        }
    }

    pub(crate) fn rest() -> Vec<Vec3> {
        vec![Vec3::ZERO, Vec3::ZERO, Vec3::new(5.0, 5.0, 5.0)]
    }
}

#[cfg(test)]
mod tests {
    use super::fixtures::{rest, stepping, two_targets};
    use super::*;

    fn animation() -> Animation {
        Animation::new(two_targets(), vec![stepping()]).expect("a playable animation")
    }

    #[test]
    fn a_file_with_no_targets_has_no_animation() {
        assert!(Animation::new(Vec::new(), vec![stepping()]).is_none());
    }

    #[test]
    fn a_clip_with_no_keyframes_is_dropped_rather_than_listed() {
        let empty = Clip {
            name: "still".into(),
            keys: Vec::new(),
        };
        assert!(Animation::new(two_targets(), vec![empty.clone()]).is_none());
        let mixed = Animation::new(two_targets(), vec![empty, stepping()]).expect("one plays");
        assert_eq!(mixed.clips().len(), 1);
        assert_eq!(mixed.clips()[0].name, "wave");
    }

    #[test]
    fn the_first_keyframes_weights_hold_before_the_clip_starts() {
        assert_eq!(animation().weights_at(0, -5.0), vec![1.0, 0.0]);
    }

    #[test]
    fn the_last_keyframes_weights_hold_past_the_end() {
        assert_eq!(animation().weights_at(0, 900.0), vec![0.0, 1.0]);
    }

    /// ⚠️ **The mutation this is written for.** A weight lookup that ignored
    /// `time` and always answered with pose 0 passes every "does it move"
    /// test; it fails here, because halfway is neither key.
    #[test]
    fn halfway_between_two_keys_lands_between_them() {
        let weights = animation().weights_at(0, 0.5);
        assert_eq!(weights, vec![0.5, 0.5]);
    }

    #[test]
    fn a_quarter_of_the_way_is_a_quarter_of_the_way() {
        assert_eq!(animation().weights_at(0, 0.25), vec![0.75, 0.25]);
    }

    #[test]
    fn an_unknown_clip_weighs_nothing_rather_than_panicking() {
        assert_eq!(animation().weights_at(9, 0.5), vec![0.0, 0.0]);
    }

    /// A clip whose keys all sit at one instant has no span to divide by.
    #[test]
    fn a_zero_length_clip_does_not_divide_by_its_length() {
        let flat = Clip {
            name: "held".into(),
            keys: vec![
                Key {
                    time: 0.0,
                    weights: vec![1.0, 0.0],
                },
                Key {
                    time: 0.0,
                    weights: vec![0.0, 1.0],
                },
            ],
        };
        let animation = Animation::new(two_targets(), vec![flat]).expect("playable");
        assert_eq!(animation.clips()[0].seconds(), 0.0);
        for weight in animation.weights_at(0, 0.4) {
            assert!(weight.is_finite(), "{weight}");
        }
    }

    #[test]
    fn the_first_pose_displaces_only_what_it_names() {
        let moved = animation().displace(&rest(), 0, 0.0);
        assert_eq!(moved[0], Vec3::new(0.0, 1.0, 0.0));
        assert_eq!(moved[1], Vec3::ZERO);
        assert_eq!(moved[2], Vec3::new(5.0, 5.0, 5.0), "an untouched vertex");
    }

    #[test]
    fn halfway_displaces_halfway_towards_each_pose() {
        let moved = animation().displace(&rest(), 0, 0.5);
        assert_eq!(moved[0], Vec3::new(0.0, 0.5, 0.0));
        assert_eq!(moved[1], Vec3::new(1.0, 0.0, 0.0));
    }

    /// Weight zero everywhere must reproduce the mesh exactly, not merely
    /// closely: a viewport that drifted at rest would look like a broken
    /// exporter.
    #[test]
    fn every_weight_at_zero_reproduces_the_rest_pose_exactly() {
        let silent = Clip {
            name: "none".into(),
            keys: vec![Key {
                time: 0.0,
                weights: vec![0.0, 0.0],
            }],
        };
        let animation = Animation::new(two_targets(), vec![silent]).expect("playable");
        assert_eq!(animation.displace(&rest(), 0, 0.0), rest());
        assert_eq!(animation.displace(&rest(), 0, 99.0), rest());
    }

    /// A target shorter than the mesh is a file disagreeing with itself. The
    /// vertices it reaches still move; nothing indexes past the end.
    #[test]
    fn a_short_target_moves_what_it_reaches_and_no_more() {
        let stubby = vec![Pose {
            deltas: vec![Vec3::new(1.0, 0.0, 0.0)],
        }];
        let clip = Clip {
            name: "one".into(),
            keys: vec![Key {
                time: 0.0,
                weights: vec![1.0],
            }],
        };
        let animation = Animation::new(stubby, vec![clip]).expect("playable");
        let moved = animation.displace(&rest(), 0, 0.0);
        assert_eq!(moved.len(), 3);
        assert_eq!(moved[0], Vec3::new(1.0, 0.0, 0.0));
        assert_eq!(moved[2], Vec3::new(5.0, 5.0, 5.0));
    }

    #[test]
    fn a_clip_reports_the_time_of_its_last_key_as_its_length() {
        assert_eq!(stepping().seconds(), 1.0);
        assert!(stepping().describe().starts_with("wave"));
    }

    /// ⚠️ **Nobody can look at this window.** A clip that plays perfectly in
    /// the data and never reaches the frame is invisible to every test above,
    /// so these assert on the pixels the rasteriser produced.
    mod on_the_frame {
        use crate::data::gltf;
        use crate::data::mesh::Mesh;
        use crate::render;

        const SIZE: render::Size = render::Size::new(96, 96);

        /// The mesh a file carrying two morph targets loads as.
        fn animated() -> Mesh {
            gltf::parse(&gltf::fixtures::animated_quad())
                .expect("the animated quad parses")
                .into_mesh()
        }

        /// The same quad with no targets and no clips.
        fn still() -> Mesh {
            gltf::parse(&gltf::fixtures::bare_quad())
                .expect("the bare quad parses")
                .into_mesh()
        }

        fn drawn(mesh: &Mesh) -> Vec<render::Rgba> {
            let view = render::View {
                camera: render::Camera::fit(mesh.bounds()),
                background: render::Background::DarkGrey,
            };
            let image = render::render(mesh, &view, SIZE);
            let mut pixels = Vec::with_capacity(SIZE.pixels());
            for y in 0..SIZE.height {
                for x in 0..SIZE.width {
                    pixels.push(image.pixel(x, y));
                }
            }
            pixels
        }

        fn lit(pixels: &[render::Rgba]) -> usize {
            let sky = render::Background::DarkGrey.pixel(0, 0, SIZE);
            pixels.iter().filter(|&&pixel| pixel != sky).count()
        }

        /// The whole point: two moments of one clip are two different pictures.
        #[test]
        fn a_clip_draws_differently_at_two_different_times() {
            let mut mesh = animated();
            mesh.pose(0, 0.0);
            let start = drawn(&mesh);
            mesh.pose(0, 1.0);
            let end = drawn(&mesh);
            assert!(lit(&start) > 100, "nothing was drawn at all");
            assert_ne!(start, end, "the frame did not change between poses");
        }

        /// ⚠️ Halfway is its own picture, not one of the two ends. A weight
        /// lookup that snapped to the nearest key would pass the test above.
        #[test]
        fn halfway_through_a_clip_is_a_third_picture() {
            let mut mesh = animated();
            mesh.pose(0, 0.0);
            let start = drawn(&mesh);
            mesh.pose(0, 1.0);
            let end = drawn(&mesh);
            mesh.pose(0, 0.5);
            let middle = drawn(&mesh);
            assert_ne!(middle, start);
            assert_ne!(middle, end);
        }

        /// A model with no clip must reach the frame exactly as it did before
        /// any of this existed — 646 of 864 exported models are in that state.
        #[test]
        fn a_model_with_no_animation_draws_the_same_whatever_it_is_asked_for() {
            let mut mesh = still();
            let before = drawn(&mesh);
            mesh.pose(0, 0.0);
            mesh.pose(3, 42.0);
            assert_eq!(drawn(&mesh), before);
            assert!(lit(&before) > 100, "the control drew nothing");
        }

        /// Scrubbing past the end holds the last pose rather than panicking or
        /// emptying the frame.
        #[test]
        fn scrubbing_far_past_the_end_holds_the_last_pose() {
            let mut mesh = animated();
            mesh.pose(0, 1.0);
            let end = drawn(&mesh);
            mesh.pose(0, 9_000.0);
            assert_eq!(drawn(&mesh), end);
        }

        /// A negative time is reachable by nothing in the window, and a
        /// rasteriser is not the place to find that out.
        #[test]
        fn a_time_before_the_clip_starts_holds_the_first_pose() {
            let mut mesh = animated();
            mesh.pose(0, 0.0);
            let start = drawn(&mesh);
            mesh.pose(0, -5.0);
            assert_eq!(drawn(&mesh), start);
        }
    }
}
