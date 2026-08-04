# The effect format — `files/eff/effdata.dat`

**Living document.** What is true about the 139 effects on the disc, as one
reference rather than as the twenty-odd decision-log entries it was assembled
from. Companion to [`model-format.md`](model-format.md), which does the same
for the character models in `files/a/`.

⚠️ **The decision log is the chronology; this is the current answer.** Several
readings below supersede earlier ones, and the wrong turns are recorded at the
bottom rather than deleted — a refuted reading that is not withdrawn keeps
shipping (D252, D270).

Confidence is marked throughout: ✅ verified · 🔶 hypothesis · ⛔ ruled out.

---

## What is on the disc

| | |
|---|---|
| `files/eff/effdata.dat` | the effects: structure, curves, geometry, materials |
| `files/eff/effdata.tpl` | their 219 images. `bleck texture export` writes these |
| `files/eff/effdata_sub_*.dat` | per-language sub-banks, not yet read |

Measured over `eu0`: **139 effects, 704 parts, 3,739 nodes, 2,960 draws, 360
display lists, 4,752 curve commands, 524 materials, 350 samplers, 219 images.**

## The section table

✅ The file opens with a header of 16 section pointers. The evaluator holds it
in `r21`, so `lwz rN, 4*S(r21)` in the disassembly **names section `S`
outright** — the single observation that made the whole format readable (D266).

| section | holds | stride |
|---|---|---|
| 2 | curve samples | variable |
| 3 | GX display lists | variable |
| 4 | samplers (texture records) | 28 |
| 5 | materials | 16 |
| 6 | precomputed node matrices | 48 |
| 7 | groups | — |
| 8 | entries (draw records) | 8 |
| 10 | curve commands | 8 |
| 11 | texture coordinates | 8 |
| 12 | node vectors | 12 |
| 13 | vertex positions | 6 |
| 14 | vertex normals | **3** |
| 15 | vertex colours | 4 |

✅ The strides are not inferred from GX convention — the game states them in
`GXSetArray` calls (D266). ⛔ **Section 14's stride is 3, not 4.** D263 assigned
it by convention, got it wrong, and 4,598 indices fell out of range; three
independent routes now agree on 3.

## An effect, and how a draw is reached

An effect is a name, a base node index, and a list of parts. ✅ A part's `first`
is a node index **relative to the effect's base**, and the image it paints is
**five sections further on**: node → draw → subdraw → material → texture →
`effdata.tpl` index (D258).

⚠️ **Seven earlier candidates for the image were refuted** because every one was
looked for in or beside the part record. The answer was never a field.

⚠️ **A part issues a set of draws, not one.** 560 of 704 resolve to one image,
35 to none, and the rest to as many as twelve.

### The node record

| offset | field |
|---|---|
| `+0x00` | sibling index |
| `+0x02` | child index |
| `+0x08` | translate, into section 12 |
| `+0x0A` | rotate |
| `+0x0C` | scale |
| `+0x0E` | alpha, `u8` |
| `+0x0F` | billboard flag |
| `+0x10` / `+0x12` | curve run: first command, count |

✅ The walker is at **`0x8005f1a8`**, recursive, with the curve loop D266 read
at `0x8005f2d4` inside it (D282):

```
f(r3=EffData*, r4=base, r5=nodeIndex, r6=Mtx34* parentWorld,
  r7=u8 parentAlpha, r8=mirrorParity, f1=frame)
```

It composes into the child and passes through to the sibling. **Three values
travel that way** — the matrix, the alpha, and a mirror-parity flag toggled per
negative scale axis and used to swap `GXSetCullMode`.

## Curves — the file animates three different things

✅ `eff_sub.c` inlines the same evaluation loop **three times**, and all three
read the same record shape (D266, D281):

| what | at | slots | samples |
|---|---|---|---|
| a node's transform | `0x8005f2d4` | 10 | mixed |
| a material's RGBA | `0x8005c634` | 4 | `u8` |
| a texture's UV | `0x8005d040` | 5 | `f32` |

✅ Of section 10's 4,752 commands, **4,447 are reached by a node, 212 by
materials and 93 by textures — zero overlap, zero remainder** (D278). Section
2's unaccounted bytes fall from 36,745 to 942 once all three are counted; the
same exact-fill argument that settled the vertex arrays.

### The curve record

```
+0x00 u32  length in frames -- and the modulus when looping
+0x04 u16  first frame this curve speaks for
+0x06 u16  last frame
+0x08 u16  loop flag
+0x0A u16  sample format: 0 = f32, else u8
+0x0C      samples
```

Evaluation, branch for branch:

```
if loop:  while t < 0: t += length << 6;   t = int(t) % length
else:     if t < 0: t = 0;   if t >= length: t = length - 1
if t < start: leave the slot alone        <- not zero
t = min(t, end)
value = samples[int(t - start)]
```

⚠️ **`length << 6`**, not `length`, is what the game adds when normalising a
negative time. A plain `+= length` is the obvious guess and is wrong.

⚠️ **A curve overrides one slot and leaves the rest of the record alone.** A
material with only a red curve keeps its own green, blue and alpha; a node with
only a scale-Y curve keeps its own scale X. Measured in all three evaluators.

⚠️ **A curve that has not started returns nothing, not zero.** 44% of the
file's draws are flat at frame 0 and 26 effects draw nothing there — an effect
rendering as empty at frame 1 is usually correct (D265).

### The ten node slots

| slot | from | | slot | from |
|---|---|---|---|---|
| 0-2 | translate | | 6-8 | scale |
| 3-5 | rotate | | 9 | alpha |

✅ Read from the array the evaluator builds at `0x8005f22c`, not inferred.

## Alpha

✅ **Alpha is inherited, multiplicatively** (D282, `0x8005f734`):

```
composed = if own == 0 { 0 } else { (parent * (own + 1)) >> 8 }    // u8
```

⚠️ **Zero is absorbing**: a node whose own alpha is 0, or whose composed alpha
truncates to 0, **suppresses its whole subtree** while its siblings still walk.
⚠️ The game **truncates mod 256 rather than clamping**, so a curve overshooting
255 wraps.

✅ Where it lands, at `0x8005c7dc`:

```
finalA = ((globalA + 1) * (matA * (chainAlpha + 1))) >> 16
finalC = (matC * (globalC + 1)) >> 8          for R, G, B
```

✅ **Node alpha scales alpha alone, never RGB.** The global tint at
`effWork +0x88..0x8B` defaults to `FF FF FF FF`, so it is an identity multiply
unless a running game calls the setter at `0x8005fab0`.

## Materials and samplers

### Material, 16 bytes (section 5)

| offset | field |
|---|---|
| `+0x00`..`+0x03` | RGBA colour register |
| `+0x04` / `+0x06` | curve run: first, count |
| `+0x08` | 🔶 high byte set on 17 materials, unexplained |
| `+0x0A` | gate; 523 of 524 are 1 |
| `+0x0C` | section-4 sampler index |
| `+0x0E` | `0xFFFF` exactly when untextured |

⛔ `+0x0E` reads as a hidden second texture and is not: `+0x0A == 256`,
`+0x0E == 0xFFFF` and texture index −1 coincide on the same 20 materials.

291 of 524 materials are not white; 101 of 139 effects reach a tinted one.

### Sampler, 28 bytes (section 4)

| offset | field |
|---|---|
| `+0x00` | image index into `effdata.tpl` |
| `+0x02` | wrap byte |
| `+0x03` | flags — **bits 2-3 are the alpha type** |
| `+0x04` / `+0x08` | `f32` UV translate |
| `+0x0C` / `+0x10` | `f32` UV scale |
| `+0x14` | `f32` rotation, degrees |
| `+0x18` / `+0x1A` | curve run |

✅ The UV matrix is **`R · T · S`**, each block skipped when it would be the
identity. ⚠️ **The V translation is `1 - tv - sv`, not `tv`** — read it as `+tv`
and every scrolling texture runs backwards, and 75 of the file's 93 texture
curves drive exactly that slot.

✅ **The wrap byte is two bits per axis**, mirror winning over repeat (bit 0
S-repeat, 1 T-repeat, 2 S-mirror, 3 T-mirror), decoded at `0x8004cb54`.
Measured: 264 repeat/repeat, 67 clamp/clamp, 16 mirror/mirror, **3 mixed** —
⛔ so reading it as one mode for both axes gets 3 of 350 wrong, invisibly until
a UV coordinate leaves the unit square.

✅ **`+0x03` bits 2-3 are an alpha type**: 0 opaque, 1 cut-out, 2 translucent,
never 3 across all 350 records (D283). 🟢 Against the measured alpha channel of
the image each sampler names, **344 of 350 agree** and all 56 declared cut-out
are measured 1-bit.

## Geometry

✅ Effects are **indexed triangle fans**, not billboards (D263, D264). An entry
names a display list in section 3 and the vertex descriptor to read it under;
the same subdraw that names the material names the geometry.

⚠️ Positions are `s16` in raw file units and texture coordinates are unscaled
floats. **What one position unit is in the game's world is not established**, so
neither is converted on export.

⚠️ **Vertices are shared, not repeated per triangle.** Fans overlap heavily —
every quad of Dimentio's star carries the same centre.

## Blend modes

✅ The selector is the **high byte of a section 7 group's flags**, switched at
`0x8005c9f8`, and each case is one `GXSetBlendMode` (D270):

| value | call | meaning |
|---|---|---|
| **0** | — | **derive it, see below** |
| 1 | `NONE, ONE, ZERO` + compare always | opaque |
| 2 | `NONE, ONE, ZERO` + `GEQUAL 128` | cut-out |
| 3 | `BLEND, SRCALPHA, INVSRCALPHA` | alpha blend |
| 4 | `BLEND, SRCALPHA, ONE` | additive |
| 5 | `SUBTRACT, SRCALPHA, INVSRCALPHA` | `dst − src` |
| 6 | `BLEND, INVSRCCLR, INVSRCCLR` | electricity |

🟢 The semantic check: the 40 effects asking for mode 4 are `explosion`,
`dmen_explosion`, `event_fire`, `event_hammer`, `chaos_start` — glows and
flashes, every one. Mode 6's are `item_thunder`, `item_biribiri` — electricity.

### ✅ Selector 0 is "auto", and it is 2,528 of 2,960 draws

Derived at `0x8005c870`–`0x8005c9f8`, *before* the switch (D283). Three things
force mode 3: the sampler's **alpha type == 2**, **bit 15 of the section-8
vertex descriptor**, or an **evaluated colour alpha strictly between 0 and
255**. Otherwise the mode is `(accumulator & 1) + 1`.

⛔ **Selector 0 can only ever produce 1, 2 or 3.** Additive is unreachable
from it.

⚠️ **It is not a constant.** At rest the 2,528 split 280 opaque / 61 cut-out /
2,187 alpha blend, but the tested alpha is
`(material_alpha * (arg + 1) * (global + 1)) >> 16`, so **any instance fade
below 255 flips a 1 or a 2 into a 3** — 341 draws are exposed. ⛔ **An exporter
must carry the inputs, not a resolved mode.**

⚠️ Modes 1 and 2 **write depth**; 3, 4, 5 and 6 do not. ⛔ There is no
colour-keyed compare anywhere in the draw path.

## How the game draws one

| function | address |
|---|---|
| `effLookup(effect, part)` → `(effIdx << 16) \| partIdx` | `0x8005fc64` |
| `effDraw(handle, Mtx*, f32 frame)` | `0x8005f82c` |
| `effLife(handle)` → `max(Part.second)` | `0x8005fe84` |
| `dispEntry` — display-list submission | `0x8005af04` |
| the node walker | `0x8005f1a8` |

✅ **48 of 139 effects are drawn as several concurrent instances per frame**, a
lower bound (D277). ⚠️ Each instance is the *same* animation at a *different
age*, and ⛔ **the ages exist only at runtime** — no file records them, so a
viewer showing one instance is correct but incomplete. 85 of 139 effects have
two or more drawing nodes sharing one curve block, which is why several parts
render in the same place.

## What `bleck` exports

`bleck effect export` writes `effects.json` beside `models.json` and
`textures.json`. Schema 5 carries `meshes`, `nodes`, `curves`, `materials`,
`samplers`, and per draw a `mesh`, `chain`, `blend`, `translucent`, `material`
and `sampler`. A `samplers` row carries `alpha_type` beside its raw `flags`.

⚠️ **The viewer poses rather than being handed a pose.** An effect's transform
is a function of time, so shipping one frame's matrices would ship the one frame
that does not work.

⚠️ **The same applies to the blend mode, and for the same reason** (D284).
`blend` stays 0 where the file says 0; `alpha_type` and `translucent` are the
two static inputs of the derivation, and the third — the evaluated colour alpha
— is the value the reader has already composed for that frame. Baking a mode
would be wrong for 341 draws the moment an instance fades.

⚠️ **The derivation is applied per draw, where the game accumulates across the
group.** 2,520 of the 2,528 selector-0 groups hold exactly one entry, so the two
readings differ on 8 draws in 4 groups — 2 of them at rest, both in `heart_use`
(groups 145 and 191), which read cut-out per draw and alpha blend per group.
Carrying the group would mean exporting section 7's grouping, which nothing else
needs.

---

## Superseded readings

Kept because a refuted reading that is not withdrawn keeps shipping.

| claim | superseded by |
|---|---|
| the curve header's `+0x06` is a sample count | it is the **last frame** (D266) |
| curve samples are always `f32` | `u8` when `+0x0A` is set; the `-FLT_MAX` was a byte pattern (D266) |
| section 14's normal stride is 4 | it is **3** (D264, confirmed D266) |
| `heart_dance` has an emitter that respawns itself | `0x8005af04` is `dispEntry`; the loop is age/draw/expire (D277) |
| node alpha is not inherited | it **is**, multiplicatively (D282) |
| `spindash` is wholly transparent | its register is the first frame of an alpha curve (D281) |
| blend selector 0 means plain alpha | it means **derive** (D283) |
| `Effect.rows` / the transform-row table | deleted; the viewer poses from the node chain (D270) |

## Open questions

- 🔶 **The TEV stage configuration**, `0x8005d540`–`0x8005e0xx` — eight-plus
  variants of `GXSetTevOrder` plus colour/alpha In and Op, selected by something
  other than the blend switch, entirely unread. The only known state that could
  stop an opaque black texel painting black.
- 🔶 **What makes `dmen_warp` distort the screen.** A gameplay screenshot shows
  the scene smeared inside a hard-edged rectangle. ⛔ No framebuffer copy exists
  in the `dmen` modules; the mechanism is unaccounted for.
- 🔶 **Sampler `+0x03` bits 0-1** — bits 2-3 are the alpha type; the low two are
  unread.
- 🔶 **Material `+0x08`**'s high byte, set on 17 materials.
- 🔶 **Node `+0x0F`** is a **yaw-only** billboard subtracting the camera's
  `targetAngle` from `rotate.y` (D282). The value 3 is **not** a mode — a
  whole-DOL sweep finds only two reads, both testing against zero. Not honoured:
  the yaw is applied to the *local* rotation before the concat, so a billboarded
  node still inherits its parents' rotation.
- 🔶 The per-language `effdata_sub_*.dat` banks are unread.

## What a human has actually looked at

⚠️ Kept separate from everything above, which is measured rather than seen.

- ✅ `dmen_magic` renders as the purple shuriken with a distortion ring and a
  yellow four-pointed star — the gameplay screenshot.
- ✅ `map_derkness` past frame 240 is a purple vortex whose swirl arms move
  between frames.
- ✅ `explosion` is a yellow-orange fireball that fades out; `event_hammer` a
  flash fading to a white spark.
- ⛔ `dmen_warp` in game distorts the scene behind a rectangle. The viewer draws
  the rectangle. Nothing yet explains the distortion.
