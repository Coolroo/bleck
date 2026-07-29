---
title: The game accepts LZ77 that is not bit-exact
description: A re-compressed archive 0.25% larger than Nintendo's, with entirely different token boundaries, boots and renders — plus the overlapping-match trap in Nintendo's own streams
---

# The game accepts LZ77 that is not bit-exact

Every `map/*.bin` and `rel/*.bin` on the disc is a Nintendo LZ77 (type `0x10`)
stream. Anyone rebuilding one faces the same question: does the game care
whether your compressor reproduces Nintendo's exact output?

✅ **No.** A disc built with re-compressed archives boots and renders the
modified assets. The encoder used produces a stream **~0.25% larger** than
Nintendo's, with **entirely different token boundaries**, and the game accepts
it without complaint.

| encoder | `aa1_01` output | vs Nintendo |
|---|---|---|
| Nintendo (original) | 424,712 | — |
| greedy, overlap-aware | 425,773 | **+0.25%** |
| literals only (no matching) | 1,272,969 | +200% |

Confirmed visually: the title screen rendered with modified textures, through
the full chain — LZ77 decompress → U8 unpack → replace member → U8 repack →
LZ77 **re-compress** → disc rebuild → boot.

This retires a real worry. Chasing bit-exactness is optional polish, not a
prerequisite for a working tool.

## ⚠️ The trap: Nintendo's streams contain overlapping matches

Attempting bit-exactness failed, and paid for itself anyway by finding a bug
that a round-trip test cannot catch.

Token-diffing our stream against Nintendo's on `aa1_01`: at input offset 19 they
emit `(length 13, displacement 3)` where we emitted `(length 3, displacement 3)`.
Same displacement, shorter match. The cause: our match search only looked
*inside* already-emitted output, so it could not find **overlapping** matches —
ones that read bytes the copy itself is in the process of producing.

Two consequences for anyone writing this codec:

- A **decompressor** must copy byte-by-byte, not with a block move. Overlapping
  back-references occur in Nintendo's own data.
- A **compressor** that only searches the completed window leaves real
  compression on the table, silently and correctly.

⚠️ **Counter-intuitive:** fixing the overlap bug made the output slightly
*larger* (424,955 → 425,773) while halving runtime. That is not a regression —
greedy longest-match is not optimal parsing, and taking a longer match now can
force a worse parse later. The pre-fix encoder was accidentally better on this
one file. The principled answer is lazy matching, not reverting.

## The format, for completeness

4-byte header: the byte `0x10`, then a 24-bit little-endian **uncompressed**
size. Then blocks of one flag byte followed by 8 units, MSB first:

- clear bit → one literal byte;
- set bit → a back-reference in two big-endian bytes: 4-bit `(length - 3)` and
  12-bit `(displacement - 1)`.

✅ Verified by decompressing all five REL archives across the PAL and US discs
to *exactly* their declared sizes, with no trailing slop and no malformed
back-references — and the output is a valid Nintendo REL v3 in every case
(`sectionInfoOffset = 0x4C`, section tables parse cleanly).

✅ The U8 container layer above it **is** reproducible byte-exactly: a rewriter
round-trips the entire corpus of 383 archives with matching hashes. It is only
the compression that differs.

*(Sources: bleck decision log D10, D14, D16, D17, D25.)*
