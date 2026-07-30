# Your mods

This directory is yours. `bleck` looks here by default, it starts empty, and
**everything in it is git-ignored** except this file.

That is deliberate. A probe mod is written to answer one question and is worth
nothing once the question is answered; keeping them out of git stops the
directory silting up with a dozen near-duplicates, which is what happened
before (D147, and again in D175).

```bash
uv run bleck mod new my-mod
```

## The shipped examples live next door

[`example-mods/`](../example-mods/) holds worked examples of every concept and
the probe mods that produced the findings in `docs/decision-log.md`. Build one
by pointing `bleck` at that directory:

```bash
uv run bleck mod build coin-tick --mods-dir example-mods
```

⚠️ **Dependencies resolve within one directory.** A mod in `mods/` that depends
on one in `example-mods/` will not find it — copy what you need across rather
than reaching between the two.

## Promoting one

When a mod here turns out to be a worked example -- it demonstrates a concept, or
it produced a finding recorded in `docs/decision-log.md` -- **copy it** to
`example-mods/` and commit it there:

```bash
cp -r mods/my-mod example-mods/my-mod
rm -rf example-mods/my-mod/overlay
uv run bleck mod check my-mod --mods-dir example-mods
```

Copy rather than move: the working version stays where you are working on it.
Drop `overlay/` in the copy, since it is build output and is regenerated.

Set `BLECK_MODS_DIR` in `.env` to change the default permanently.
