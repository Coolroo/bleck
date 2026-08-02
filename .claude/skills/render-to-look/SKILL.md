---
name: render-to-look
description: Use when a model, effect, texture or animation export needs eyes on it and you have no screen — `dimentio shot` renders a .glb to a PNG contact sheet and `dimentio reel` renders an effect across its own timeline, both readable directly instead of costing a human a day of round trip. Covers the flags, the self-checks and their blind spots.
---

# Render to look

**Five rounds of controlled statistics told us less than one human screenshot.**

Every model defect in this repo's record was found by a person opening Blender:
D223's bow-ties, D229's "small mimis on a big mimi", D234's bare model, D236's
stray quad, D252's "insane, not accurate" animation. Each round trip cost a day,
and every hour of it was a person being asked to be a display.

`dimentio`'s viewport has been a **software rasteriser since D213** — a
`Vec<u8>`, no GPU, no window, no driver — precisely because this machine cannot
capture its own desktop. Nothing was reading it except the window. `dimentio
shot` (D253) reads it into a file.

## The command

```powershell
cargo run --release --manifest-path dimentio/Cargo.toml -- `
  shot work/export/models/files/a/e_lui_robo.glb --out shot.png
```

Then `Read` the PNG. That is the whole loop.

| flag | |
|---|---|
| `--out <file.png>` | required; there is nowhere else to write |
| `--angles <n>` | views around the model, **into one contact sheet**. Default 4, range 1–16 |
| `--clip <n>` | morph clip to pose, by index. Default 0 |
| `--frame <f>` | keyframe of that clip to hold. Default: the rest pose |
| `--background <s>` | `dark-grey` \| `checkerboard` \| `gradient`. Default checkerboard |
| `--size <px>` | cell edge. Default 512, range 16–4096 |

A bare `dimentio` and `dimentio <folder>` still open the window; only the
literal first argument `shot` diverts.

## Why it is shaped this way

- **Several angles into one image, not one file each.** Most defects are visible
  from one direction only, and the file not opened is the one that showed it.
  Views are evenly spaced from the front, 0.35 rad above the horizon — a
  model's top is where an exporter's mistakes collect.
  ⛔ Four hand-picked poses were rejected: they stop meaning anything the moment
  `--angles` is not 4, and the axis-aligned views are the informative ones. A
  flat card that vanishes edge-on is a *fact about the model*; two of `p_bibi`'s
  four cells being empty is the picture saying so.
- **Never white.** A texture decoding to near-white and a texture that failed to
  decode are the same image on a white page (D251). Checkerboard by default,
  with a `(120,124,132)` gutter in a colour neither background uses.
- ⛔ **A missing clip or frame is an error, not the rest pose.** A believable
  image of the wrong thing is the failure mode this tool exists to prevent.
- Camera fitted from the bounding box, so nothing is off-screen.

⚠️ It worked on the first model it was pointed at, and the first thing it showed
was **D236's stray quad** — the Mario sprite 130 units to the side of
`e_lui_robo`, textured, plainly separate, in two of four cells and edge-on in
the other two. That took a person and a day the first time.

## The self-check, and what it cannot see

The tool measures its own output, because a screenshot tool that emits a
plausible image for a broken model is worse than none.

**Colour spread** — RMS scatter of each drawn pixel's tint about the frame mean,
**with luminance divided out**, because shading alone swings a bare surface from
ambient to full and raw RGB variance cannot tell a lit grey model from a painted
one.

⛔ **Spread no longer means "an image reached it", and the table that said so is
gone** (D251). Once the renderer learned to draw `COLOR_0`, 41 models that name
no image at all became vividly coloured. Measured on this export today:

| model | images | spread |
|---|---|---|
| `e_big_nok` | **0** | **1.426** |
| `e_lui_robo` | 15 | 0.786 |
| `OFF_doorL` | 2 | 0.011 |

The bare model is now the *most* colourful of the three. **`images`, read from
the file, is the verdict**; spread only says the frame is not one flat tint,
which is a weaker and true statement. The three verdict strings are `an image
reached it`, `no image: drawn with vertex colour`, and `no image, and one flat
tint`.

⚠️ **Spread still cannot see a greyscale image.** `OFF_doorL` carries two images
and reads 0.011, under the 0.015 threshold. Both numbers are always printed.
**Do not read a low spread as "the texture binding is broken."**

⛔ **"Surface detail" is reported and decides nothing.** It was meant to catch
exactly the greyscale case, and the corpus refuted it rather than tuning it
(D253): `e_bari_bari` carries no image and steps **0.099**, above 26 of the 30
textured models, because small facets read as texels; `OFF_doorL` steps
**0.006**, what a bare cube steps, because one texel covers many pixels. Both
refutations are standing tests, one asserting that an untextured model
out-details a textured one — so if the numbers swap, the reasoning is flagged
stale.

## Effects: `dimentio reel`

An effect has no shape to walk around; it has a **timeline**. So the effect
command is one angle at several *instants*, laid out in the same grid (D257):

```powershell
cargo run --release --manifest-path dimentio/Cargo.toml -- `
  reel --effect chaos --export work/export --out chaos.png --frames 9
```

| flag | |
|---|---|
| `--effect <name>` | required; as `bleck effect list` names it |
| `--out <file.png>` | required |
| `--export <dir>` | folder holding `effects.json`. Default `work/export` |
| `--frames <n>` | frames sampled across the effect. Default 9, range 1–64 |
| `--size <px>` | cell edge. Default 320 |
| `--background <s>` | as for `shot` |

⛔ **The sheet shows the timeline, not the artwork.** Which image a part draws is
still undecoded (D210 refutes six fields; D218 puts the reference one hop
further), so every part is a flat colour from a **six-entry palette** and its
position is a display choice. The report says so on every run. **Never quote a
reel as "what this effect looks like."**

What it settles is that the data and the renderer agree — per frame it prints
the parts the manifest calls running, how many reached the pixels, and the area
drawn:

```
chaos — 4 part(s), 3.00s, 181 frame(s) long
  frame    1 at  0.000s — 4 active, 4 visible, 5.2% drawn
  frame   69 at  1.125s — 2 active, 2 visible, 2.5% drawn
  frame  136 at  2.250s — 1 active, 1 visible, 1.5% drawn
```

⚠️ **`visible` is measured against `distinct`, not `active`** — the palette
repeats after six, so a seventh part is drawn in the first one's shade and the
pixels cannot separate them. Comparing against `active` would report a fault for
every effect with more than six parts, forever.

⚠️ **A part is still running at exactly its own duration.** The end is
inclusive, so sampling five frames over a 2 s effect whose second part lasts
0.5 s gives `2, 2, 1, 1, 1`.

## What this does not replace

⛔ **A render by the program under test is not independent of it.** The sheet
shows what *the rasteriser* draws, which is not always what Blender draws — and
when the two disagree, that is a finding about one of them, not proof about the
export.

What it removes is the round trip for everything short of that: a defect visible
in a contact sheet no longer costs a day to hear about. Still ask a person for
the final confirmation on a claim like "the animation now looks right" — and
when you do, re-export first and check the mtime (D245).
