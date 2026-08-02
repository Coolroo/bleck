---
name: decode-by-disassembly
description: Use when a binary format, struct field, or file layout resists pattern-matching — stop guessing at the bytes and disassemble the game code that reads them. Covers the scripts/dolscan.py workflow (strings/xref/dis/callers/calls), the xref-cannot-find-callers trap, and resolving small-data-base (r2/r13) loads.
---

# Decode by disassembly

**When a format will not yield, find the code that reads it and let the game
state its own layout.**

This is the highest-value method in this repo. Every attempt to fit a layout to
the bytes has either failed or produced a plausible wrong answer; every time the
draw code was disassembled instead, the answer arrived the same day and came
with field names.

## The scoreboard

| finding | what pattern-matching cost first | what the code said |
|---|---|---|
| character vertex format (**D207**) | four failed attempts at fitting the file | `GXSetVtxAttrFmt` at `0x8004854c`: BE f32 XYZ, stride 12, `u16`-indexed |
| model geometry / position base (**D240**) | four more; a per-group base *refuted* in D214 | `0x14C` is a table of **168-byte group records**, base at `+0x40` |
| shape → texture (**D243**) | D229 refuted three direct guesses and shipped 761 models bare | **two indirections**: shape `+0x10` → slot 17 → slot 18 → bank index |
| wrap mode (**D247**) | the exporter assumed REPEAT, wrong on 6,760 of 7,300 layers | slot 17 `+0x04`, bits 2/3, feeding `GXInitTexObj` |
| animation scale (**D252**) | shipped raw `s8` since D217; median pose 2.4× model width | `lfs f0,-30780(r2)` at `0x80045798` = **0.0625** |

D247 was the fourth time in one format. Reach for this **before** the third
statistical fit, not after.

## The workflow

```bash
uv run python scripts/dolscan.py strings setup_data     # 1. find a string
uv run python scripts/dolscan.py xref 0x80323BB0        # 2. who builds that address
uv run python scripts/dolscan.py dis  0x800297A0 40     # 3. read the code
uv run python scripts/dolscan.py callers 0x8028EA78     # 4. who calls that function
uv run python scripts/dolscan.py calls 0x40 0x800de9b8  # 5. who reads field +0x40, then calls
```

Capture to a file and read slices from it — a `dis` sweep is slow enough to
notice, and re-running to widen a filter is the standing mistake.

### ⛔ `xref` cannot find a caller

`xref` tracks how the game **builds an address** (`lis`/`addis`/`addi` pairs),
which is right for data and wrong for code. A `bl` encodes a *signed
displacement*, not an address, so `xref 0x8028EA78` (`GXSetVtxAttrFmt`) returns
**nothing** — and an empty list reads as "nobody calls it", which is plainly
false for a GX entry point in a shipping game (**D206**).

Use `dolscan.py callers <addr>`. It decoded every `bl` in the text range and
found **178 callers** of `GXSetVtxAttrFmt`, five inside the character-animation
range. Those five are what unblocked the model format.

⛔ Widening `xref` to cover branches was rejected: the two questions have
different failure modes, and folding them together keeps the empty result
silently plausible.

### Resolving a small-data-base load

Constants come in through r2 (`_SDA2_BASE_`) and r13 (`_SDA_BASE_`), so
`lfs f0,-30780(r2)` looks like nothing until the base is known.

- `_SDA2_BASE_` = **`0x805B7260`**, read off the register init at `0x8000630C`
  (D247).
- r13 = **`0x805B5F00`** (D218).

So `-30780(r2)` is `0x805B7260 - 0x783C` = `0x805AFA24`, whose word is
`3d800000` = **0.0625** — the animation delta scale (D252). One instruction
settled a question four statistical readings had been arguing about.

⚠️ **Check the quantisation registers too.** `psq_l` scales by a GQR field.
D252 had to confirm `mtspr 914..917` write `0x000?000?` with `LD_SCALE` zero
before the `0.0625` could be the whole story.

### ⚠️ objdump needs `-EB -M 750cl`

The default decode turns `ps_merge00` into VMX nonsense, so `dolscan.py dis`
shows garbage in the paired-single routines and a matrix cannot be read at all
(D247). Fall back to `powerpc-*-objdump -EB -M 750cl` for those.

## What makes a reading trustworthy

A disassembled layout still needs a check the *file* can fail. The ones that
have earned their keep:

- **A physical invariant.** Every normal triple is unit length — true on 864 of
  870 models, so `mesh()` refuses the other six rather than returning plausible
  nonsense (D207).
- **A tiling invariant.** The group slices tile the position array exactly:
  first base 0, each `base + count` equal to the next, the last ending at the
  array length. **863 of 864**; the one failure falls back rather than indexing
  into the wrong points (D240).
- **Counts that agree across sections.** Header counts vs section strides
  (8 / 64 / 108): **870 / 870**. Every slot-17 material index inside slot 18:
  **870 / 870** (D243).

## Traps this method has its own version of

- ⛔ **A constant stride can be aliasing.** 38 records at a stride of `0x268`
  looked like a shape array; the joint table's stride is `0x58`, and 7 × 0x58 =
  0x268 (D207). A constant stride is exactly what aliasing produces.
- ⛔ **Do not read the modes in order and take the first that fits.** Material
  mode 1 is a proper decal blend and would have been a plausible answer; the
  disc uses mode 2, which is a mask. **The corpus said which, not the
  disassembly** (D247).
- ⚠️ **A field the code branches on may still be constant on this disc.** Shape
  `+0x30` is a signed UV-channel selector and is 0 everywhere; slot 17's
  `+0x04 < 0` branch is never taken. Record them as read-but-unexercised, not as
  decoded behaviour.
- ⚠️ **A field's *name* can be wrong for years.** `NAME_AT = 0x44` holds the
  *bank's* name; the model's own name is at `0x04`. They agree on 795 of 864
  files, which is why it read as a name (D245).

Findings go in `docs/model-format.md` and `docs/function-behaviour.md`, with the
address they were read from.
