---
name: verify-the-emitted-artifact
description: Use when writing or trusting a test for anything this project exports — glTF, TPL, a disc image, a manifest. Tests that assert on what the writer was handed pass on an empty file; an export with zero materials passed 1,508 of them. Covers reading back the emitted bytes, independent readers, cut-the-known-good controls, and checking file mtimes.
---

# Verify the emitted artifact

**Test the bytes you shipped, not the writer's internals.**

An export of 864 models containing **zero materials, zero textures, zero images
passed 1,508 tests** (D245). Every pre-existing texture test asserted on what
the writer was *handed*, or on one field of the document it built. None followed
a primitive through to image bytes.

## The three failures this prevents

All from D245, all in one commit:

1. **The manifest described intent, not output.** `textured` was `bool(paints)`
   — what the writer was handed. Ten files were listed as textured while every
   primitive in them drew bare. Fixed by `gltf.painting(blob)`, which **parses
   the file just written** and counts primitives carrying a material. *A
   manifest derived from the emitted bytes cannot over-report.*
2. **Images embedded that nothing could reach.** `_paint` wrote a material per
   decoded image, then handed materials only to primitives with `TEXCOORD_0`.
   12 unreferenced images across the corpus — bytes a reader downloads, decodes
   and never draws. Now 0.
3. **A headline number that was never true.** D243's "781 of 864 textured"
   counted files *handed* an image; only **771** painted a primitive.

## How to check an artifact

### 1. Walk the chain a real reader walks

```
primitive.material -> materials[m].pbrMetallicRoughness.baseColorTexture
  -> textures[t].source -> images[i].bufferView -> PNG bytes
```

Recompute each PNG's chunk CRCs; do not merely check the magic. Across all 864
exports the walker reports **zero structural violations**.

### 2. Build a minimal known-good artifact and cut it N ways

⚠️ **The walker was controlled before it was believed.** A minimal textured
`.glb` — one triangle, one 2×2 PNG, one material — was hand-written and then cut
**twelve** ways:

material index out of range · no `baseColorTexture` · no `source` · no
`samplers` · no `mimeType` · no `TEXCOORD_0` · a `texCoord` slot the primitive
lacks · `byteStride` on an image's buffer view · corrupted PNG magic · a
truncated image view · an image nothing references.

**The intact file passed; all twelve cuts were caught.** One cut exposed a hole
in the checker itself — the truncated-image case raised `struct.error` instead
of reporting a fault, so it would have *crashed* on a real malformed file rather
than naming it. Found only because the control existed.

These live as parametrised controls in `tests/test_gltf_materials.py`.

### 3. Use a reader that has never seen this repo

`trimesh` 4.12.2 in a throwaway venv, decoding images through Pillow, gave the
verdict that settled D245:

| file | geometry | UV | images |
|---|---|---|---|
| hand-written control | 1 | 1 | 1 |
| the stale `e_lui_robo.glb` | 92 | **0** | **0** |
| the same model re-exported | 92 | 68 | **68 decoded** |

⚠️ **A fixture written by the test that reads it cannot detect a disagreement
between two programs** (D221). `dimentio` parsed only OBJ for a whole session
after `bleck` moved to glTF, and every mesh test passed, because each built its
own OBJ. **The suite needs one foot in the real output.**

⚠️ **A render by the program under test is not independent of it** (D253).
`dimentio shot` is a fast look, not a third-party reader.

The one cross-end check that exists here (D246): `dimentio`'s `paints().len()`
and its painted-shape count are asserted against `bleck`'s manifest `textures`
and `painted` for **all 864 models — 0 disagreements**. Those numbers came from
the other program.

### 4. ⚠️ Check the file's mtime before believing a bug report

D245 opens with a false alarm because the false alarm is the lesson. A person
opened `e_lui_robo.glb` and `p_wii_mario.glb` in Blender and reported **no
materials at all**. D243 had just claimed 781 of 864 textured. Both were true:
the `.glb` files were written at **14:25**, and D243 landed at **15:13**.

**The files predated the fix by 48 minutes.**

⛔ **Do not conclude "the writer is broken" from a file on disk without checking
when the file was written.** Nothing about the report was wrong; the artifact was
simply older than the code. When sending an artifact to a human — who costs a
day of round trip — re-export first and state the timestamp.

## Rules of thumb

- A test must not depend on **how** the export it reads was produced (D234
  addendum). Two real-export tests broke on `--guess-textures`, and neither was
  a code fault.
- Pin **invariants**, not counts, in an area still being decoded. The model
  geometry counts have been rewritten three times;
  `tests/test_model_geometry.py` asserts that the slices tile, that nothing
  falls off the end, and that the positive controls stay under 5°.
- If a manifest field can be computed two ways, compute it from the **output**.
- An artifact that is absent from the document is different from one that is
  broken: the stale `.glb` had **no `materials` key at all**, which is exactly
  what a viewer showing bare geometry looks like.
