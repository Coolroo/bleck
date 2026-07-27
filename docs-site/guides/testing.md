---
title: Testing your build
description: Running a modded disc, per platform
---

`bleck` verifies structure — that archives repack correctly and the base stays
clean. Only running the game verifies that it *works*.

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

  === "Windows"

      `bleck launch` works here, or drag the `.wbfs` onto Dolphin.

      This is the best platform for visual testing — Dolphin runs Super Paper
      Mario at full speed on typical desktop hardware.

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

      On a desktop this is fine. On ARM single-board computers, see below.

  === "Raspberry Pi"

      Dolphin **will** boot a Wii disc on a Pi 4, but nowhere near fast enough to
      reach the title screen in reasonable time.

      It is still useful as a smoke test — it proves the disc is valid and
      readable:

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

??? note "Your change appears"

    The pipeline worked end to end, including recompression.

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
