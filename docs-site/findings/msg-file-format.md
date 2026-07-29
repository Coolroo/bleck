---
title: The message file format — files/msg/<lang>/*.txt
description: A flat run of NUL-terminated key/value pairs from byte 0, with no header, plus what the encoding is per language
---

# `files/msg/<lang>/*.txt` is a flat run of NUL-terminated pairs

Despite the `.txt` extension these are **binary** files. There is no header, no
index and no line structure. From byte 0 the file is:

```
key \0 value \0 key \0 value \0 …
```

and that is all of it. Trailing NUL padding appears at the end of the file.

## Evidence

The first 96 bytes of `files/msg/UK/global.txt` on a PAL rev 0 disc:

```
0000000   p  l  a  c  e  _  t  o  w  n \0  F  l  i  p  s
0000020   i  d  e \0  p  l  a  c  e  _  s  t  g  1 \0  L
0000040   i  n  e  l  a  n  d \0  p  l  a  c  e  _  s  t
0000060   g  2 \0  G  l  o  a  m     V  a  l  l  e  y \0
0000100   p  l  a  c  e  _  s  t  g  3 \0  T  h  e     B
0000120   i  t  l  a  n  d  s \0  p  l  a  c  e  _  s  t
```

So `place_town` → `Flipside`, `place_stg1` → `Lineland`, `place_stg2` →
`Gloam Valley`. ✅ Independently, all 538 `nameMsg` keys taken from
[`itemDataTable`](item-data-table.md) resolve against `files/msg/UK` with this
reading — a 538-for-538 hit rate on keys derived from a completely different
part of the disc.

## Languages and encoding

The PAL disc carries seven directories under `files/msg/`:

```
FR  GE  IT  JP  SP  UK  US
```

✅ **`JP` is Shift-JIS.** The same file in `files/msg/JP` decodes as:

| key | value |
|---|---|
| `place_town` | ハザマタウン |
| `place_stg1` | ラインラインランド |

✅ UK/US values are plain ASCII. 🔶 The other European directories were not
checked for encoding; Latin-1 or Shift-JIS-compatible ASCII are both plausible
and neither was verified.

⚠️ A European disc shipping Japanese text is itself worth knowing about: `msg/JP`
is 11 files that do not exist on the US build.

## Values contain markup

Values are not plain strings. Dialogue carries in-band control sequences —
`<k>` (wait for a key press) and `<p>` (page break) are both visible in
`global.txt`, and values contain literal newlines:

```
Boomer the exploding Pixl is\nnow your friend!\n<k>
```

🔶 The full set of control codes has not been enumerated here. Only the
container format is claimed.

## Why this matters

The game's *internal* item and character names are romaji
([and not English](item-data-table.md)). Anything that wants to show a human an
English name has to go through one of these files, and there is no index to
seek with — a reader walks the file from byte 0, splitting on NUL, and builds
its own map.

*(Source: bleck decision log D114. The hexdumps above were re-checked directly
against an extracted PAL rev 0 disc for this page.)*
