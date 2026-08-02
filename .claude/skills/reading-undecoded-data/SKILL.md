---
name: reading-undecoded-data
description: Use when facing a binary file on the disc whose layout is unknown, or one of the game's own evt scripts. Covers scripts/modelscan.py (survey/header/offsets/at/strings/vectors/streams/chain/mesh) as the non-DOL counterpart to dolscan, and scripts/evtdis.py for reading vanilla scripts back.
---

# Reading undecoded data

Two tools, for the two kinds of thing on the disc that are not code.

## `scripts/modelscan.py` — an unknown binary file

`dolscan.py` is "find a string, find who builds its address, read the code".
**There was no equivalent for a data file**, and the character models in
`files/a/` were mapped with a dozen throwaway `python -c` snippets that answered
a question and then vanished. This keeps them.

⚠️ **The point is reproducibility, not convenience.** A finding in
`decision-log.md` says *what* was concluded; this lets the next person see it
again and disagree with it.

```bash
uv run python scripts/modelscan.py survey  files/a/p_wii_mario
uv run python scripts/modelscan.py header  files/a/p_wii_mario
uv run python scripts/modelscan.py offsets files/a/p_wii_mario
uv run python scripts/modelscan.py at      files/a/p_wii_mario 0x15f5c
uv run python scripts/modelscan.py strings files/a/p_wii_mario --min 6
uv run python scripts/modelscan.py mesh    files/a/p_wii_mario
```

Paths resolve as given **or** relative to `BLECK_BASE_DIR` (default
`work/extracted/eu0`), so `files/a/x` works from anywhere.

| subcommand | flags | what it settled |
|---|---|---|
| `survey` | `--window 4096` `--only KIND` | classifies windows as floats / strings / packed. Showed `p_wii_mario` is tables and matrices to `0x15F5C`, then 200 KB of dense packed data — where geometry had to be (D202) |
| `header` | `--limit 8` | the two nested records. ⚠️ **The bounding box is in the record the leading word points at**, not the opening one — reading the opening one gave a sub-object's box and made Mario 17.9 units tall instead of 73.4 |
| `offsets` | `--least 4` `--limit 20` | runs of ascending plausible file offsets. Found the table at `0x170`, which led to materials, matrices, indices and the texture path list |
| `at` | `--rows 8` | one place as hex, text **and** floats at once. Noise as hex is often obvious as floats |
| `strings` | `--min 4` `--search TEXT` | printable runs with offsets |
| `vectors` | `--start 0x…` | longest run of position triples, as f32 **and** s16. ⚠️ Both, because a float-only search once said `p_wii_mario` has no mesh at all (D204) |
| `streams` | `--least 64` `--limit 12` | runs of `u32` that all fit in `u16` — the signature of an index array, because the draw loop copies each with `lhz` and a stride of 4 |
| `chain` | `--limit 40` | walks the size-prefixed record chain |
| `mesh` | `--limit 4` | the decoded position and normal arrays |

## ⛔ When these do not yield, stop fitting and disassemble

Pattern-matching `p_wii_mario` failed **four times**. What worked was reading
the game's own draw code:

1. `dolscan.py callers 0x8028ea78` — who calls `GXSetVtxAttrFmt`. ⚠️ `xref`
   cannot answer this: it tracks `lis`/`addi` data addresses, not `bl`
   displacements, so it returns nothing and that reads as "nobody" (D206).
2. `dolscan.py dis 0x80048400 100` — the calls state the format outright:
   `GX_VA_POS`, `GX_POS_XYZ`, `GX_F32`, `GXSetArray` stride 12.
3. The inner loop reads four index streams from `+0x158`/`+0x160`/`+0x168`/`+0x16C`.
4. Those are **file** offsets — the loader relocates in place — so the table at
   `0x150` is the geometry, and `streams` confirms it (D207).

**Escalate to the `decode-by-disassembly` skill before the third statistical
fit, not after.** `vectors` above is explicitly superseded *as evidence* by
`mesh`, which reads the arrays the game itself points at rather than guessing.

## `scripts/evtdis.py` — the game's own scripts

`bleck` compiles *to* `evt` and never read it back, so every question about what
a vanilla script does was answered by reading raw hex. This closes that.

```bash
uv run python scripts/evtdis.py 0x8046AA58          # Count Bleck's onSpawn
uv run python scripts/evtdis.py 0x8046AA58 --raw    # keep the hex alongside
uv run python scripts/evtdis.py --template 196      # list one template's scripts
```

Other flags: `--dol` (default `work/extracted/eu0/sys/main.dol`), `--symbols`.

Script addresses come from the template table — `onSpawnScript` at
`NPCEnemyTemplate+0x30`, `moveScript` at `+0x38`, and so on. `--template N`
lists them for one template instead of taking an address.

⚠️ **DOL scripts only.** A pointer into a REL cannot be followed without knowing
where that REL was loaded, and the game's boss scripts are split across both. An
address outside the DOL is reported as such rather than decoded as garbage.

## Capture, don't filter

A `survey` over a 250 KB model or a `dis` sweep is slow enough to notice.
Redirect to a file and read slices from it; when the filter turns out too
narrow, **re-read the file** rather than re-running.

```bash
uv run python scripts/modelscan.py survey files/a/p_wii_mario > "$CLAUDE_JOB_DIR/tmp/survey.txt" 2>&1
```

## Related

- `decode-by-disassembly` — the escalation, and the highest-value method here
- `ground-truth-from-reference-rips` — when a decode needs an external answer key
- `control-every-statistic` — before believing any percentage a survey produced
