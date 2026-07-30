# Your mods

This directory is yours. `bleck` looks here by default, and it starts empty.

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

Set `BLECK_MODS_DIR` in `.env` to change the default permanently.
