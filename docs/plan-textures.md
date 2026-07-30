# Declarative texture edits

**Why this exists.** `tex-koopa` and `title-invert` cannot be shared. Their whole
content is a modified game texture, so a `.bleck` archive either omits it (and
the mod does nothing) or carries Nintendo's bytes (D158). Every other kind of
edit in `bleck` is a *declaration* rebuilt against the recipient's own disc;
textures are the last place where the rule in
[`vision.md`](vision.md) — *edits are declared as data and generated at build
time, never shipped as baked bytes* — is broken.

Fixing that is what this plan is for. It is not about making texture editing
nicer; it is about making texture mods **legal to share**.

---

## What the game actually uses

✅ Measured, not assumed: 898 TPL containers across the extracted disc, 9,403
images.

| format | images | share | kind |
|---|---|---|---|
| **CMPR** | 8,516 | **90.6%** | S3TC/DXT1 block compression |
| I4 | 304 | 3.2% | 4-bit intensity |
| RGB5A3 | 284 | 3.0% | direct colour |
| I8 | 199 | 2.1% | 8-bit intensity |
| IA4 | 57 | 0.6% | intensity + alpha |
| IA8 | 29 | 0.3% | intensity + alpha |
| RGBA32 | 10 | 0.1% | direct colour |
| RGB565 | 4 | <0.1% | direct colour |
| C4 / C8 / C14X2 | **0** | — | paletted |

⛔ **No paletted textures at all.** That removes palette decoding, palette
re-quantisation and the whole class of "editing one image changes another"
problems. Commonest sizes are 64×64, 32×32 and 24×24 — small.

⚠️ **CMPR being 90% is the single fact that shapes this work.** A naive
implementation decodes DXT1 to RGBA, edits, and re-compresses — which is lossy,
needs a good block encoder, and degrades a texture every time a mod is rebuilt.

---

## The trick that avoids a DXT1 encoder

A CMPR block is two `RGB565` endpoint colours followed by 2-bit per-pixel
indices into the four colours those endpoints imply. For a whole class of
operations, **the indices do not change** — only the endpoints do:

| operation | endpoint-domain? |
|---|---|
| invert | ✅ `c = 0xFFFF - c` per channel |
| brightness / contrast | ✅ scale both endpoints |
| tint / recolour | ✅ map both endpoints |
| greyscale | ✅ |
| replace with new artwork | ⛔ needs a real encoder |
| blur, resize, anything spatial | ⛔ |

🟢 So `invert` — the operation `tex-koopa` and `title-invert` actually perform —
is **lossless, exact, and needs no encoder at all**: rewrite four bytes per
block. The same applies to every other per-pixel colour map.

⚠️ This must be verified before it is believed. DXT1 has a special case: when
`c0 <= c1` the block is 3-colour + transparent rather than 4-colour, and
inverting the endpoints can **flip which case applies**, changing transparency.
The first thing to write is a test that round-trips every block form.

---

## Tiers, in the order they pay off

### Tier 1 — colour-map operations, all formats

`invert`, `brightness`, `tint`, `greyscale`. CMPR handled in the endpoint domain;
the seven direct formats decoded, mapped and re-encoded exactly (no compression
involved, so it is byte-lossless).

Covers **100% of the images measured** and both existing texture mods, with no
new dependency.

### Tier 2 — replace with the author's own artwork

`replace: art/koopa.png`. The PNG is the author's work, so it ships in the
`.bleck` happily — this is the case that makes texture *mods* rather than texture
*tweaks* shareable.

⚠️ Needs a PNG decoder (a dependency decision — Pillow is the obvious one and is
heavy) **and** a DXT1 encoder for the 90% case. A poor encoder will look worse
than the original, so quality is a real acceptance criterion, not a footnote.

### Tier 3 — spatial operations

Resize, crop, overlay. Only worth it once Tier 2's encoder exists.

---

## How it is declared

Following the table convention already used for enemies, coins and doors:

```csv
# tables/textures.csv
file,member,op,arg
files/lyt/title.bin.uk,arc/timg/koopa.tpl,invert,
files/lyt/title.bin.uk,arc/timg/mario.tpl,tint,#8800ff
```

`file` and `member` are the same disc-path-plus-archive-member pair
`bleck mod vendor` already understands, so the addressing is not new.

`bleck` reads the base texture at build time, applies the operation, and writes
the result into the overlay — exactly as placements already work. The mod ships
the CSV; the recipient's disc supplies the pixels.

---

## What "done" means

- [ ] `tex-koopa` and `title-invert` rewritten as declarations, with **no
      overlay files at all**
- [ ] Both produce byte-identical output to the current hand-vendored versions,
      or the difference is explained
- [ ] `bleck mod pack tex-koopa` completes with **no consent prompt**
- [ ] A round-tripped CMPR texture is byte-identical when the operation is
      identity

⚠️ The third is the real acceptance test. The prompt disappearing is the whole
point of the feature.
