---
title: Testing your build
description: Running a modded disc, per platform
---

`bleck` checks structure — that archives repack correctly and the base stays
clean. Only running the game shows whether your change does what you meant.

## Choosing a format

Build to **WBFS** unless you know your Dolphin is recent:

```bash
uv run bleck mod build my-mod work/out/my-mod.wbfs
```

See [Disc formats](../concepts/disc-formats.md) for why.

## Running it

The quickest route is to let `bleck` do it, on any platform:

```bash
uv run bleck mod build my-mod work/out/my-mod.wbfs --force --launch
```

That builds and boots in one step. For an image you already have:

```bash
uv run bleck launch --batch work/out/my-mod.wbfs
```

`--batch` skips Dolphin's game list and goes straight into the game. Both need
the emulator itself, found via `BLECK_DOLPHIN`.

## Starting in a particular level

Super Paper Mario boots into its attract demo — two maps, `aa4_01` and
`ls4_12` — and nothing else happens without someone holding a Wii remote. If
your mod changes Lineland, that is a lot of controller work before you can see
it.

`--map` puts the destination in the disc, so it takes itself there:

```bash
uv run bleck mod build my-mod work/out/my-mod.wbfs --force --map he1_01 --launch
```

It takes either the map's name or the game's own id, both of which
`bleck maps` prints:

```bash
uv run bleck maps --search he1     # 26  he1_01  Ch 1-1  Lineland
uv run bleck mod build my-mod --map 26
```

This works on **any** mod, including one that ships nothing but a texture —
`bleck` generates the small script that drives the map change, so there is
nothing to write.

To make it permanent for a mod, put it in `mod.json` instead of passing the
flag every time:

```json
{
  "name": "my-mod",
  "code": { "boot": "he1_01" }
}
```

!!! warning "The player starts uninitialised"

    A map entered this way has no save file and no profile behind it, so
    **Mario is invisible** and anything depending on player state — damage,
    items, the pause menu — cannot be trusted. This is a way to *look* at a
    map, not to play it. Load a save state (`--state`) for that.

!!! note "This does not skip the logos"

    The disc changes maps on the first frame of gameplay, which is still about
    45 seconds of logos away. `bleck launch --fast` uncaps the emulator and
    reaches that point in about 6 seconds, but it uncaps the **whole session**,
    gameplay included, and there is no way to restore the cap part-way
    through — so it is for unattended runs, not for playing.

## Per-platform notes

  === "Windows"

      `bleck launch` works here, or drag the `.wbfs` onto Dolphin.

      Dolphin runs Super Paper Mario at full speed on typical desktop hardware,
      which makes this a good platform for visual testing.

      !!! warning

          If you see *"Is an invalid GCM/ISO file, or is not a GC/Wii ISO"* when
          opening an **RVZ**, your Dolphin predates RVZ support (5.0-12188, 2020).
          Build to `.wbfs` instead, or update Dolphin.

      !!! note

          `DolphinTool verify` reports three **Low** severity problems on any disc
          `bleck` builds — a missing update partition, an unsigned DATA partition, and
          a format that does not record the disc size. All three are expected and none
          prevent booting.

  === "macOS"

      Open the `.wbfs` with Dolphin.app, or use `bleck launch`.

      Performance is good on Apple Silicon. On Intel Macs expect it to depend
      heavily on the GPU.

  === "Linux"

      ```bash
      dolphin-emu -e work/out/my-mod.wbfs
      ```

      !!! warning

          The emulator is `dolphin-emu`. Plain `dolphin` is KDE's **file manager**,
          which is installed on many desktops — running it will open a file browser.

      For a headless smoke test that the disc is valid and readable, run Dolphin
      with no window and no video backend:

      ```bash
      timeout -k 15 90 dolphin-emu-nogui \
          -u /tmp/dolphin-user -p headless -v Null \
          -C Logger.Options.WriteToConsole=True \
          -C Logger.Options.Verbosity=4 \
          -C Logger.Logs.BOOT=True \
          -C Logger.Logs.FILEMON=True \
          -e work/out/my-mod.wbfs
      ```

      !!! tip

          `Logger.Logs.FILEMON=True` names **every file the game reads**, which is a
          precise way to confirm a modified file is actually being loaded:

          ```
          W[FileMon]:  251 kB msg/UK/global.txt
          W[FileMon]:  543 kB sptexture.tpl
          ```

      Always wrap it in `timeout -k` — Dolphin ignores a plain `SIGTERM`.

## What to look for

The first thing to check is the **title screen**, which shows
`mod_loaded: <name>` in the bottom right for any mod that ships code. That one
line separates two failures which otherwise look identical:

- **The label is there, your change is not.** The module loaded and ran; the
  problem is in what it does.
- **No label at all.** The module never loaded, so nothing it contains could
  have run. Look at the build and the loader, not at your code.

Without it, "nothing happened" is ambiguous.

??? note "Your change appears"

    Nothing to do — the whole pipeline ran, including recompression.

??? note "Everything looks normal"

    The merge did not take. Check `bleck mod status` shows the file you expect,
    and diff the staged build against the base.

??? note "It hangs or errors where your file loads"

    Something about the rebuilt file is wrong. Confirm the archive round-trips:

    ```bash
    uv run bleck verify work/build/my-mod/files/lyt/title.bin.uk
    ```

## Verifying without an emulator

Much can be checked before booting:

```bash
uv run bleck verify work/extracted/eu0/files/map    # every archive round-trips
uv run bleck mod check my-mod                  # conflicts, no writes
diff -r --brief work/extracted/eu0 work/build/my-mod     # exactly what changed
```
