# The character model format — `files/a/`

**Living reference.** What a character model file holds, how to read it, and
what is still unread. Every claim carries the decision-log entry that
established it and one of ✅ verified · 🔶 hypothesis · ⛔ ruled out.

This is the *format*. How the export is shaped — glTF, primitives, budgets — is
at the end, because a reader who wants the bytes should not have to walk through
a file writer to reach them.

Read alongside:

| | |
|---|---|
| `bleck/formats/model.py` | the container — name, bounds, name blocks, section table |
| `bleck/formats/modelarrays.py` | the section table at `0x150` and its vertex arrays — positions, normals, colours, texture coordinates |
| `bleck/formats/modelmesh.py` | the `Mesh` those arrays land in, and how a face is triangulated |
| `bleck/formats/modelrebase.py` | the group and shape records — which slice of those arrays each shape indexes |
| `bleck/formats/modelbase.py` | `Face`, `Shape`, the error type and the name field |
| `bleck/formats/modelanim.py` | the clip table and its morph poses |
| `bleck/formats/modelmat.py` | the layer, material and transform tables — which image a shape draws, how it is wrapped and where |
| `bleck/formats/gltf.py` | the `.glb` writer |
| `bleck/formats/gltfpaint.py` | its materials, samplers, textures and images |
| `scripts/modelscan.py` | `survey`, `header`, `offsets`, `at`, `strings`, `vectors`, `streams`, `chain`, `mesh` |
| [`model-appearance.md`](./model-appearance.md) | what six of these models are *supposed* to look like, with a source per claim (D255) |

⚠️ **Some docstrings in those files are older than this page.** The
contradictions are listed under [Where the code and the log
disagree](#where-the-code-and-the-log-disagree) rather than quietly resolved.

---

## What is on the disc

✅ `files/a/` holds **1,687 files in pairs** (D202): `name` is the model and
`name-` is a TPL image bank beside it. D204's inventory: **815 banks, 870 model
files and 2 `.bin`** — nothing else in the directory.

| | |
|---|---|
| ✅ model files that read as a container | **869 of 872** (D202); the two refusals are the `.bin` files |
| ✅ files whose geometry `mesh()` accepts | **864 of 870** (D207) |
| ✅ pairs where the texture-reference count is checked | **787** (D202) |

✅ **A model names its textures by their original TGA source path** —
`ara/playar/mario/w_tex/R_arem.1.tga` — and the count matches the bank's image
count. Across all 787 pairs: 773 equal, 14 fewer references than images, and
**zero** with more references than images (D202). ⛔ **That zero is the
invariant.** A bank may carry images nothing names; a model never names an image
its bank lacks. Without the direction being clean the pairing would be a
coincidence of counts.

⛔ **It is not `map.dat`'s format.** Room geometry announces its sections in a
string table (`mesh`, `material_name_table`, `animation_table`, D167); none of
those markers appears in a character file (D202). Two containers, decoded
separately.

---

## The two regions

✅ **The file's leading `u32` splits it** (D212). In `p_wii_mario` that word is
`0x15F5C`, which is exactly the boundary D202 measured between the tables and
200 KB of dense packed data.

```
0x000000  front region  -- header record, node/joint records, materials,
                           texture paths, shape section table, name blocks
0x015F5C  record chain  -- animation clip data, each record prefixed by its
                           own size, the next starting immediately after
0x0313xx  end of file
```

✅ The record the leading word points at confirms itself: six floats at `+0x44`
are `(-30.0, -14.68, 0.0)..(10.775, 58.7, 3.2)`, the bounding box already
measured independently, which is why `Bounds` reads Mario as **73.4 units tall**
(D202, D212).

⛔ **Every earlier scan walked over the chain**, because its records use offsets
**relative to their own base**, not file-absolute ones (D212). Small values like
`0x5c`, `0x68`, `0x94` read as counts, so an 8 KB sweep past the boundary
reported "no ascending offset table" while sitting on one.

⚠️ **The chain's record count is reported three different ways** and no entry
reconciles them: 40 contiguous records (D212), "all 80 chain records are exactly
clip starts" (D216), 94 record sizes summing to exactly 201,580 bytes (D205).
The number `bleck` actually uses is the clip table's own entry count, not a walk
of the chain. Treat the walk counts as measurements of different things until
someone re-measures.

---

## The section table at `0x150`

✅ **A shape record lists its data sections here**, as file-absolute offsets.

⛔ **The word at `0x14C` is not a name pointer.** It points at the **group
table** — 168-byte records that state where each shape's indices start (D240).
Reading its first record's `char name[0x40]` field is why it looked like one, and
why `mesh()` still reports `R_Arm_skinShape` for `p_wii_mario`: that is group 0's
Maya name, not the model's.

`modelarrays.py` reads **24 entries** (`FULL_SECTIONS`) from `SHAPE_SECTIONS_AT =
0x150`, and validates the first eight as strictly ascending offsets inside the
file. `model.py` separately locates the table **by structure** — the longest run
of ascending in-file offsets in the first 1 KB — and finds **26 entries starting
at `0x148`** in every one of the 870 models (D203).

🔶 **Those are the same run read from two starting points.** `0x148 + 2 × 4 =
0x150` and `26 − 2 = 24`, so the arithmetic is exact — but no decision-log entry
says so outright, so it is recorded here as an inference rather than a finding.
`model.py` uses the wider run only for its last two entries, which bound the
joint-name block and the clip-name table.

### What each slot is

Offsets are `p_wii_mario`'s, and the "what" column is what `bleck` reads today.

| slot | at | `p_wii_mario` | what it is | how established |
|---|---|---|---|---|
| 0 | `0x150` | 192 words = **96 faces** | **face list** — `(first corner, corner count)`, 8 bytes each | ✅ D208 |
| 1 | `0x154` | **324 positions** | **positions**, big-endian F32 XYZ, stride 12 | ✅ D207 |
| 2 | `0x158` | 336 entries, 23 distinct | **corner → position index**, `u16` in a `u32` | ✅ D209 |
| 3 | `0x15C` | **336 normals** | **normals**, F32 XYZ, stride 12, unit length | ✅ D207 |
| 4 | `0x160` | 336 entries, 0..335 | **corner → normal index** | ✅ D207, D208 |
| 5 | `0x164` | 336 entries of 4 bytes | **vertex colours**, `GX_RGBA8`, stride 4 | ✅ D251 |
| 6 | `0x168` | 490 entries | **corner → colour index** | ✅ D251 |
| 7 | `0x16C` | 153 entries, 23 distinct | **corner → UV index** for channel 0, one per corner | ✅ D234 |
| 8..14 | `0x170`+ | one offset, repeated | **UV index streams for channels 1–7**, empty on every model | ✅ D240, D247 |
| 15 | `0x18C` | 2 floats × coordinates | **the texture-coordinate array itself** | ✅ D240, D247 |
| 16 | `0x190` | 24 bytes × layers | **per-layer animation offset and UV transform** | ✅ D247 |
| 17 | `0x194` | 8 bytes × layers | **layer records** — `+0x00` a material index, `+0x04` the wrap mode | ✅ D243, D247 |
| 18 | `0x198` | 64 bytes × materials | **material records** — `+0x04` the bank image index, `+0x08` a mode the draw code branches on, `+0x0C` the source TGA path | ✅ D243 |
| 19 | `0x19C` | 108 bytes × shapes | **shape records** — layer count and list, material mode, UV channel per layer, first face, face count, and the corner offset of each index stream | ✅ D240, D243, D247 |
| 20 | `0x1A0` | 176 bytes, 108 of them `01` | **per-node visibility** — one `u8` a node, `0` meaning off | ✅ D289 |
| 21 | `0x1A4` | 96 bytes × **nodes** | **node transforms** — translate, scale, rotation in degrees, and a pivot | ✅ structure D287, 🔶 fields |
| 22 | `0x1A8` | 88 bytes × **nodes** | **node records** — a name, previous sibling, last child, and the shape it draws | ✅ D287 |
| 23 | `0x1AC` | — | ⛔ **unread** | — |

⛔ **Slots 21 and 22 are a scene graph, and nothing reads it** (D287). `bleck`
exports every model in its **rest state, unposed**: 489 of 869 models carry at
least one node that is not the identity, and 5,473 of 27,400 nodes do.

✅ **Slot 20 says which nodes to draw at all**, and `bleck` does read it (D289).
One `u8` per node, padded to a multiple of four, `0` meaning off; slot 22's
`+0x48` names the shape each node draws, so the two give the shapes to hide.
**2,427 of 17,597 drawn shapes are off**, on 346 of 869 models.
⚠️ The section is *not* "32 bytes of `01`" — that reading came from a model with
few nodes, and it is why the slot sat marked unread while carrying the answer to
"why does this model look wrong".

⚠️ **The draw code loads slots 7–14 as *index* streams, not channel data.**
`lwzx r0, r24, r5` picks `0x16C + channel × 4`, so `0x16C`…`0x188` are eight
per-channel UV index streams and `0x18C` is the coordinate array itself (D240).
⛔ **D208's addendum put channel 0 at slot 8 and is superseded**: slot 7 is
channel 0. `_uvs()` reads from `table[8]` to the next *different* entry and
lands on the right bytes anyway, because every channel above 0 is empty on this
disc — all 870 models have slots 8–14 equal to slot 15 (D247).

### Slot 16 — how a layer is sampled

✅ **24 bytes per layer, 1:1 with slot 17 on all 870 models** (D247). The draw
code indexes it by layer index × 24 in two loops: one adds `+0x00` to the
material index, the other builds a texture matrix from the five floats.

| field | what |
|---|---|
| `+0x00` | `u8` **frame offset** added to the layer's material index at runtime — how a texture animates without the file changing |
| `+0x04` / `+0x08` | translate U and V. ⚠️ The V the code uses is `1 - v - scale_v` |
| `+0x0C` / `+0x10` | scale U and V |
| `+0x14` | **rotation in degrees**, about the middle of the image `(0.5, 0.5)` |

✅ Composed as `rotate × translate × scale`, each factor built only when it is
not the identity, dispatched through an 8-entry jump table at `0x80407D50`.

⚠️ **The default record still builds a translation matrix.** `+0x10` is one of
the three fields tested, so `(0, 0, 1, 1, 0)` takes the branch — and translates
by `(0, 1 - 0 - 1)`, which is nothing. Ask the composed matrix whether a layer
moves, never the branches.

**130 of 7,300 records are not the identity.** `MOBJ_EFF_mahojin_omote` rotates
by 45°, 61°, 45° and 360°; the four `OFF_door*` models scale U by **-1**, which
is how one door mirrors the other; `MOBJ_bom` translates by -2.5.

### Slots 5 and 6 — the vertex colour that multiplies the texture

⛔ **This page said slots 5 and 6 were "read by nothing" and that was the whole
bug behind D251.** They are the per-vertex colour array and its index stream,
and the draw code names both:

```
80048594: li r3,11 ; li r4,3    GXSetVtxDesc(GX_VA_CLR0, GX_INDEX16)
800485a4: li r4,11 ; li r5,1    GXSetVtxAttrFmt(fmt0, GX_VA_CLR0,
800485ac: li r6,5                                GX_CLR_RGBA, GX_RGBA8, 0)
800485b8: mr r4,r15 ; li r5,4   GXSetArray(GX_VA_CLR0, r15, stride 4)
```

with `r15 = lwz r3,356(r6)` — `0x164`, slot 5 — and the inner loop's fourth
`lhz`/`sth` pair reading slot 6 at `corner + shape[0x48]`.

✅ **Mode 0's TEV is `GX_MODULATE` against `COLOR0A0`** (D247), so the texture
is *multiplied* by this. ⛔ **The disc stores one greyscale panel and tints it
per shape**: `e_lui_robo`'s 200×80 body panel decodes to a mean of 243 in all
three channels, and the rip's `red.dds` of the same panel is (189, 40, 41) —
which is exactly the panel times `(198, 39, 39)`, the vertex colour the file
gives that shape. Leaving it out is why a person reported Brobot as
"almost entirely white" with every rivet and vent plainly visible.

| | |
|---|---|
| models carrying a colour array | **864 / 864** |
| colour indices inside their own array | 864 / 864, **zero strays** |
| group records whose colour slice is `(0, 0)` | **17,290 / 17,290** |
| shape records where the colour corner offset equals the position one | **18,631 / 18,631** |
| models that are opaque white throughout | 524 |
| models carrying more than one distinct colour | **331** |

⚠️ **Unlike UVs, colours need no per-group base and no separate corner
offset** — the two tables above are why. Reading slot 6 like slot 4 is correct;
reading it like slot 7 would not be.

⚠️ **A channel's length runs to the next *different* table entry.** All eight
channel slots carry the same offset when one channel is in use, so the obvious
`table[n+1] - table[n]` is zero and reads as no data (D215). `_uvs()` takes the
smallest later entry that is larger.

⛔ **D208's reading of `+0x16C` as an array of per-texcoord pointers is
superseded.** D234 identifies it as the texcoord *index* stream, and the channel
pointers as slots 8 onward.

### Why the vertex format is a reading and not a guess

✅ **It is read off the game's own draw code** (D207), not pattern-matched out of
the file. Four attempts to find Mario's mesh by scanning failed or misled; what
worked was `dolscan.py callers 0x8028EA78` → the five call sites in the
character-animation range → disassembling `0x80048400`, where the game **states**
the format:

```
80048528: bl 0x8028ea44        GXClearVtxDesc()
8004852c: li r3,9 ; li r4,3    GXSetVtxDesc(GX_VA_POS,  GX_INDEX16)
8004854c: bl 0x8028ea78        GXSetVtxAttrFmt(fmt0, GX_VA_POS, GX_POS_XYZ, GX_F32, 0)
8004855c: bl 0x8028f13c        GXSetArray(GX_VA_POS, r16, stride 12)
80048560: li r3,10; li r4,3    GXSetVtxDesc(GX_VA_NRM,  GX_INDEX16)
80048580: bl 0x8028ea78        GXSetVtxAttrFmt(fmt0, GX_VA_NRM, GX_NRM_XYZ, GX_F32, 0)
```

The runtime offsets `+0x158`/`+0x160`/`+0x168`/`+0x16C` the inner loop reads from
are **file** offsets: the loader relocates in place.

⛔ **D204's "positions are s16 with a scale exponent" is ruled out.** GX *can*
quantise positions; this game does not (D207).

⚠️ **`xref` could not have found this.** It tracks how the game builds an
*address* — `lis`/`addis`/`addi` — which is right for data and wrong for code,
since a `bl` encodes a signed displacement. Asking it who calls `GXSetVtxAttrFmt`
returned nothing, which reads as "nothing calls it" for a GX entry point in a
shipping game. `dolscan.py callers` was added for exactly this and found **178**
(D206).

### The two checks that make `mesh()` refuse rather than guess

✅ **Every normal is unit length.** Nothing else in a binary does that, and a
wrong offset or stride scatters immediately. It holds on **864 of 870** models,
so `mesh()` checks it and refuses the other six (D207).

✅ **The face corner counts sum to exactly the index-stream length** — 96 faces
covering 336 corners in `p_wii_mario`, against 336-entry streams. A wrong stride
or a wrong slot gives a sum that misses (D208).

Face shapes across the whole disc, which is what a Maya polygon export looks
like (D208):

| corners | faces |
|---|---|
| 3 | 11,172 |
| 4 | 54,403 |
| 5 | 1,044 |
| 6–32 | 587 |

So these are **polygons, not strips**, which is why `GXBegin` is reached with
`GX_QUADS` (`li r3,160`) on one branch of several.

---

## Per-shape rebasing — the finding that made models readable

✅ **The single most important thing on this page** (D224). A file's faces are
grouped by shape, a group restarts its `first` at zero, and **both the corner
offset and every index it reaches are relative to the shape, not the file.**

| | before | after (D224) | after (D240) |
|---|---|---|---|
| median coverage | 13.7% | **100.0%** | 100.0% |
| mean coverage | — | 98.6% | **99.8%** |
| models at 95%+ | 132 | 801 | **860** |
| models under 50% | 661 | **1** | 1 |
| models with playable animation | 12 | **202** | 218 |
| faces dropped past the array | — | 4,902 | **0** |
| mean per-model normal-agreement angle | — | 3.487° | **0.269°** |

`p_big_kuppa` went from **3 of 3,401** vertices to 99.9%.

⚠️ **D224 got the idea right and the arithmetic wrong.** Rebasing per shape is
what took coverage to 100%; *how far to advance* stayed wrong for another day and
is D240 below.

### The draw code said so and it was read past

`GXSetArray` is handed `add r16, r4, r0` — a position array **plus a per-shape
offset off the stack** (D207). That single `add` is why the index stream never
exceeds 22 while the array holds 324 points. It was in the disassembly for two
sessions.

### ⛔ The bases were counted, and that was wrong — the file states them

D224's `_rebase` found groups where `Face.first` restarts at zero, then advanced
the position base by the number of **distinct** indices each group used. Both
halves of that are wrong (D240):

- a block is as long as its **largest index plus one**, not as long as the
  indices used — the two differ on any shape that skips a point;
- **consecutive shapes can share one block**, so the base must not advance at
  all between them.

It cost **4,902 of the disc's 67,280 faces**, dropped for indices past the end of
the position array, and left `e_lui_robo` at 90° to its own normals.

### ✅ How `_rebase` does it now

`bleck/formats/modelrebase.py` reads two tables the draw code reads:

| what | where | fields |
|---|---|---|
| **group records** | the word at `0x14C`, 168 bytes each, running to `table[0]` | `char name[0x40]`; `(base, count)` for positions `0x40`, normals `0x48`, colours `0x50`, eight UV channels `0x58`…`0x94`; first shape `0x98`; shape count `0x9C` |
| **shape records** | slot 19, 108 bytes each | layer count `0x00`; eight layer indices `0x10`…`0x2C`; first face `0x38`; face count `0x3C`; corner offsets for the position `0x40`, normal `0x44` and colour `0x48` index streams; eight UV corner offsets `0x4C`…`0x68` |

- the **face list is split by the shape records**, not by `first` restarting at
  zero. The two disagree on **51 models** — a shape whose first face does not
  start at corner zero was merged into the one before it;
- the **position base** is its group's `0x40`, shared by every shape the group
  owns;
- the **UV base** is its group's `0x58`, and the UV *corner* offset is the shape
  record's `0x4C` — **a different word from the position corner offset**, which
  only advances for shapes that carry coordinates.

✅ **The invariant that says this was read right: the group slices tile the
position array exactly**, first base 0 and last `base + count` equal to the
array's length. It holds on **863 of the 864 readable models**, and `_bases()`
checks it before using the table — a model that fails falls back to the counting
reading rather than indexing into the wrong points.

⛔ **Zero faces now rebase past the end**, on any model. Anything above zero
means the group table stopped being read.

### ⛔ Why the earlier refutation was wrong, and what instrument caught it

D214 tested a cumulative base by **shuffling the group bases** and comparing
**planarity** — real 53.3% against shuffled 49.8% — and concluded no signal.

**The control was sound; the instrument was not.** A model's vertices are locally
clustered, so most quads come out planar however they are grouped. Planarity
cannot see this.

✅ **UV coherence can.** A face's three corners should land close together on the
texture, and a wrong base scatters them (D224):

| bases | median UV triangle area | coverage | out-of-range |
|---|---|---|---|
| **corner + position** | **0.0626** | **100.0%** | **22** |
| position only | 0.0768 | 100.0% | 172 |
| corner only | 0.1754 | 12.5% | 0 |
| neither (the old reading) | 0.1250 | 11.1% | 0 |
| shuffled control | 0.2294 | 100.0% | 1,250 |

⚠️ **Coverage alone would have accepted the shuffle** — it reaches 100% too. It
took two measures disagreeing to pick the answer.

⛔ One test was defending the bug: `test_coverage_is_low_and_says_so` asserted
the median stay below 50%, pinning 13.7% as though it were the format. It would
have passed forever while the reader was wrong, and **failed the fix**.

---

## Texture coordinates

✅ **UVs are indexed per corner, from slot 7** (D234), with their own per-shape
base — exactly like positions and normals.

⛔ **They have their own *corner* offset too, and it is not the position one**
(D240). The shape record holds the position corner offset at `+0x40` and the
first UV channel's at `+0x4C`, and the UV one only advances for shapes whose
`+0x00` is 1 — the flag the draw code tests before setting up texture
coordinates at all. `e_lui_robo_hige` reaches corner 368 with 136 UV corners
behind it. Reading the UV stream at the position offset gives **wrong but
in-range** indices, so nothing complains and the art comes out smeared;
`_shift_uvs()` re-packs the stream into position-corner order with `None` where a
shape carries none.

⛔ **"Is it textured" is a per-shape question.** 269 models mix textured and
untextured shapes, and asking `Mesh.is_textured` once for the whole mesh answered
no and threw the coordinates away from every shape in all of them. `gltf._weld`
asks `Mesh.textured(faces)` per primitive (D240).

⚠️ **It only reads as a stream against the 24-entry table.** With the 8-entry
shape record, slot 7's stop edge is the end of the file and the run does not look
like an index array at all — which is why it sat unread through D207, D215 and
D229.

The reading was found because `e_bara_tib_p` exported bare despite carrying a
12-image bank: it has **64 positions and 96 UVs**, and `is_textured` compared
those two counts. That silently dropped the texture on **26% of models**.

Result, verified by set difference rather than by comparing counts:
**639 → 770 textured, and zero losses.** Median UV triangle area, the D224
instrument reused unchanged:

| reading | UV area | position-paired | shuffled |
|---|---|---|---|
| slot 7, newly textured (131 models) | **0.0474** | 0.0668 | 0.1342 |
| slot 7, textured before (464) | **0.0312** | 0.0444 | 0.0604 |

The baseline reproduced D224's 0.0626 exactly, so it is the same ruler.

✅ **D240 sharpened it again**, by reading each shape's own UV corner offset and
asking per shape rather than per model:

| | D234 (whole mesh) | D240 (per shape) |
|---|---|---|
| median UV triangle area | 0.0474 | **0.0326** |
| shuffled control | 0.1342 | 0.1174 |
| triangles measured | 18,362 | **54,613** |
| fully textured | 770 models | 574 models, **4,720 shapes** |

⚠️ **The model count went down and that is the honest number.** Of the 770,
around 196 contained untextured shapes that were reading the previous shape's
coordinates; they are now reported as partly textured instead of wrongly whole.

⚠️ **A deliberate fallback.** 258 models carry a slot-7 stream shorter than their
corners; **175 of those hold exactly one UV per position** — `e_2D_manera` and
the paper sprites — and keep the older position pairing. Without it the net would
have been 639 → 595.

⛔ **The coherence instrument cannot judge that group.** A sprite quad
legitimately covers the whole image, so its UV area is 0.5 and the shuffled
control scores *better* (0.0469). Their behaviour is unchanged rather than newly
asserted, which is the honest position when the measure is blind.

✅ 79% of models keep every UV inside `[0,1]` and 74% have one pair per position;
values above 1 are texture **tiling**, not a misread (D215). After D234, 76.2% of
textured models keep every UV inside `[0,1]` (D234).

⛔ **`EFF_koopa`'s UV overflow is gone** (D240). D234 recorded it as the one
model whose rebased UV index ran past the array — 198 against 191, on 1 face of
67. Splitting its faces where `first` restarts at zero was the fault: the shape
records give it 7 spans and 91 faces, all seven textured. The overflow was the
split, not the model.

---

## Turning faces into triangles

⛔ **A fan is wrong for 14% of the disc's four-corner faces** (D223). **7,206 of
48,338**, across **182 models**. Fanning a non-convex polygon produces a bow-tie:
the diagonal leaves the shape and the texture stretches across the gap. It was
reported from the window — `e_genjin_b` rendered as a recognisable Cragnon with
"two bottom corners open up to a triangle in the middle".

⚠️ **D209 justified the fan with planarity, which was true and insufficient.**
Planar does not mean convex. The measurement was right and the inference from it
was not.

✅ **Ear clipping instead.** Repeatedly take a corner whose triangle turns the
same way as the polygon and encloses no other corner. Zero-area triangles are
dropped as they appear: `e_genjin_b` went **104 → 86** triangles, and across the
disc **117,010 triangles now contain no degenerate one at all**.

⚠️ There is a fallback to a fan when no ear can be found, for faces that are
self-crossing or non-planar. Silently dropping them would lose geometry.

### The planarity measurement, and both ways it was fooled

The instrument: a four-corner face of a real mesh is planar; shuffled indices are
not. It was wrong twice before it was right.

1. ⛔ **The first shape measured was flat.** `R_Arm_skin` spans z −1.0 to 2.8, so
   every quad was planar to 0.0000 — and so was the random control (D209). A
   control measured with the same broken ruler.
2. ⛔ **Degenerate faces are planar for free.** 16% of quads reference fewer than
   four distinct vertices; `e_big_nok` scored 100% planar using three vertices
   (D211). The control drew four *distinct* random points, so it had to clear a
   bar the real faces were walking under.

✅ Excluding degenerate faces, over 24,091 real quads on 125 three-dimensional
shapes: **72.4% planar against 15.2%** for the shuffled control (D211). A
five-fold gap. The test asserts the *gap*, not the rate.

---

## Animation

⛔ **It is per-vertex morphing, not skeletal** (D217). Two sessions went into
hunting a track→joint mapping that does not exist.

`animPoseMain` at `0x80045288` reads a clip through its `+0x24` section table,
copies the model's **positions** from slot 1 and **normals** from slot 3 into
working buffers, then at `0x800457e4` does this per key:

```
lbz   r5,0(r6)       ; byte 0 of the key
mulli r5,r5,12       ; x 12 -- a vec3 stride
psq_l f2,1(r6),1,4   ; dx, through GQR4: type s8, scale 0
psq_l f3,2(r6),1,4   ; dy
psq_l f4,3(r6),1,4   ; dz
lfsux f1,r8,r5       ; load WITH UPDATE: the pointer advances by index*12
fmadds f1,f0,f2,f1   ; dest.x += 0.0625 * delta
stfs  f1,0(r8)       ; ... and the same for .y at +4 and .z at +8
```

✅ **A key is `[u8 vertex stride, s8 dx, s8 dy, s8 dz]`.** `lfsux` *advances* the
destination pointer rather than indexing it, which is why byte 0 is 1 in 920 of
`mario_S_1`'s 1,152 keys — consecutive vertices.

Checks that confirm it (D217):

- All **1,152** keys of `mario_S_1` resolve to vertices inside its 324-position
  array. A wrong stride would run off the end almost immediately.
- Every `dz` is **zero**, on every key. Paper Mario is a flat character.

### ✅ A delta is a *sixteenth* of a unit, and a track is an *increment*

Both are read off the same function and both were wrong for as long as anything
exported (D252).

**`f0` is `0.0625`.** It is loaded once, outside every loop, at `0x80045798` —
`lfs f0,-30780(r2)` with `_SDA2_BASE_` at `0x805B7260`, so the float is the
`3d800000` at `0x805AFA24`. ⛔ The quantisation registers are *not* the scale:
`mtspr 914..917` write `0x00040004`, `0x00050005`, `0x00060006`, `0x00070007`,
so the load types are 4–7 and every load scale is **zero**.

⚠️ **Read raw, the median clip throws a vertex 2.42 times the model's own width**
and 1,336 of the disc's 1,728 clips throw one further than the model is wide.
At a sixteenth the median is **0.151** and 26 clips exceed one width. That
measurement is what "the animation is a smeared mess" looks like from here.

**A pose is every track up to it, added together.** The rebuild path walks
tracks `0..frame` into a buffer copied from the model's own positions:

```
800456fc: mulli r0,r26,44      ; frame * 44
80045700: lwz   r21,40(r27)    ; &track[0]
80045708: add   r20,r21,r0
8004570c: addi  r20,r20,44     ; &track[frame+1]
   ...   ; apply each track's keys into the buffer at 80(r29)
80045d20: addi  r21,r21,44
80045d28: blt   0x800457ac     ; while r21 < &track[frame+1]
```

✅ **The incremental path is the proof.** At `0x80045d34` the game applies only
tracks `cached+1..frame`, and it never re-copies the base positions — so it can
only agree with the rebuild path if a track *adds* to what is already there.
Two code paths that must produce the same picture.

An independent witness agrees: the clip's own box at `+0x44`. Over the 554
clips whose box already fits the rest pose to within 20%, the accumulated
reading **never** leaves that box; the per-track reading leaves it on 23, and a
control that accumulates the same tracks in reverse order leaves it on 70.

⚠️ **`mark` is a timeline position after all.** The seek at `0x80045560` scans
the track array for the last record whose field 0 is `<=` the current time, then
divides `(time − mark[frame]) / (mark[next] − mark[frame])` for the blend. The
D216 addendum called it a per-channel duration; under D217 there are no
channels, and this is simply the keyframe's time.

⚠️ **A zero-length track is still a keyframe** — 13,115 of the disc's 35,190 —
and holds the pose for another beat. 36% of keyframes are these.

### The clip table and the clip record

✅ **The last section of the front region is a fixed-stride clip table** (D203):
a 60-byte name field then a `u32` file offset at `+0x3C`.

```
mario_Z_1 -> 0x015F5C    mario_S_1 -> 0x015FFC    mario_W_1 -> 0x01BEE8
```

✅ Across all 869 readable models: **10,851 clips**, and **zero** whose pointer
falls outside its own file. That zero is what makes it a pointer rather than a
number that happens to be in range.

⛔ **Two wrong ways to read that block, both of which produced plausible output**
(D203): a loose name scan reads `mario_S_3` as `Tmario_S_3`, the tail of the
previous record being printable by chance; requiring a preceding NUL finds only
*one* clip, because the block is padded rather than NUL-separated. Only the
strided read is correct.

⚠️ **The joint table is *not* fixed-stride** — its first two records are `0x58`
apart and the next is `0x59` — so joints stay a scan, and `Model.joints` says in
its docstring that the count is not to be trusted (D203).

✅ **A clip record is accounted for byte for byte** (D205): the 94 record sizes
sum to exactly the 201,580-byte region, and `offset + size` lands on the next
clip's offset every time.

| field | at | |
|---|---|---|
| size | `+0x00` | the record's own byte length |
| counts | `+0x08`, `+0x0C`, `+0x14`, `+0x1C` | `(62, 1152, 14, 613)` for `mario_S_1` |
| section offsets | `+0x24` | seven, **relative to the record** |
| bounding box | `+0x44` | the clip's, not the model's |

⚠️ **Sections 1, 2 and 4 are the counted ones**, dividing by one of the record's
own counts 94, 88 and 91 times out of 94 with no exceptions. ⛔ The first version
of that claim said *every* section divides and is wrong: section 0 is a fixed 12
bytes, and sections 5 and 6 are padded (D205). The number that made it look right
was a pre-check requiring only two sections per record to divide, which says
almost nothing.

Track records are **44 bytes** with two cumulative `(first, count)` pairs — one
into the keys, summing to exactly 1,152, and one into section 6, summing to
exactly 613 (D216).

### 🔶 Key times are frames, divided by 60

Decoded key times are whole numbers running to 280 (`mario_S_1`). glTF defines a
sampler's input as **seconds**, so writing them raw plays a 4.7-second clip over
4 minutes 40 in every viewer. `effdata` already converts effect frames at 60 Hz
(D219), so `FRAME_RATE = 60.0` in `bleck/cli/commands/model.py` is **the same
inference applied to a second table — not a separate measurement**, and is marked
🔶 for that reason (D235). The manifest carries both `frames` and `seconds` per
clip, so the raw number is never lost.

### ⛔ `curves()` is gone, and it was never in the animation path

D216 read a key as `[time step, s16 delta, zero]` and accumulated it, scoring
0.0112 roughness against a 0.155 shuffled control — a fourteen-fold separation.
D217 shows what that was actually detecting: **adjacent bytes are small
correlated deltas**, which is equally true of two independent s8 axes.

⚠️ **A fourteen-fold separation from a control is not proof of the
*interpretation*, only that structure exists.** The game's own code settled which
structure it is.

Once the key layout is `[stride, dx, dy, dz]`, what that `s16` held is not
merely unproven — it is **`dx` in the high byte and `dy` in the low byte of one
number**, which is nothing. `modelanim.curves()` shipped that reading for two
months and `models.json` published `curves`, `keys` and `span` per clip from
it. Nothing read those numbers; nothing could have used them if it had.
Removed in D252, along with the three manifest columns.

⛔ **What a curve drives was never bound.** No field in the 44-byte track record
ranges over anything like the 176 joint names: fields 3 and 4 are always zero, 5
is 2 or 14, 6 is 0 or 2, 7 and 8 are 0 or 1 (D216 addendum). That question is
moot for rendering, since the animation is not skeletal.

⛔ **The D216 addendum's `mark` is superseded.** It called field 0 a per-channel
duration that the tracks are sorted by. There are no channels, and the seek at
`0x80045560` uses the field as a **time**: it scans for the last track whose
field 0 is at or before the clock, then interpolates on the gap to the next
(D252).

---

## What the exporter does with all this

`bleck model export` writes glTF 2.0 in the single-file `.glb` container.

⚠️ **Chosen because it can be checked by someone other than us** (D215). A `.glb`
opens in Blender, Windows 3D Viewer and any browser, so a claim about the geometry
stops depending on `dimentio` — which runs on a machine that cannot capture its
own screen (D213). ⛔ Wavefront OBJ was first and cannot carry animation at all;
FBX can and is proprietary, binary, and has no maintainable open writer. glTF is
JSON plus one blob, so `gltf.py` is stdlib-only and adds no runtime dependency.

✅ **One primitive per shape** (D237), not one merged mesh:

| model | before | after |
|---|---|---|
| `e_lui_robo` | 1 primitive, 3,130 tris | **91 primitives**, 3,130 tris |
| `e_2D_manera6` | 1 primitive, 86 tris | **31 primitives**, 86 tris |
| `p_wii_mario` | 1 primitive, 143 tris | **90 primitives**, 143 tris |

The triangle counts are the point: the split moves geometry between primitives
and creates none.

⛔ **One node per shape was rejected.** glTF puts morph targets on the
*primitive* and weights on the *mesh*, so primitives of one mesh share a single
`weights` array and an animation stays one sampler and one channel. A node each
costs a channel, a sampler and a full weight array per node — and the weight
array is already `keys × targets`.

⚠️ **`Mesh.shapes` and `Mesh.groups` are different numbers and both are kept.**
`shapes` counts the groups the file describes; `groups` holds the spans that
survived the rebase-past-the-end filter. `e_lui_robo` is 92 and 91.

⚠️ **The mistake that nearly shipped: 23,434 accessors.** Every primitive must
carry a target for every pose, so writing a fresh zero-filled target for the
untouched ones gave `p_wii_mario` — a 335-vertex mesh — a 2.9 MB JSON chunk.
Fixed by sharing one run of zeros and one do-nothing accessor per primitive:
23,434 → **979** accessors, 3.33 MB → **961 KB** (D237).

✅ **Morph targets are sparse where sparse is smaller** (D238), per target, via
`sparse_pays(vertices, moved)`. ⛔ Writing *every* target sparse was built,
measured and rejected: 120.8 MB against dense's 107.2 MB, because after the
per-shape split **68% of touched primitive-poses move every vertex the primitive
has** (mean fill 0.811). A sparse accessor costs ~100 bytes more of JSON than a
dense one and saves only on what it leaves out.

⛔ **A count-0 sparse accessor is not legal** — `accessor.sparse.schema.json`
carries `"minimum": 1` on `count`. A pose that misses a primitive is written as
an accessor with **no `bufferView` and no `sparse`**, which the specification
defines as zeros and which occupies no bytes at all.

The budget (`SPARSE = 2,048 targets / 12 MiB`, `DENSE = 256 / 2 MiB`) binds on
the **weight block**, not the deltas: every keyframe carries a weight for every
target in the file, so it is `keys × targets × 4` bytes — 8.6 MB of `p_luigi`'s
10.65 MB (D238). 11 MiB already drops no clip; 12 is 11 plus room for the cost
model's worst-case error.

⚠️ **`keys` and `targets` are not the same number** (D252). A hold keyframe
repeats the target before it rather than adding one, and 36% of the disc's
35,180 keyframes are holds — so a file carries 22,485 targets over 35,180 keys.
Writing a target per keyframe instead dropped 70 clips and cost 39 MB.

| | D237 | D238 | now | `--dense-morphs` |
|---|---|---|---|---|
| clips written / dropped | 2,256 / 823 | 3,079 / 0 | **3,079 / 0** | 2,279 / 800 |
| morph targets | 14,469 | 22,073 | **22,485** | 14,861 |
| `work/export/models` | 74.5 MB | 123.4 MB | **137 MB** | 76.4 MB |

⛔ **"3,079 / 0" is against the wrong denominator, and this row has been read as
full coverage** (D288). The files declare **10,851** clips — the number this
document records above — so 7,772 are neither written nor counted as dropped,
because a clip with no keyed track produces no pose to write. Of the 3,079 that
are written, **673 across 67 models hold a single pose at constant morph weight
and cannot move**; only 2,406 animate. ✅ The held ones are *correct* — three of
nine live poses in the running game do not change one word across eight seconds,
and every one of those is a model exported with zero animations (D288). What is
wrong is that `animations_dropped: 0` cannot tell a clip that plays from one
that cannot.

Geometry alone (`--no-animation`) is **20.6 MB** for all 864.

### How a texture reference is written

A shape's layers become one glTF material each. The base layer is the
`baseColorTexture`; its wrap mode is a real `samplers` entry (one per distinct
pair, shared) and its UV transform a `KHR_texture_transform` on the texture
reference, declared in `extensionsUsed` and never in `extensionsRequired`
(D248).

⛔ **The second layer has no core glTF slot.** It multiplies the base's colour
*and* alpha by its own alpha, which `occlusionTexture` cannot express and
`emissiveTexture` inverts. It is written as a full `textureInfo` at
`material.extras.spmMaskTexture`: Blender ignores it and draws layer 0,
`dimentio` reads it and multiplies. ⚠️ The image is a real `textures` entry, so
it stays reachable and D245's unreferenced-image check still holds.

⚠️ **Materials are deduplicated on the whole reference, not on the image.** Two
shapes can name one picture and clamp it differently.

✅ **The vertex colour rides as `COLOR_0`** — VEC4 of `UNSIGNED_BYTE` with
`normalized: true`, per primitive (D251). glTF multiplies it into the base
colour, which is `GX_MODULATE` exactly, so this needs no extension and no
`extras`. **4,609 primitives across 336 models carry one**, tinting 146,493
vertices for **0.56 MiB** of payload across the whole corpus.

🔶 **Four models are the exception**: `e_card_fre3`, `e_zun_tail`, `n_gid_tyou`
and `OFF_house_02` store black in *every* entry, which applied literally draws
them as silhouettes. They are written untinted, on the argument that a model
multiplied to nothing everywhere cannot be right — not extended to a black
shape inside a coloured model, which is ordinary art.

⚠️ **Omitted where every vertex is opaque white** — the specification already
means a multiply by 1, and 524 models are entirely white. ⚠️ **The weld key
gained the colour index**: two corners at one point with different tints are
two glTF vertices, and welding them would smooth a hard colour edge away.

✅ **Structurally validated, since nobody here can open a `.glb`.** All 864 files
re-parsed: header length equals file length, both chunks 4-byte aligned and
summing to the file, every buffer view inside the buffer, every accessor inside
its view, every `sparse.count` between 1 and the accessor's count. **0 failures**
(D238).

---

## Open questions

### ✅ Shape → texture binding — SOLVED

⛔ **This was the longest-open question here and is not one any more** (D243).
It is read from the file, through **two indirections** — which is why the three
candidates below all failed: each tried to go straight from a shape to an image.

```
shape record +0x00   how many texture layers (0, 1 or 2)
shape record +0x10   eight layer indices, -1 where unused
      -> slot 17     8-byte layer record, +0x00 a material index
      -> slot 18     64-byte material record, +0x04 the bank image index
```

⚠️ **The layer list is stored backwards.** The draw loop reads
`indices[count - i - 1]` and binds it to `GX_TEXMAP` *i*, so the last stored
index is map 0. `modelmat.Binding.layers` is already in map order.

⚠️ **`+0x00` is a count, not a flag.** Reading it as a boolean called the disc's
40 two-layer shapes untextured, which also cost them their UV corner offset.

✅ **Which bank the index lands in is stated at `0x44`** (D245), not derived from
the filename. **69 models name a bank other than their own name and 52 have no
same-named file at all** — `e_bari_beam` draws from `e__bari_beam-` with a
doubled underscore, `e_burosu_b` from `e_burosu_h-`, and `e_kmoon_g`/`_w`/`_b`
share one 201-image bank. All 52 exported bare whatever the binding said.
⚠️ **`NAME_AT = 0x44` is mislabelled in `model.py`**: it is the *bank's* name.
The model's own is `OWN_NAME_AT = 0x04`, and the two agree on 795 of 864, which
is why it read as a name for as long as it did. 31 models name a bank the disc
does not carry at all and fall back to the old guess.

✅ **Validated against the Brobot rips** (D236), two independent ways, each with
a shuffled control: **284 of 286** matched shapes pick an image of exactly the
reference's dimensions (controls 13.6% / 24.4% / 31.2%), and **61 of 61**
confident content matches of the rip's own images agree (controls 38.4% /
56.5%). 42 of 46 shapes this reading calls untextured get a flat placeholder in
the rip; **0 of 286** textured ones do. ⚠️ The first run of the dimension test
scored 1 of 24, because DDS stores `dwHeight` before `dwWidth` and the reader
had them the other way round — **without the control that would have read as a
refutation**.

✅ **Each shape still has its own image** (D229). `e_2D_manera6` is a paper
sprite built from 31 flat quads, and all 31 groups span the full `[0,1]` UV
square — so a shape is not a *region* of an atlas. That observation was right;
only the conclusion drawn from it, that the binding could not be found, was
wrong.

| candidate | how it died |
|---|---|
| ⛔ shape *i* uses texture *i* | quad aspect against texture aspect: 30–31% within 15%, against 21–24% shuffled (D229, D229 addendum) |
| ⛔ a material index in the face record | word0 and word1 high halfwords are **0** in every face of every model checked (D229) |
| ⛔ section slot 17 read as a per-shape array | 38 entries with a maximum of 31 against 32 bank images looked right; scored **23%**, *below* the 24% shuffled control (D229 addendum). Slot 17 *is* in the chain — one hop further along |

**What ships:** 823 of 864 models export textured with 6,892 embedded images,
one glTF material per distinct texture reference any shape makes — image, wrap
mode, UV transform and mask together (D247, D248). The 41 that stay bare name no
image at all, which the file states. ⚠️ D243 first reported 781 and 6,647; 10
of those 781 embedded art no primitive referenced, and 52 models were reading
the wrong texture bank (D245). ⛔ `--guess-textures` and the manifest's
`texture_guessed` are deleted with the guesswork they described.

⚠️ **The per-shape split (D237) was this binding's prerequisite, and the split
was also hiding a bug:** `gltf._primitive` asked `mesh.is_textured` for the
whole mesh, so the 269 models that mix textured and bare shapes wrote no UVs at
all (D243).

### ✅ What the two layers of a two-layer shape do — SOLVED

⛔ **It is not a second colour.** Shape record `+0x08` selects a TEV program from
a 13-entry table at `0x80409188`, and every two-layer shape on the disc — all 40
— picks **mode 2**, which multiplies the base by the second layer's **alpha**
(D247):

```
stage 0   prev = tex0                      (colour and alpha)
stage 1   prev = tex1.a * prev             <- the mask; tex1.rgb is never read
stage 2   prev = ras * prev
```

Mode 0, which every other shape picks, is a single `GX_MODULATE` stage. ⚠️
**Mode 1 is a real decal blend and nothing on the disc uses it**, so reading the
modes in order and stopping at the first plausible one gets this backwards.

⚠️ **Both layers sample UV channel 0.** Shape record `+0x30 + i` is a *signed*
per-layer channel index, read in the same reverse order as the layer list, and
it is 0 everywhere; slots 8–14 are empty on all 870 models. The two layers
differ only in their slot-16 matrices, so a second UV set is not needed and is
not exported.

### Wrap mode — slot 17 `+0x04`

✅ Bits 0 and 1 choose CLAMP (0) or REPEAT (1) for S and T; bits 2 and 3
override either with MIRROR (2). A **negative** word means "keep the image's own
`GXInitTexObj` defaults", which nothing on the disc asks for (D247).

| value | S | T | layers |
|---|---|---|---|
| 0 | CLAMP | CLAMP | 6,719 |
| 1 | REPEAT | CLAMP | 22 |
| 2 | CLAMP | REPEAT | 19 |
| 3 | REPEAT | REPEAT | 539 |
| 12 | MIRROR | MIRROR | 1 |

⛔ **The exporter assumed REPEAT and was wrong about 6,760 of 7,300 layers.**
D215's "~21% of models have coordinates outside `[0,1]`, so it is tiling" was
half right: most of it is a clamp. 672 models state something other than
REPEAT/REPEAT and **32 of them render differently** for it; the rest keep every
coordinate inside `[0,1]`, where all three modes agree (D248).

### ✅ Where the colour comes from — SOLVED, and it is not the textures

⛔ **The hue is mostly not in the images at all** (D251). A census of every TPL
bank under `files/a` — **815 banks, 12,736 images** — is:

| format | images |
|---|---|
| CMPR | **12,678** |
| IA8 | 20 |
| I4 | 13 |
| IA4 | 12 |
| RGB5A3 | 8 |
| I8 | 3 |
| RGB565 | 1 |
| RGBA32 | 1 |

**Zero paletted images**, and zero image-table entries carrying a palette
pointer. So the obvious explanation for a flat, structure-preserving grey — a CI
image decoded without its TLUT — is ruled out: `tpl.read` **refuses** an unknown
format rather than skipping it, so a paletted image on this disc would raise.

The colour is in **slot 5**, per vertex; see [Slots 5 and
6](#slots-5-and-6--the-vertex-colour-that-multiplies-the-texture). ⚠️ **The
reading was derived from the draw code and only *scored* against a third-party
rip afterwards** — mean distance to the nearest same-size rip image is 47.8
read, 87.8 for the white the old export wrote, and 67.7 for a shuffled control
whose best of 50 draws is 59.8. Nothing was fitted to the rip, and D243's
content matcher could not have found this in the first place: it is z-scored, so
a grey copy of a coloured image still scores +0.996 against it.

### ✅ Which Maya shape name goes with which primitive — SOLVED

⛔ **This was an open question and is not one any more** (D240). The group record
carries the name *and* the run of shapes it owns, so `Shape.name` is read rather
than guessed: `e_lui_robo`'s 92 spans come out as `marioShape`, `wallShape`,
`agoShape`, `L_eye|eye|eyeShape` and so on. D237's `shape <index>` labelling and
D236's "nothing binds one to the other" are both superseded.

⚠️ The shape-name counts in the log disagree and are counting different things:
29 names for Mario (D202), 88 (D211), 90 face groups (D237). The regex improved
between the first two; the third is groups, not names.

### ✅ Effect part → image binding — solved, after six refutations

Not this format, but the same shape of problem, and it is **the worked example
for the section above**: six candidates died before the answer turned out not to
be a field at all. Solved in D258 — the image is five sections past the part,
`part → node → draw → subdraw → material → texture`. The refuted list is kept
because *why each one died* is the reusable part.

| candidate | how it died |
|---|---|
| ⛔ `Part.second` | it is a **duration in frames** — 385 of 704 parts are exactly 1 mod 60 (D210) |
| ⛔ `Part.first` | a **running index**: an effect's parts carry *consecutive* values, and 14 of 704 exceed 218 (D210) |
| ⛔ the `+0x28` header word | it is section 10's offset, not a texture count (D210) |
| ⛔ three field offsets tried in D19x | a scan of every section at nine plausible strides found **no** field in 0..218 with enough distinct entries (D210) |

✅ **How it ended** (D258). D218's lead was half right and half wrong, and both
halves are instructive. Right: `Part.first` is a signed index with `0xFFFF` as
its null, into a second array of 20-byte records — **section 9**, 3,739 scene
nodes. ⛔ Wrong: those five fields do not drive drawing. `0x8005f1a8` is a
*transform evaluator*, named by its calls to `PSMTXTrans` and `PSMTXScale`, and
the fields are a sibling, a child, matrix and vector references, an alpha and a
billboard flag. ⛔ Also wrong: section 7 is **2,960 records of 6**, not 888 of
20 — the code multiplies by 6, which settles it without any counting.

⚠️ **The lesson for the table above**: a lead can name the right array and still
mislabel every field in it. The size arithmetic that looked confirmatory
(17,760 = 888 × 20) was a coincidence, and reading the multiply in the code beat
dividing the section size.

### 🔶 The 60 Hz clip rate

See above. It is an inference from `effdata`'s frame counts, not a measurement of
the model clip table. Nothing has timed a clip against the running game.

### 🔶 Slots 20–23

✅ **Slots 5 and 6 are decoded and exported** (D251) — see above; only 20–23
are left. Slots 16, 17, 18 and 19 are decoded too (D240, D243, D247), as are
the shape record's `+0x08` material mode and its `+0x30`…`+0x37` UV-channel
bytes.

What remains inside the decoded ones: the frame-offset byte at slot 16 `+0x00`
steps a texture animation by walking consecutive material records, and a static
export takes frame 0; material record `+0x08` is a mode the draw code compares
against 1, 2 and 10 and is only partly read; and the `+0x04 < 0` branch of the
wrap flag is unexercised on this disc.

### ✅ Group record `+0xA4` is a cull mode — 🔶 `+0xA0`

`+0xA4` indexes the table at `0x80407D40` — `[GX_CULL_FRONT, GX_CULL_BACK,
GX_CULL_ALL, GX_CULL_NONE]` — and the result goes to `GXSetCullMode`. It is 3 on
every group, so the whole disc draws double-sided (D247).

`+0xA0` is still undecoded: 0 except on `e_lui_robo`'s `glassShape`, where it is
3. A blend or render-pass mode is the obvious guess and is untested (D240).

### 🔶 `OFF_hei_01b` — the one model whose group table does not read

Its `0x14C`-to-`table[0]` span is 520 bytes, not a multiple of 168. It falls back
to the counting reading. One model of 864, and nothing else about it is unusual
(D240).

---

## Where the code and the log disagree

⚠️ **Found while writing this page, and left in place** — fixing docstrings is a
code change and this is a doc task. Each is a real contradiction between a
docstring and a later decision-log entry.

**Closed since this table was written:**

- ✅ The coverage claim in `modelmesh.py`'s module, `Mesh` and `Mesh.coverage`
  docstrings, the same claim in `bleck/cli/commands/model.py`, and
  `Mesh.triangles()` documenting a fan where `_cut` ear-clips — all fixed (D240).
- ✅ `Curve.mark`'s "a **position on the timeline** rather than a duration" — the
  seek at `0x80045560` uses field 0 as a key time, so the docstring was right and
  D216's addendum was wrong. **The type is gone with `curves()`** (D252), so the
  row is deleted rather than resolved.
- ✅ `model.py`'s `NAME_AT` — D245 found it holds the *bank's* name, not the
  model's, and the constant now carries that warning beside `OWN_NAME_AT = 0x04`.
  The name itself is unchanged, because `is_model` and `Model.name` both read it.

**Still standing.** Each is a real contradiction between a docstring and a later
decision-log entry; fixing them is a code change and this is a doc page.

| file | says | but |
|---|---|---|
| `model.py` module docstring table | "⛔ vertices, indices, weights — **not decoded**" and "⛔ animation keyframes — not decoded" | D207/D209/D224 decode the geometry, D216/D217/D252 the keyframes, and D251 the vertex colours. `Model.has_geometry` and `Model.can_animate` are still hard `False` |
| `model.py` module docstring | "bounding box — read, and sane — **Mario is 58.7 units tall**" | 58.7 is Mario's **max Y**; his height is 73.4 (D202, D212), since min Y is −14.68 |
| `model.py` / D235 | `Model` reads **94** clips for Mario (D203, D216) | D235 says **95** (`94 of p_wii_mario's 95 were not written`). Nothing has re-measured it |
| `Clip` docstring | "the pointer is real and checked; **what it points at is not decoded**, so nothing here can play one" | `modelanim.morphs()` decodes exactly that, and the whole disc's 3,079 clips export as glTF animations (D238, D252) |

⚠️ **`Model.has_geometry` and `Model.can_animate` are defensible as written** —
the *container* holds neither, and both come from `mesh()` and `morphs()`
instead — but a reader who trusts the docstring will conclude the format is
undecoded, which it is not.

---

## What a human has actually looked at

⚠️ Everything on this page is measured, but **only these were confirmed by a
person with eyes on the artifact**:

| | |
|---|---|
| ✅ `e_3D_manera_ruby` "renders correctly and looks like a ruby" | D215 — the only model at 100% coverage at the time |
| ✅ `MOBJ_broken_heart` rendered its texture in Blender | D215 addendum — mesh, UVs, embedded PNG and material |
| ⛔ `p_wii_mario` "all stretched out and weird looking" | D215, at 6.5% coverage — what a fragment looks like |
| ⛔ `e_genjin_b` bow-ties | D223 — the report that killed the fan |
| ⛔ `e_2D_manera6` "a bunch of small mimis on a big mimi" | D229 — the report that killed one-image-per-model |
| ✅ third-party rips of Brobot, as ground truth | D236 — max Y matches to the hundredth, 100.83 both ways |
| ✅ `p_bibi` static geometry, "model looks great" | after D240 |
| ⛔ `p_bibi` animation, "insane, not accurate" | D252 — deltas 16× too large and applied per track, not accumulated |
| 🔶 `p_wii_mario` "looks like it has a bunch of stuff in it" | D252 — 61 one-triangle planes stacked three-deep, plus props. Read exactly as the file states them; whether they *should* be exported is undecided |
| ⛔ `e_lui_robo` "almost entirely white", detail visible | D251 — the report that found the vertex colour |
| ✅ `e_lui_robo` after the fix: green cap, red thrusters, brown moustache, yellow eyes | D251, via `dimentio shot`. ⚠️ Not yet seen in Blender, which is the reader we did not write |
| ✅ `OFF_doorL` "a large kanji 表 filling the door" | D251 — reported as a suspected wrong image, and it is the art: the bank holds 裏 and 表, named `back.tga` and `front.tga` |

⚠️ **The oracle that closed D240 needed no human and no reference**: the angle
between a face's own normal and the mean of the normals its corners name. The
stored normals are not rebased, so they are an independent witness — ~0° when the
bases are right, ~90° when they are not, and 88° for a random control. That is
what let all 864 models be checked rather than the six a rip existed for.

⚠️ **`work/reference/` is a permanent instrument.** Reference bounds turn "the
verts look wrong" into a number, and the Brobot comparison took minutes where
four rounds of eyeballing had not converged. ⛔ The rips are third-party assets;
`work/` is git-ignored and stays that way.

## ✅ Slots 21 and 22 are a scene graph, and the export ignores it (D287)

Reported as "`e_card_nri_m` looks wrong, the textures seem to be not rotated
correctly". ⛔ **It is not the textures and not the rasteriser.** The model is
exported in its rest state with a whole node hierarchy left unapplied.

### The two tables

Parallel, one record per node, on **869 of 872** model files — and the two
counts **agree on every one of them**, which is what makes this structural
rather than a reading of one file.

| slot | stride | what a record holds |
|---|---|---|
| 21 | 96 bytes | 24 floats: translate `[0..2]`, scale `[3..5]`, rotation in degrees `[6..8]`, then a pivot repeated at `[12..14]` and `[15..17]` |
| 22 | 88 bytes | `char name[0x20]`, then at `+0x40` previous sibling, `+0x44` last child, `+0x48` the shape this node draws (`-1` for a node that only groups) |

`e_card_nri_m` — a Cursya — holds **31 nodes for 17 shapes**, and the links
rebuild a Maya DAG exactly:

```
|all
  noroi                      <- 呪い, the enemy's own name
    grp_body
      lct_body02a            <- rotate (11.69, -2.40, -1.04)
        body02a_mod          <- shape 16
        lct_body01a          <- rotate (44.09, -33.42, -42.93)
          body01a_mod        <- shape 15
          lct_body02b        ...and so on down the stack
    lct_tntcl_l              <- rotate (0, 0, 10.00)
      tntcl_l01_mod          <- shape 9, its own rotate (0, 0, 17.50)
    grp_eye_r                <- translate (-0.3, 0.3, 0), scale 1.10
```

⚠️ **`lct_` is a Maya locator and they nest down the stack**, so a stone's
rotation is the product of every locator above it. This is the same shape the
effect format's node chain has (D265, D266) and wants the same treatment.

### ✅ The stored positions are unposed — the control

`grp_eye_r` carries **scale 1.10** and `grp_eye_l` carries 1.00. If the
positions were already posed the right eye would be 1.1× the left. Measured:
`weye_r` is 5.0 × 5.0 and `weye_l` is 5.0 × 5.0, `eye_r` is 4.0 × 3.0 and
`eye_l` is 4.0 × 3.0. Identical. Nothing is baked in.

⚠️ **The rotations read as degrees authored by hand**, which is the other reason
to believe the field: the values across the corpus are 3.50, 7.50, 10.00, 17.50,
20.00, 168.75, **180.00** and **360.00**, not a spread of arbitrary floats.

### 🔶 What this does *not* yet establish

✅ **The draw code has been read** (D292), and it is the walker this section
asked for: **`0x80048c48`**, recursive, calling itself on node `+0x44` (last
child) and `+0x40` (previous sibling). It reads slot 22 at `lwz r6,424(r4)` with
`mulli r0,r4,88`, gates each node on slot 20, and reaches slot 21 through node
`+0x50` — which holds `index × 24`, and `slwi r0,r4,2` makes it `index × 96`,
this section's stride from the other direction.

🔶 **What it composes is partly read** (D294). The walker threads the *parent's
scale* down, not its whole matrix, and picks `0x80046c2c` when there is a parent
or `0x800466c4` when there is not. That builder skips each block that would be
the identity — the same structure as the sampler's `R · T · S` — and it reads
floats `[9..11]`, which this document listed as unknown.

⛔ **One thing blocks applying it: rotations are multiplied by 2.0.** The
constant is exactly 2.0, measured, so it is *not* degrees-to-radians (0.017453).
🔶 A sine table at half-degree resolution fits and is unverified. Until it is,
the rotation cannot be reproduced, and a subtly wrong rotation is the failure
that renders plausibly and hides — D265's lesson exactly.

✅ **The control to demand when it is applied**: `e_card_nri_m`'s `grp_eye_r`
carries scale 1.10 against `grp_eye_l`'s 1.00, so a posed right eye must come
out 1.1× the left. That is measurable off the emitted bytes and false today.

⚠️ Also unestablished: the rotation **order** (the effect evaluator is z, then y,
then x — D265), whether the rotation is taken **about the pivot** at `[12..14]`
(it is within 0.08 of `weye_r`'s centroid, on one sample), and what floats
`[9..11]` and `[18..23]` are.

⛔ **Do not apply this to the exporter on the strength of the above.** The
positive control to demand first is the draw code: find the routine that walks
slot 22's sibling/child links, and read what it does with slot 21.

---

## ✅ Slot 20 is per-node visibility, and the export honours it (D289)

Reported as "the animations look funky, there must be default ones hidden for
each model". There are: **one `u8` per node**, padded to a multiple of four,
`0` meaning the node is not drawn.

### Why it is a reading and not a coincidence

| | |
|---|---|
| models where the length is the node count padded to 4 | **869 of 870** |
| distinct byte values in the unpadded region | **`0` and `1`, nothing else** |
| nodes off, of 27,400 | **2,560** (9.3%) |
| **drawn shapes** off, of 17,597 | **2,427** (13.8%) |
| models hiding nothing at all | 523 of 869 |

⚠️ **The two counts differ because a node can draw nothing.** Slot 22's `+0x48`
is `-1` on a node that only groups, so 133 of the off nodes hide no shape.

### The control: what it names on `p_wii_mario`

68 of 176 nodes are off, and slot 22 names every one of them:

```
big_hammer  hammer  awate_foot     <- props
namida                             <- 涙, the tears
hed_kae  mouth  zentai             <- alternate parts
pPlane1..pPlane12, A10..A15,
B0..B5, C0..C15, D0..D5,
E0..E8, F0..F3, G0..G3             <- all 61 stacked planes
```

✅ **The 61 `pPlane*` nodes are the ones `handoff.md` recorded as unexplained**
— "61 one-triangle planes stacked at three spots", open since D252. They are not
unexplained; the file says not to draw them.

✅ `big_hammer` measures **50 units** against the body's 27, so drawn at rest it
fills the frame and the character is a few pixels below it. Hiding the 68 takes
`p_wii_mario` from 90 primitives to 22, and the sweep of `mario_S_1` becomes a
recognisable Paper Mario.

### ⚠️ The bounds have to follow, or the fix is invisible

The camera fits the model's bounds, and the bounds span every face including the
hidden ones. Framing the 50-unit hammer drew Mario at **0.9%** of the contact
sheet — worse than before the flag was read. `Mesh::visible_bounds` fits only
what is drawn, and the figure returns to **7.7%**.

⛔ **Only the *first* fit may use it.** A toggle that moved the bounds would read
as the model jumping rather than as a part disappearing.

### How it is exported

`extras.spmHidden` on the primitive, because glTF has no visibility field. Every
other reader ignores it: Blender draws the shape, `dimentio` leaves it out until
asked. `models.json` carries `hidden`, counted from the emitted bytes (D245).

⚠️ **The export marks 2,393 primitives on 319 models, not the file's 2,427 on
326**, and the whole difference is accounted for:

| | shapes | models |
|---|---|---|
| the file marks | 2,427 | 326 |
| in a model `mesh()` refuses, so never exported | −31 | −4 |
| naming a shape index past the mesh's own list | −3 | −3 |
| **written into a `.glb`** | **2,393** | **319** |

🔶 **The three are `e_pakflwr`, `_i` and `_p`** — one node each names shape **4**
where the mesh has four spans, `0..3`. The reader drops it and hides nothing on
those models, which is the right degradation and not an explanation. 3 of 863 is
small enough to leave open and large enough not to wave away.

⚠️ **The flag is matched on `Part.shape`, never on a primitive's position.**
`parts()` drops a shape whose faces are all degenerate, so the nth primitive is
not the nth shape — and a positional match would hide a different part of the
model, silently, in a file that still validates.

### ✅ The game copies it, one byte a node (D290)

⛔ **The "no code has been read" that stood here is discharged.**
`animPoseMain` copies four section arrays into its runtime buffer at
`0x80045714`–`0x80045780`, and the element sizes are in the instructions:

| source | count × size | destination |
|---|---|---|
| slot 3, normals | `mulli r5,r23,12` | `r29 + 0x58` |
| **slot 20** (`lwz r4,416(r28)`) | **`mr r5,r19` — no multiplier** | **`r29 + 0x60`** |
| slot 21 | `slwi r5,r22,2` | `r29 + 0x68` |
| slot 16 | `mulli r5,r18,24` | `r29 + 0x70` |

⚠️ **The siblings are the argument.** Every other copy carries an explicit size
— 12, 4, 24 — and slot 20's carries none. `0x150 + 20 × 4 = 0x1A0 = 416`.

✅ **The live array starts as the file's copy.** `scripts/dump_anim.py` follows
the pose's `+0x60`; on `p_wii_mario` the cleared bytes begin 3, 4, 5, 6, 23, 26,
27, 50, 52, 54 … — `zentai`, `big_hammer`, `hammer`, `awate_foot`, `hed_kae`,
`namida`, `mouth`, then the `pPlane` run.

### ⛔ What it still does not explain

⚠️ **The copy makes this a floor, not a ceiling.** The game owns the array
afterwards, so a shape the file shows may still be turned off at runtime — and
some are:

| what `p_wii_mario` still draws | shapes | grouped under |
|---|---|---|
| a purple flower on a green stem | `sp_ball`, `sp_bou`, `bou`, `l_ha`, `r_ha` | `Kinome` — 木の芽, a sprout |
| a large blue ring, Y 8 → 24 | `sp_naka`, `sp_waku` | `Sp_boushi` — a special hat |

⛔ **All of them are marked visible, and so is every parent group**, so subtree
propagation is not the missing rule. 🔶 What clears them is unfound; the live
array is the instrument, sampled on a map where Mario is actually drawn.

🔶 So a hidden shape is the file's *starting* statement, and the viewer keeps a
way to show it again.
