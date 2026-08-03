//! What a reel measured, and the sentences it prints about it.
//!
//! Plain data and formatting: nothing here renders, loads or samples anything,
//! so a caveat can be reworded without touching the drawing.
//!
//! ⚠️ **Every verdict here is reported rather than judged**, and each field
//! says why. A reel is evidence for a person with no screen, and a confident
//! wrong verdict is worse than a number they can weigh themselves.

use crate::render::Size;

/// Depth-to-width ratio past which a fitted camera cannot show an effect
/// usefully. ⚠️ A **reporting** threshold, never a clamp: nothing is scaled or
/// dropped because of it, and 359 of the file's 360 display lists sit far
/// below it.
const DEEP: f32 = 4.0;

/// One cell of the reel.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Frame {
    /// The game's own frame number, counted from 1 the way the durations are.
    pub number: u32,
    pub time: f32,
    /// Parts the manifest says are running at `time`.
    pub active: usize,
    /// Draws those parts issued — one piece of geometry each.
    ///
    /// ⚠️ **Not the same as `active`, and usually larger.** A part issues a set
    /// of draws; `dmen_magic`'s six parts issue 31 pieces between them. This
    /// field exists because `active` briefly counted pieces and read as an
    /// effect with five times the parts it has.
    pub pieces: usize,
    /// How many of those **pieces** carried a decoded image into this cell.
    pub painted: usize,
    /// Draws the parts issued that were **not** turned into pieces, because the
    /// drawing node's alpha and the material's composed to nothing.
    ///
    /// ⚠️ **Reported, because it is invisible by construction.** A faded draw
    /// leaves no trace in the cell, so without this a frame that is empty
    /// because the data says so cannot be told from one that is empty because
    /// the export is stale — and the advice for those two is opposite (D280).
    pub faded: usize,
    /// How many of the **unpainted** parts can be told apart by colour.
    ///
    /// ⚠️ **Two separate ceilings, and both bite.** A painted part is drawn in
    /// its texture's colours, so its flat palette shade is not in the frame and
    /// searching for it would report it missing. And the palette holds only six
    /// colours before repeating, so a seventh unpainted part is drawn in the
    /// first one's shade. `visible` is measured against this rather than
    /// against `active`, which would report a fault on every textured effect.
    pub distinct: usize,
    /// How many of those distinct colours were actually found in the cell.
    ///
    /// ⚠️ Below `distinct` means a part did not reach the frame. That is
    /// usually occlusion — one quad in front of another, which the shared depth
    /// buffer is right to do — and only sometimes a fault. It is reported
    /// rather than judged.
    pub visible: usize,
    /// Share of the cell the effect covers, 0..1.
    pub drawn: f32,
}

/// What the run found, in the terms a caller with no screen can act on.
#[derive(Debug, Clone, PartialEq)]
pub struct Report {
    pub name: String,
    pub index: usize,
    pub parts: usize,
    pub seconds: f32,
    /// The effect's whole length in frames, which bounds how many can be shown.
    pub length: u32,
    pub sheet: Size,
    pub frames: Vec<Frame>,
    /// Consecutive cell pairs whose pixels differ at all.
    pub changes: usize,
    /// Parts that carried a real image anywhere in the reel.
    ///
    /// ⚠️ **Counted from the meshes, never written down.** It read zero until
    /// D258 decoded the binding, and it started reporting the truth the day it
    /// landed with nothing here to remember to change — the two tests asserting
    /// zero failed loudly instead of quietly staying right. Keep it derived.
    ///
    /// Zero now means one of two things, and the caveat names both: the parts
    /// genuinely draw nothing (35 of the file's 704 do), or the export predates
    /// the binding and wants `bleck effect export` re-run.
    pub painted: usize,
    /// Pieces drawn as a stand-in billboard rather than the effect's own shape,
    /// at the first frame.
    ///
    /// ✅ Zero on a current export: the geometry is decoded (D263). ⚠️ Non-zero
    /// means the manifest carried no mesh for a draw — an export predating the
    /// decoding — and **a billboard looks like a deliberate sprite**, so this
    /// has to be reported rather than left for the reader to notice.
    pub stood_in: usize,
    /// How much deeper the effect's geometry is than it is wide.
    ///
    /// ⚠️ **A fitted camera frames the whole box, depth included**, so a shape
    /// far deeper than wide is drawn a few pixels across and reads as an effect
    /// that renders nothing. One display list of the file's 360 is like this —
    /// `item_delete`'s is 640 units wide and 58,642 deep — and why is not
    /// established (D264). Reported rather than clamped: a rule invented here
    /// to make one effect look better would quietly reshape the other 358.
    pub depth_ratio: f32,
    /// The GIF frame delay actually used, in milliseconds, when one was
    /// written.
    ///
    /// ⚠️ **A GIF's unit is a centisecond**, so a 60 Hz effect cannot play at
    /// rate — one game frame is 1.67 cs. Reported rather than hidden: a GIF
    /// running at 2/3 speed otherwise reads as a slow effect.
    pub tick: Option<u32>,
}

impl Report {
    /// Whether every part the manifest called running reached its own cell.
    ///
    /// ⚠️ Measured against `distinct`, not `active` — see `Frame::distinct`.
    /// Against `active` this would report a fault for any effect with more than
    /// six parts, every time, on no evidence.
    pub fn parts_all_arrived(&self) -> bool {
        self.frames
            .iter()
            .all(|frame| frame.visible >= frame.distinct)
    }

    /// Whether the reel shows the effect doing anything over time.
    ///
    /// ⚠️ A one-part effect changes nothing between its first frame and its
    /// last, and that is correct rather than broken — the parts only start and
    /// stop, because no per-frame motion is decoded. So this is reported, not
    /// asserted, and a `false` for a single-part effect means nothing.
    pub fn moves(&self) -> bool {
        self.changes > 0
    }

    pub fn lines(&self) -> Vec<String> {
        let mut said = vec![
            format!(
                "{} — {} part(s), {:.2}s, {} frame(s) long",
                self.name, self.parts, self.seconds, self.length
            ),
            match self.tick {
                // ⚠️ Names the real playback rate. A GIF rounds every delay up
                // to a centisecond, so an effect sampled faster than that plays
                // slow — which reads as the effect being slow.
                Some(tick) => format!(
                    "{} frame(s) as a looping GIF at {tick}ms each ({:.1} fps)",
                    self.frames.len(),
                    1000.0 / tick as f32
                ),
                None => format!(
                    "{} frame(s) sampled into {}x{}",
                    self.frames.len(),
                    self.sheet.width,
                    self.sheet.height
                ),
            },
        ];
        said.extend(self.frames.iter().map(Frame::line));
        said.push(format!(
            "{} of {} frame pair(s) differ{}",
            self.changes,
            self.frames.len().saturating_sub(1),
            // ⚠️ Said, not judged. A one-part effect is identical from its
            // first frame to its last and is working perfectly.
            if self.moves() || self.frames.len() < 2 {
                ""
            } else {
                " — nothing changes across the reel"
            }
        ));
        // ⚠️ Never claim a clean check that was not made. A fully textured
        // effect has no part findable by its flat colour, so "every active part
        // reached its frame" would be true of a reel that drew nothing.
        let checkable: usize = self.frames.iter().map(|frame| frame.distinct).sum();
        said.push(if checkable == 0 {
            "no part is identifiable by colour here, so arrival was not checked \
             — the drawn percentages are the only evidence"
                .to_owned()
        } else if self.parts_all_arrived() {
            "every part identifiable by colour reached its frame".to_owned()
        } else {
            "some parts did not reach their frame — occluded, or missing".to_owned()
        });
        if self.faded_out() {
            said.push(format!(
                "⚠️ every draw was left out at every sampled frame because its alpha composed \
                 to zero — the material's own alpha register times the drawing node's. That is \
                 the data saying draw nothing, not a stale export, and more --frames will not \
                 change it (up to {} draw(s) in a frame) (D280)",
                // ⚠️ The largest, not the first frame's. A part whose scale has
                // not risen yet is dropped as flat before its alpha is ever
                // composed, so frame 1 of a fading effect can report none.
                self.frames
                    .iter()
                    .map(|frame| frame.faded)
                    .max()
                    .unwrap_or(0)
            ));
        } else if self.never_posed() {
            said.push(
                "⚠️ every sampled frame posed this effect flat, so nothing was drawn — its                  scales rise from zero on their own curves and none had risen yet. Try more                  --frames (D266)."
                    .to_owned(),
            );
        }
        if self.too_deep() {
            said.push(format!(
                "⚠️ this effect's geometry is {:.0}x deeper than it is wide, so a \
                 camera fitted to it draws the visible face small — the depth is \
                 in the file and why is not established (D264)",
                self.depth_ratio
            ));
        }
        if let Some(blank) = self.blank_frame() {
            said.push(format!(
                "⚠️ frame {blank} drew nothing though its parts carry images — much of this \
                 bank is sparse art (one bolt lights 20 of 512 texels), and at a small --size \
                 a quad can miss every lit texel. Re-run at --size 320 before believing it."
            ));
        }
        said.push(self.caveat());
        said
    }

    /// Whether a fitted camera is being stretched by depth the viewer cannot
    /// show — the one cause of a blank cell that raising `--size` will not fix.
    pub fn too_deep(&self) -> bool {
        self.depth_ratio > DEEP
    }

    /// Whether every sampled frame posed the effect flat, so nothing was drawn
    /// anywhere in the reel.
    ///
    /// ⚠️ **Not a fault, and not the same as "no images".** An effect's scales
    /// rise from zero on curves of their own; if none of them has risen at any
    /// frame this reel happened to sample, there is genuinely nothing to draw.
    /// More `--frames` may find it (D266).
    pub fn never_posed(&self) -> bool {
        self.frames.iter().all(|frame| frame.pieces == 0) && !self.faded_out()
    }

    /// Whether the reel is empty because every draw's alpha composed to zero.
    ///
    /// ⛔ **Not the same as `never_posed`, and the advice is opposite.** A part
    /// whose scale has not risen yet may draw at some other frame, so more
    /// `--frames` can find it; a material carrying alpha 0 draws at no frame
    /// ever. `spindash` is the export's one wholly transparent effect and was
    /// told to re-run the exporter until this existed (D280).
    pub fn faded_out(&self) -> bool {
        self.frames.iter().all(|frame| frame.pieces == 0)
            && self.frames.iter().any(|frame| frame.faded > 0)
    }

    /// The first frame that drew nothing despite having a painted part.
    ///
    /// ⚠️ **Not a fault on its own.** Nearest-neighbour sampling of a sparse
    /// sprite into a handful of pixels can land entirely on transparent texels;
    /// `item_thunder` blanks at `--size 64` and draws at 128. Reported so the
    /// reader raises the size rather than filing a bug against the export.
    pub(super) fn blank_frame(&self) -> Option<u32> {
        self.frames
            .iter()
            .find(|frame| frame.drawn == 0.0 && frame.painted > 0)
            .map(|frame| frame.number)
    }

    /// ⚠️ Printed on every run, deliberately. The images are measured and the
    /// **placement is not**, and a sheet that shows real artwork in invented
    /// positions is far more convincing than one drawn in flat colours — so the
    /// half that is still a display choice has to be said out loud every time.
    fn caveat(&self) -> String {
        if self.faded_out() {
            return format!(
                "no part of {} reached the frame: every draw it issues composes to zero alpha, \
                 so the export is being read correctly and there is nothing to paint (D280)",
                self.name
            );
        }
        if self.painted == 0 {
            return format!(
                "no part of {} carries an image — either they genuinely draw none, or this \
                 export predates the part-to-image binding (D258); re-run `bleck effect export`",
                self.name
            );
        }
        let shape = if self.stood_in == 0 {
            "each posed as its own geometry (D263, D266)".to_owned()
        } else {
            format!(
                "⚠️ {} piece(s) fell back to a stand-in billboard, so this export carries no \
                 geometry for them — re-run `bleck effect export`",
                self.stood_in
            )
        };
        format!(
            "{} of {} part(s) drew a decoded image (D258); {shape}. ⚠️ A part whose scale has \
             not risen from zero yet draws nothing at that frame — that is the data, not a \
             fault: 44% of the file's draws are flat at frame 0.",
            self.painted, self.parts
        )
    }
}

impl Frame {
    /// One row of the report.
    fn line(&self) -> String {
        // The ceiling is only worth naming when it bites; on the great
        // majority of effects it equals the active count and saying so
        // every line would bury the numbers that vary.
        // ⚠️ Against `pieces`, not `active`. `painted` counts pieces and a
        // part issues several, so `active - painted` underflows on any
        // effect with more than one draw per part — silently in release,
        // and `dmen_magic` alone would hit it.
        let unpainted = self.pieces.saturating_sub(self.painted);
        // Only worth a column when there is something in it. On a fully
        // textured effect "0 of 0 plain found" is noise in every row.
        let plain = if unpainted == 0 {
            String::new()
        } else if self.distinct < unpainted {
            format!(
                ", {} of {} plain found ({} tellable apart)",
                self.visible, unpainted, self.distinct
            )
        } else {
            format!(", {} of {} plain found", self.visible, unpainted)
        };
        // ⚠️ Only when something faded. A column of ", 0 faded" on every row of
        // every effect would bury the frames where it is the whole story.
        let gone = if self.faded == 0 {
            String::new()
        } else {
            format!(", {} faded out", self.faded)
        };
        format!(
            "  frame {:>4} at {:>6.3}s — {} part(s), {} piece(s), {} painted{}{}, {:.1}% drawn",
            self.number,
            self.time,
            self.active,
            self.pieces,
            self.painted,
            gone,
            plain,
            self.drawn * 100.0
        )
    }
}
