---
name: ground-truth-from-reference-rips
description: Use when a decoded asset needs an external answer key — third-party rips under work/reference/ carry real material assignments and can validate a binding across a whole corpus. Covers the shape→usemtl→image chain, rigid-invariant matching, and why the matcher itself needs a positive control.
---

# Ground truth from reference rips

**A reference model turns "the verts look wrong" into a number.** D236's
comparison took minutes where four rounds of eyeballing had not converged.

## What exists, and where

```
work/reference/x/Brobot/           Brobot.obj, Brobot.mtl, Brobot.dae, *.dds, *.png
work/reference/x/Brobot L type/
work/reference/x/missile/
```

⚠️ **This exists only on this machine.** `work/` is git-ignored and stays that
way — these are third-party rips of game assets. `docs/handoff.md` lists
`work/reference/` under "what is not in git, by design", and **tests skip
without it**. A CI green run says nothing about these checks. If it is missing,
ask the user for the rips rather than reinventing the answer key.

The corresponding `bleck` models are `e_lui_robo`, `e_lui_robo_*` and
`e_lui_robo_missile` in `files/a`.

## What it settled

**D236 — geometry scale and origin.** Max Y matches to the hundredth: **100.83
in both**. That is the thing a wrong reading almost never gets. It also located
the real defect: the "fucked-up verts" were exactly **4 of 2,086** positions,
indices 0–3, in group 0 whose base is zero — read verbatim, not rebased. The
file genuinely holds that quad; the rip just did not export it. The defect was
the *merge* (92 shapes flattened into one glTF mesh), which is what D237 fixed.

**D243 — the shape→texture binding**, validated twice with controls.

## The chain

```
bleck shape  --(rigid-invariant key)-->  reference object
             --usemtl-->  MTL entry  --map_Kd-->  image file
             --(content match)-->  our extracted bank image
             ==?==  the image our binding picks
```

**Matching objects across the two sides** uses a *rigid invariant* — triangle
count plus total surface area, which no rotation or translation changes — and
keeps only keys unique on both sides. Everything downstream depends on this
being conservative, not complete.

### Test 1 — image dimensions

| | matched | agree | shuffled control |
|---|---|---|---|
| Brobot | 83 | **83 (100%)** | mean 13.6%, max 25.3% |
| Brobot L type | 195 | **193 (99.0%)** | mean 24.4%, max 33.3% |
| missile | 8 | **8 (100%)** | mean 31.2%, max 75.0% |

The two misses are one key collision on a 6-face `oya1Shape`.

⚠️ **The first run scored 1/24** — DDS stores `dwHeight` at offset 12 and
`dwWidth` at 16, and the reader had them the other way round. Every row was an
exact transpose. **Without the control that would have read as a refutation.**

### Test 2 — image content, and why the matcher needs its own control

⚠️ **The matcher is an instrument.** The rip's images are re-encoded (DXT1, some
twice), so exact hashes are worthless. The signature used is a 6×6 grid of
alpha-weighted RGB plus coverage, z-scored, taking the better of the two
vertical orientations.

- ✅ **Positive control first.** Each of the 46 disc images in these six banks
  was re-encoded as DXT1 and fed back to the matcher. Self-score **≥ 0.992**,
  and **46 / 46** came back as themselves (32) or as an image scoring ≥ 0.99
  against themselves (14 — the banks hold near-duplicates).
- ⚠️ **Its limit, recorded:** unrelated pairs reach 0.999 at the maximum and
  0.888 at the 95th percentile. Usable only with a threshold and an ambiguity
  check. **"No match" from this instrument alone means nothing.**
- ✅ **Composed:** shape → `usemtl` → rip image → bank image, against our
  binding. **61 of 61 agree** (18 Brobot, 43 Brobot L type, 0 missile — its
  images are too heavily re-encoded to clear the threshold). 207 further
  comparisons dropped as ambiguous. Shuffled controls: **38.4% and 56.5%**, high
  because these banks hold as few as two images.

### A third check falls out for free

**42 of the 46** shapes our reading calls *untextured* are given a flat 137-byte
placeholder image by the rip, and **0 of 286** textured shapes are. The ripper
invented a solid colour where the game draws with vertex colour — the same
statement from the other side, and it later became D251 (the tint is per-vertex,
in slot 5).

## ⛔ Refuted bridges — do not rebuild these

- **`Tex_0088_0.dds`-style numbering is not a game texture index.** The numbers
  run 0 to 460 across banks holding 2–24 images, jump between files, and do not
  order consistently with bank position. It is the ripper's own dump counter.
  Treating it as a second bridge would have been a fitted one.
- **Do not copy a third-party renderer's reading.** `SpmViewer` corroborated the
  texture-bank rule independently, but ⛔ **carries no licence of any kind** —
  which is stricter than GPL, not looser. Nothing was copied; every fact was
  re-verified against the disc. Its layer handling is also *wrong* (it binds
  only the first of consecutive layers), and its field names are inverted
  relative to ours.

## Using this on something new

1. Confirm `work/reference/x/…` is present; skip loudly if not.
2. Find a rigid invariant to match objects on. Discard non-unique keys.
3. Build the cheapest bridge first (dimensions), with a shuffled control.
4. If a stronger bridge is needed (content), **control the bridge itself** with
   known-positives before composing anything through it.
5. Report the shuffled baseline beside every score. On small banks the baseline
   is high — 56.5% here — and a score has to be read against it.
