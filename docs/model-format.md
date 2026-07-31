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
| `bleck/formats/modelmesh.py` | the section table at `0x150` and its vertex arrays |
| `bleck/formats/modelrebase.py` | the group and shape records — which slice of those arrays each shape indexes |
| `bleck/formats/modelbase.py` | `Face`, `Shape`, the error type and the name field |
| `bleck/formats/modelanim.py` | the clip table, its curves and its morph poses |
| `bleck/formats/gltf.py` | the `.glb` writer |
| `scripts/modelscan.py` | `survey`, `header`, `offsets`, `at`, `strings`, `chain` |

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

`modelmesh.py` reads **24 entries** (`FULL_SECTIONS`) from `SHAPE_SECTIONS_AT =
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
| 5 | `0x164` | 336 entries of 4 bytes | 🔶 **vertex colours** — not floats, and paired with an identity index stream | 🔶 D208 addendum |
| 6 | `0x168` | 490 entries | 🔶 an index stream; D208's addendum reads the colour index here | 🔶 D207, D208 |
| 7 | `0x16C` | 153 entries, 23 distinct | **corner → UV index**, one per corner | ✅ D234 |
| 8..15 | `0x170`+ | one offset, repeated | **eight texture-coordinate channels**; slot 8 is channel 0 | ✅ D208 addendum |
| 16 | `0x190` | — | ⛔ **unread** | — |
| 17 | `0x194` | 8 bytes × layers | **layer records** — `+0x00` a material index, `+0x04` a wrap flag | ✅ D243 |
| 18 | `0x198` | 64 bytes × materials | **material records** — `+0x04` the bank image index, `+0x0C` the source TGA path | ✅ D243 |
| 19 | `0x19C` | 108 bytes × shapes | **shape records** — layer count and list, first face, face count, and the corner offset of each index stream | ✅ D240, D243 |
| 20..23 | `0x1A0`+ | — | ⛔ **unread** | — |

⚠️ **The draw code loads slots 8–15 as *index* streams, not channel data.**
`lwzx r0, r24, r5` picks `0x16C + channel × 4`, so `0x16C`…`0x188` are eight
per-channel UV index streams and `0x18C` is the coordinate array itself. `_uvs()`
reads from `table[8]` to the next *different* entry and lands on the right bytes
anyway, because an unused channel's start equals the array's start (D240).

⚠️ **Slots 5 and 6 are read by nothing in `bleck`.** They are listed because
D207 measured them, not because their meaning is settled — and D207's 490
entries at slot 6 do not divide the 336 colours at slot 5, so the pairing D208's
addendum proposes is not clean.

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
lfsux f1,r8,r5       ; load WITH UPDATE: the pointer advances by index*12
fmadds f1,f0,f2,f1   ; dest.x += weight * delta
stfs  f1,0(r8)       ; ... and the same for .y at +4 and .z at +8
```

✅ **A key is `[u8 vertex stride, s8 dx, s8 dy, s8 dz]`.** `lfsux` *advances* the
destination pointer rather than indexing it, which is why byte 0 is 1 in 920 of
`mario_S_1`'s 1,152 keys — consecutive vertices.

Checks that confirm it (D217):

- All **1,152** keys of `mario_S_1` resolve to vertices inside its 324-position
  array. A wrong stride would run off the end almost immediately.
- Every `dz` is **zero**, on every key. Paper Mario is a flat character.
- Deltas are small — max 9 units on a 73-unit-tall model.

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

### ⚠️ `curves()` is a superseded reading that still ships

D216 read a key as `[time step, s16 delta, zero]` and accumulated it, scoring
0.0112 roughness against a 0.155 shuffled control — a fourteen-fold separation.
D217 shows what that was actually detecting: **adjacent bytes are small
correlated deltas**, which is equally true of two independent s8 axes.

⚠️ **A fourteen-fold separation from a control is not proof of the
*interpretation*, only that structure exists.** The game's own code settled which
structure it is.

`modelanim.curves()` still implements the D216 reading and the manifest still
reports curve counts and value spans. Only `morphs()` — the D217 reading — is
written into a `.glb`. Nothing has re-measured whether `curves()` is meaningful
at all after D217.

⛔ **What a curve drives was never bound.** No field in the 44-byte track record
ranges over anything like the 176 joint names: fields 3 and 4 are always zero, 5
is 2 or 14, 6 is 0 or 2, 7 and 8 are 0 or 1 (D216 addendum). That question is now
moot for rendering, since the animation is not skeletal.

⚠️ **`mark` is a channel duration, not a timeline position.** D216 read field 0
of a track record as a position on a timeline because it ascends across a clip's
tracks. The addendum corrects it: it is each channel's own duration, and the
tracks are **sorted by it** — which is why the values ascend and why the last one
equals the clip length.

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
target in the file, so it is `targets² × 4` bytes — 8.6 MB of `p_luigi`'s 10.65 MB
(D238). 11 MiB already drops no clip; 12 is 11 plus room for the cost model's
worst-case error.

| | D237 | now | `--dense-morphs` |
|---|---|---|---|
| clips written / dropped | 2,256 / 823 | **3,079 / 0** | 2,279 / 800 |
| morph targets | 14,469 | 22,073 | 14,861 |
| `work/export/models` | 74.5 MB | **123.4 MB** | 76.4 MB |

Geometry alone (`--no-animation`) is **20.6 MB** for all 864.

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
index is map 0. `modelmat.Binding.images` is already in map order.

⚠️ **`+0x00` is a count, not a flag.** Reading it as a boolean called the disc's
40 two-layer shapes untextured, which also cost them their UV corner offset.

Validated against the Brobot rips (D236) two independent ways, each with a
shuffled control: **284 of 286** matched shapes pick an image of exactly the
reference's dimensions (controls 13.6% / 24.4% / 31.2%), and **61 of 61**
confident content matches of the rip's own images agree (controls 38.4% /
56.5%). 42 of 46 shapes we call untextured get a flat placeholder in the rip;
**0 of 286** textured ones do.

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

**What ships:** 781 of 864 models export textured with 6,647 embedded images,
one glTF material per image any shape reaches. The 83 that stay bare name no
image at all, which the file states. ⛔ `--guess-textures` and the manifest's
`texture_guessed` are deleted with the guesswork they described.

⚠️ **The per-shape split (D237) was this binding's prerequisite, and the split
was also hiding a bug:** `gltf._primitive` asked `mesh.is_textured` for the
whole mesh, so the 269 models that mix textured and bare shapes wrote no UVs at
all (D243).

### ✅ Which Maya shape name goes with which primitive — SOLVED

⛔ **This was an open question and is not one any more** (D240). The group record
carries the name *and* the run of shapes it owns, so `Shape.name` is read rather
than guessed: `e_lui_robo`'s 92 spans come out as `marioShape`, `wallShape`,
`agoShape`, `L_eye|eye|eyeShape` and so on. D237's `shape <index>` labelling and
D236's "nothing binds one to the other" are both superseded.

⚠️ The shape-name counts in the log disagree and are counting different things:
29 names for Mario (D202), 88 (D211), 90 face groups (D237). The regex improved
between the first two; the third is groups, not names.

### ⛔ Effect part → image binding — six candidates refuted

Not this format, but the same shape of problem and it is the other thing a viewer
cannot show. Recorded here because D210's refuted list is the model for the one
above.

| candidate | how it died |
|---|---|
| ⛔ `Part.second` | it is a **duration in frames** — 385 of 704 parts are exactly 1 mod 60 (D210) |
| ⛔ `Part.first` | a **running index**: an effect's parts carry *consecutive* values, and 14 of 704 exceed 218 (D210) |
| ⛔ the `+0x28` header word | it is section 10's offset, not a texture count (D210) |
| ⛔ three field offsets tried in D19x | a scan of every section at nine plausible strides found **no** field in 0..218 with enough distinct entries (D210) |

🔶 **The live lead** (D218): `Part.first` is a **signed** index, `0xFFFF` meaning
none, into a *second* array of 20-byte records, and the fields that drive drawing
live in **that** record at `+0x08`, `+0x0A`, `+0x0E`, `+0x0F`, `+0x12`. Which
`effdata.dat` section that array is has not been established; section 7 is 17,760
bytes = 888 records of 20, which is large enough and untested.

### 🔶 The 60 Hz clip rate

See above. It is an inference from `effdata`'s frame counts, not a measurement of
the model clip table. Nothing has timed a clip against the running game.

### 🔶 Slots 5, 6, 16 and 20–23

Vertex colours and their index stream are read by nobody, and the counts D207
measured do not pair cleanly. ✅ Slots 17, 18 and 19 are decoded (D240, D243).

Two fields inside the decoded ones are still open: the shape record's
`+0x30`…`+0x37`, one byte per layer and `0` on every model (a UV-channel
selector is the obvious reading, and nothing on the disc distinguishes it from a
constant), and slot 17's `+0x04`, which the draw code branches on to pick a
`GXTexWrapMode` — the exporter always writes `REPEAT` (D243).

### 🔶 Group record `+0xA0` and `+0xA4`

Undecoded. `0xA4` is 3 on every group measured; `0xA0` is 0 except on
`e_lui_robo`'s `glassShape`, where it is 3. A blend or render-pass mode is the
obvious guess and is untested (D240).

### 🔶 `OFF_hei_01b` — the one model whose group table does not read

Its `0x14C`-to-`table[0]` span is 520 bytes, not a multiple of 168. It falls back
to the counting reading. One model of 864, and nothing else about it is unusual
(D240).

---

## Where the code and the log disagree

⚠️ **Found while writing this page, and left in place** — fixing docstrings is a
code change and this is a doc task. Each is a real contradiction between a
docstring and a later decision-log entry.

✅ **The first three rows are fixed** (D240) — the coverage claim in
`modelmesh.py`'s module, `Mesh` and `Mesh.coverage` docstrings, the same claim in
`bleck/cli/commands/model.py`, and `Mesh.triangles()` documenting a fan where
`_cut` ear-clips. The rest stand.

| file | says | but |
|---|---|---|
| `Curve.mark` docstring | "Ascends across a clip's tracks, so it is a **position on the timeline** rather than a duration" | **D216's addendum reverses this**: it is each channel's own duration and the tracks are sorted by it |
| `model.py` module docstring table | "⛔ vertices, indices, weights — **not decoded**" and "⛔ animation keyframes — not decoded" | D207/D209/D224 decode the geometry and D216/D217 the keyframes; `Model.has_geometry` and `Model.can_animate` are still hard `False` |
| `model.py` module docstring | "bounding box — read, and sane — **Mario is 58.7 units tall**" | 58.7 is Mario's **max Y**; his height is 73.4 (D202, D212), since min Y is −14.68 |
| `model.py` / D235 | `Model` reads **94** clips for Mario (D203, D216) | D235 says **95** (`94 of p_wii_mario's 95 were not written`) |

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

⚠️ **The oracle that closed D240 needed no human and no reference**: the angle
between a face's own normal and the mean of the normals its corners name. The
stored normals are not rebased, so they are an independent witness — ~0° when the
bases are right, ~90° when they are not, and 88° for a random control. That is
what let all 864 models be checked rather than the six a rip existed for.

⚠️ **`work/reference/` is a permanent instrument.** Reference bounds turn "the
verts look wrong" into a number, and the Brobot comparison took minutes where
four rounds of eyeballing had not converged. ⛔ The rips are third-party assets;
`work/` is git-ignored and stays that way.
