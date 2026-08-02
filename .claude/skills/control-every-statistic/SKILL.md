---
name: control-every-statistic
description: Use before reporting or believing any percentage, score, or "N of M agree" measurement — every statistic in this repo needs a control run through the identical code path, and the ones that skipped it produced confident wrong findings. Also covers producing a positive result before trusting a negative one.
---

# Control every statistic

**A number without a control is not evidence.** Every wrong finding in this
repo's record was a statistic that looked decisive and had nothing beside it to
say what "decisive" would be.

Two rules, and they are mirrors of each other:

1. **Ask what makes the test pass trivially**, not only what makes it fail.
2. **Before trusting a negative result, produce a positive one** — through the
   *identical* code path.

## The record

### D209 → D211 — 98.2% planar, inflated twice

Faces of a real mesh are planar; shuffled indices are not. First run: **98.2%
real vs 15.6% shuffled**, a six-fold gap on 125 shapes. Both flaws were in the
instrument.

- The first shape measured (`R_Arm_skin`) was nearly flat, so *any* four of its
  points were coplanar — and so was the control.
- ⛔ Worse, and caught only in D211: **16% of quads reference fewer than four
  distinct vertices, and a degenerate quad is planar for free.** `e_big_nok`
  scored **100% planar using three vertices**. The control drew four *distinct*
  random points, so it had to clear a bar the real faces were walking under.

Excluding degenerate faces: **72.4% vs 15.2%**. Still real, but the headline was
inflated. The test now excludes degeneracy and **asserts the gap, not the rate**,
so a future reading that made faces planar by construction would still have to
beat its own control.

### D214 — a blind statistic refuted a reading that was correct

A per-group position base scored **92.1% coverage** against 10.1% flat. Adopting
it was rejected because coverage had no control. Then one was built — shuffle the
bases among the groups:

| bases | planar | coverage |
|---|---|---|
| real, cumulative | 53.3% | 92.1% |
| **shuffled** | **49.8%** | **72.7%** |

A 3.5-point gap is nothing. Coverage was measuring "spreads indices across the
array at all", not "spreads them correctly. ⚠️ **Planarity could not see a wrong
group base either** — vertices are locally clustered. The measure that *did*
discriminate was **UV coherence** (D224), and per-shape rebasing turned out to
be right after all — the file states it (D240).

The lesson is not "the hypothesis was wrong". It is that **two measures
disagreeing means neither is confirmed**, and the fix is a third measure with a
control, not an argument.

### D229 — a candidate scored *below* shuffling and was briefly believed

Slot 17 looked like the shape→texture map: 38 entries, max 31, against 32 bank
images, paired 1:1 with a 38-record material table. Aspect-ratio test over 60
models whose texture aspects genuinely vary:

| mapping | within 15% |
|---|---|
| shape *i* → texture *i* | 31% |
| **shuffled control** | **24%** |
| **slot 17** | **23%** |

Worse than chance. Three candidates died there. Without the shuffle, 23% would
have read as "mostly works". The real binding is two indirections deep (D243).

### D245 — the dimension test first scored 1/24

Matching our texture binding against a third-party rip's, by image dimensions.
First run: **1 of 24**. A clean refutation, except that **DDS stores `dwHeight`
at offset 12 and `dwWidth` at 16** and the reader had them the other way round —
every row was an exact transpose.

With the control in place, the real numbers were **83/83, 193/195, 8/8** against
shuffled means of 13.6%, 24.4% and 31.2%.

⚠️ **A near-perfect *anti*-correlation is a bug signature, not a refutation.**

### D253 — a metric refuted by the corpus rather than tuned

"Surface detail" (mean brightness step between neighbouring pixels) was built to
tell a painted model from a bare one. The corpus killed it: `e_bari_bari`
carries no image and steps **0.099**, above 26 of 30 textured models, because
small facets read as texels; `OFF_doorL` is a sharp kanji and steps **0.006**,
because magnification reads as smooth.

⚠️ **It was refuted, not tuned.** Both refutations are now standing tests — one
asserts that an untextured model out-details a textured one — so if the numbers
ever swap, the reasoning is flagged as stale rather than quietly surviving.

## The mirror: produce a positive result first

Six runs and four decision-log entries (D70, D73, D74) went into a bug that did
not exist, because the rig read the current map from `seqWork.p0` — a field that
only means anything *during* a map change. Every entry was internally
consistent, had a control, and bisected cleanly. **A control does not help when
it is measured with the same broken ruler.**

So before "X did not happen", show the instrument can see X happening:

- **D246**: the "old path" control was the *real* file parsed and then every
  shape's `paint` forced to `Some(0)` — same rasteriser, same camera, same
  geometry. Asserted on first, because a colour count that cannot tell the two
  apart proves nothing. It caught something unexpected: the control drew **33%
  fewer pixels**, because every material is `alphaMode: MASK`.
- **D240**: `_hige` at **0.103°** and `_foot` at 1.386° through the identical
  oracle are what let a 0.269° corpus mean be believed. A random-base control
  sat at **88°**.
- **D243**: the image-content matcher was controlled before use — 46 disc images
  re-encoded as DXT1 and fed back, self-score ≥ 0.992, **46/46** recovered.
  ⚠️ And its limit was recorded: unrelated pairs reach 0.999, so "no match" from
  that instrument alone means nothing.

## Checklist before reporting a number

- [ ] What is the control, and does it run through the **same code path**?
- [ ] What would make this pass **trivially** — a degenerate case, a flat shape,
      a constant field, an empty set?
- [ ] Is the assertion on the **gap** rather than the absolute rate?
- [ ] If the result is a refutation: has the instrument been shown to detect a
      known-positive?
- [ ] If two measures disagree, is the conclusion "neither is confirmed"?
- [ ] Is a suspiciously *inverted* result a transpose or sign bug?

⚠️ **The opposite failure is real too** (D228): four cheap independent
measurements said the audio decoder was correct; one structure whose layout was
admitted to be not understood disagreed, and it carried the argument. **When a
single unexplained measurement contradicts several understood ones, suspect the
measurement.** When the proposed fix is "vary the working code until it
matches", stop — that is fitting, not decoding.
