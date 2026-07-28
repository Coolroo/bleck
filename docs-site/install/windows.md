---
title: Windows
description: Installing bleck on Windows 11
---

Windows 11 is fully supported: `extract`, `mod build` and `launch` all work, and
a disc you build here boots in Dolphin.

1.  **Install uv**

    ```powershell
    winget install --id=astral-sh.uv -e
    ```

    Or: `irm https://astral.sh/uv/install.ps1 | iex`

1.  **Clone and sync**

    ```powershell
    git clone git@github.com:Coolroo/bleck.git
    cd bleck
    uv sync --extra dev
    ```

1.  **Install Wiimms ISO Tools**

    Download the Windows build from [wit.wiimm.de](https://wit.wiimm.de/) and
    unpack it.

    !!! warning

        The Windows build is a **Cygwin** build: `wit.exe` needs the 31 `cyg*.dll`
        files that sit beside it in `bin\`. Add that whole directory to your PATH —
        copying `wit.exe` out on its own will not run.

1.  **Install Dolphin**

    You need two executables from it: `DolphinTool.exe` to read and write RVZ,
    and `Dolphin.exe` to boot what you build.

    !!! warning

        **Do not use winget.** `DolphinEmulator.Dolphin` is version **5.0** — the
        2016 stable release. It predates RVZ and ships no `DolphinTool.exe` at all.

    Get a development build from
    [dolphin-emu.org/download](https://dolphin-emu.org/download/). It arrives as
    a `.7z`, which Windows cannot open natively. If you do not have 7-Zip, the
    standalone extractor needs no install and no admin rights:

    ```powershell
    irm https://www.7-zip.org/a/7zr.exe -OutFile 7zr.exe
    .\7zr.exe x dolphin.7z -o"$env:USERPROFILE\tools\dolphin"
    ```

    Dolphin is portable — the extracted folder can live anywhere.

1.  **Point bleck at the tools**

    ```powershell
    $env:BLECK_WIT          = "$env:USERPROFILE\tools\wit\bin\wit.exe"
    $env:BLECK_DOLPHIN_TOOL = "$env:USERPROFILE\tools\dolphin\DolphinTool.exe"
    $env:BLECK_DOLPHIN      = "$env:USERPROFILE\tools\dolphin\Dolphin.exe"
    ```

    Skip this if both are already on your PATH.

1.  **Verify**

    ```powershell
    uv run pytest
    uv run bleck --help
    ```
{ .steps }


## For code and script mods

Only needed if you write behaviour rather than swap assets. Two extra tools:

| Tool | Why |
|---|---|
| **devkitPPC** | compiles scripts and code mods |
| **`wstrt`** (Wiimms SZS Toolset) | embeds the Gecko loader into the disc, so a code mod needs no emulator configuration |

```powershell
winget install devkitPro.devkitProUpdater
```

!!! warning

    `wstrt` ships in **Wiimms SZS Toolset**, a different download from `wit`. Get
    the Cygwin build from [szs.wiimm.de](https://szs.wiimm.de/download.html), unpack
    it, and set `BLECK_WSTRT` to `wstrt.exe` — the folder name is version-stamped,
    so a PATH entry goes stale on every update.

## Where bleck looks for tools

Beyond your PATH:

| Tool | Locations |
|---|---|
| `wit.exe` | `C:\Program Files\Wiimm\wit\bin`, `C:\Program Files (x86)\Wiimm\wit\bin`, `C:\wit\bin` |
| `DolphinTool.exe`, `Dolphin.exe` | `C:\Program Files\Dolphin`, `C:\Program Files (x86)\Dolphin`, `C:\Program Files\Dolphin-x64` |

Anywhere else, set the variables above.

!!! warning

    **`setx` does not affect shells that are already open.** It writes the user
    registry, but running processes keep the environment they inherited at launch —
    so a variable can be "set" and still invisible to your current terminal. Set
    `$env:` inline as well, or open a new shell.

!!! tip

    `BLECK_DOLPHIN` and `BLECK_DOLPHIN_TOOL` are **different executables** that ship
    in the same folder. `DolphinTool` converts images; `Dolphin` boots them.

## Without uv

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

!!! note

    If activation fails with a script-execution error:

    ```powershell
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    ```

    `uv run` avoids this entirely, which is why it is recommended here.
