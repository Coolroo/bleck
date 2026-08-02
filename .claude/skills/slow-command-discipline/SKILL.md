---
name: slow-command-discipline
description: Use before running anything in this repo that takes minutes — an in-game boot, a full model or texture export, a disc build, a dolscan sweep, a container build. Says what each costs, where its transcript already lives, and why re-running to widen a query is the standing mistake.
---

# Slow-command discipline

CLAUDE.md states the rule — **capture output to a file, then read slices from
the file**. This is the price list that makes it worth obeying, and the list of
artifacts that already exist so you do not recompute one.

## What things cost

| operation | cost | where its output already is |
|---|---|---|
| `scripts/ingame.py` — build, boot, read memory, shut down | **2–3 min** | `work/build/ingame.log`, full transcript, every run |
| a disc build + Dolphin glance | **2–3 min per glance** (D-log: "2-3 minutes per glance") | same |
| LZ77 compression | **~12 s/MB** (D16) | baseline numbers are recorded — cite them |
| `bleck model export`, whole corpus | 864 models, **137 MB** written | `work/export/models/` |
| `bleck texture export`, whole corpus | thousands of images | `work/export/` |
| `wit EXTRACT` / RVZ conversion | minutes, GB of output | `work/extracted/eu0` |
| `dolscan.py` sweeps (`callers`, `calls`, `strings`) | slow enough to notice on a 4 MB DOL | nothing — redirect it yourself |
| `./scripts/lint.sh --full` | every file; what CI runs | nothing — redirect it yourself |
| container / devkitPPC image build | minutes, and it is not incremental | Docker layer cache |

## The three rules

**1. Redirect, then read.**

```bash
uv run python scripts/dolscan.py callers 0x8028ea78 > "$CLAUDE_JOB_DIR/tmp/callers.txt" 2>&1
./scripts/lint.sh --full                            > "$CLAUDE_JOB_DIR/tmp/lint.txt"    2>&1
uv run pytest -q                                    > "$CLAUDE_JOB_DIR/tmp/tests.txt"   2>&1
```

Piping straight into `tail`/`head`/`grep` throws away output already paid for,
so seeing more means running the command again.

**2. ⚠️ When a filter turns out too narrow, re-read the file. Never re-run.**
Reading `--words 9` when the answer sat in word 10 has already cost a whole
repeat `ingame.py` run. **Ask for more than you think you need — the extra words
are free, and so is re-reading the log.**

This is the "start wide, then narrow" rule: a narrow first measurement has cost
a whole re-run every time.

**3. Check whether the artifact already exists.** Extraction, RVZ conversion,
exports and full-corpus sweeps all leave files on disk. `work/export/models/`
being present is not proof it is *current*, though — ⚠️ **check the mtime**
before believing it (D245: a person was sent `.glb` files written 48 minutes
before the fix and reported a bug that no longer existed).

## Recorded results are the citation

Measure once, write the number into `docs/decision-log.md`, cite the recorded
value thereafter. **Re-run a benchmark only when the code under test has
actually changed** — never to restate a number in conversation.

## Before spending a run, verify the instrument

An in-game run costs 2–3 minutes and is worth nothing if the probe cannot see
what it is looking for. Six runs and four decision-log entries (D70, D73, D74)
went into a bug that did not exist because the rig read `seqWork.p0`.

Ask, before the run: **what would this print if the thing I am testing worked?**
If the answer is "the same as if it did not", fix the probe first.

⚠️ **Prefer the two-line test to the new tool.** D71 built a whole script to
read a bound address, correctly, to answer a question that did not matter; one
extra `gw` write would have been more discriminating and taken minutes.
