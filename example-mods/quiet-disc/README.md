# quiet-disc

**Turning the `mod_loaded` banner off.**

Every disc `bleck` builds draws `mod_loaded: <name>` on the title screen,
including one whose mod is nothing but textures or placements — otherwise a
modded disc is impossible to tell from a stock one without playing it.

This is how a mod declines. `"banner": false` is a complete `code` block on its
own; the disc then carries no `mod.rel` at all.

```bash
uv run bleck mod check quiet-disc --mods-dir example-mods
```

⚠️ It has no overlay, so it changes nothing. It exists to show the escape hatch
and to hold the two edges it exposed (D180): the block used to be refused as
"nothing to compile", and once accepted it built an empty module that `elf2rel`
rejected with `max() iterable argument is empty`.
