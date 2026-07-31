# effdata-probe

**Finding the loaded `effdata.dat` in memory** — and the worked example of
starting wide instead of following one pointer.

```bash
uv run python scripts/ingame.py effdata-probe --words 26 --seconds 90     --mods-dir example-mods
```

## What it found

✅ The file is loaded to MEM2, and **its header is relocated in place**: all
sixteen section offsets are rewritten to absolute pointers, so
`header[n] == buffer + offset[n]` for 16 of 16 (D199).

⚠️ That means a memory dump and a disc read of the same file show sixteen
numbers that look nothing alike and are the same sixteen facts.

## Why it scans instead of following a pointer

⛔ **The first version of this probe followed one pointer and was wrong.** D197
saw the loader do `stw r3,12(r4)` and read it as "the parsed file lands at
+0x0C". It does not — that is a file handle carrying `./eff/effdata.tpl` — and
finding out cost a full run (D198).

This version follows nothing. It sweeps MEM2 and then MEM1 for `EFDT` **plus
its build stamp**, a two-word signature that cannot occur by accident, and
reports generously around whatever it hits.

⚠️ The same lesson applies one level up. Before this ran, `ingame.py --find` was
given **two** patterns: the file's first sixteen bytes and the `EFDT` block. The
first got 0 hits, the second got 1 — and *that disagreement* is what revealed
the relocation. Either pattern alone would have given a clean, single, wrong
answer.
