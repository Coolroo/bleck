# Windows 11 Setup

Windows is a supported target for `bleck` (D27) and is where emulation testing
happens, since Dolphin runs SPM at full speed there.

✅ **Verified end to end on Windows 11** (D33, D35, D36): the test suite, the
linters, `extract`, `verify`, `mod build` and `launch` all pass against real game
data, and a disc built here boots in Dolphin with modified textures.

This document is the recipe that was actually followed, including the parts that
went wrong. Versions known to work are named at the end.

---

## 1. Install uv

```powershell
winget install --id=astral-sh.uv -e     # or: irm https://astral.sh/uv/install.ps1 | iex
```

[uv](https://docs.astral.sh/uv/) is recommended over pip here: no venv
activation, no execution-policy dance, and the exact dependency versions from
`uv.lock`.

## 2. Clone and sync

```powershell
git clone git@github.com:Coolroo/bleck.git
cd bleck
uv sync --extra dev
```

**With pip instead**, if you would rather not add a tool:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

If activation fails with a script-execution error, allow it for this session
only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 3. Install Wiimms ISO Tools (`wit`)

Download the Windows build from <https://wit.wiimm.de/> and unpack it. It ships
a `windows-install.exe`, but you can equally just extract it and point `bleck` at
the binary — that is what was done here (`%USERPROFILE%\tools\wit`).

⚠️ **The Windows build is a Cygwin build.** `wit.exe` sits in `bin\` alongside
**31 `cyg*.dll` files** and will not run without them. Do not copy `wit.exe`
alone onto your PATH — add the whole `bin\` directory, or set `BLECK_WIT` to it
in place.

## 4. Install Dolphin

Needed twice over: `DolphinTool.exe` reads and writes RVZ, and `Dolphin.exe`
boots what you build.

⚠️ **Do not install Dolphin from winget.** `DolphinEmulator.Dolphin` is **5.0**,
the 2016 stable release. It predates RVZ entirely and does not include
`DolphinTool.exe` at all (D34). This is D24's lesson arriving through a new door.

Get a development build from <https://dolphin-emu.org/download/>.

⚠️ **The download page returns HTTP 403 to non-browser requests.** If you are
scripting it, use the JSON update API instead, which lists current per-system
artifact URLs:

```powershell
irm https://dolphin-emu.org/update/latest/beta | Select-Object -ExpandProperty artifacts
```

Dolphin ships as a **`.7z`**, and Windows cannot open those natively. If you do
not have 7-Zip and would rather not install it (winget's 7-Zip needs elevation),
the standalone extractor needs neither install nor admin rights:

```powershell
irm https://www.7-zip.org/a/7zr.exe -OutFile 7zr.exe
.\7zr.exe x dolphin.7z -o"$env:USERPROFILE\tools\dolphin"
```

Dolphin is portable — there is no installer. The extracted folder holds
`Dolphin.exe`, `DolphinTool.exe`, `Sys\` and the Qt DLLs, and can live anywhere.

## 5. Point `bleck` at the tools

`bleck` searches PATH first, then these locations:

- `C:\Program Files\Dolphin`, `C:\Program Files (x86)\Dolphin`, `C:\Program Files\Dolphin-x64`
- `C:\Program Files\Wiimm\wit\bin`, `C:\Program Files (x86)\Wiimm\wit\bin`, `C:\wit\bin`

Anywhere else — including the `%USERPROFILE%\tools\...` layout above — point at
them explicitly:

```powershell
$env:BLECK_WIT          = "$env:USERPROFILE\tools\wit\bin\wit.exe"
$env:BLECK_DOLPHIN_TOOL = "$env:USERPROFILE\tools\dolphin\DolphinTool.exe"
$env:BLECK_DOLPHIN      = "$env:USERPROFILE\tools\dolphin\Dolphin.exe"
```

`BLECK_DOLPHIN_TOOL` and `BLECK_DOLPHIN` are **different executables in the same
folder**. `DolphinTool` converts and inspects images; `Dolphin` boots them.
Swapping them fails in confusing ways, which is why they are separate settings.

Use `setx` to persist across sessions — but ⚠️ **`setx` does not affect shells
that are already open.** It writes the user registry, and running processes keep
the environment block they inherited at launch, so the variable can be "set" and
still invisible to your current terminal. This cost real debugging time (D35).
Set `$env:` inline as well, or open a new shell.

Every configurable path is declared in
[`bleck/common/env.py`](../bleck/common/env.py) — that file is the complete list.

## 6. Verify

```powershell
uv run pytest             # expect 164 passed
uv run python scripts\lint.py
uv run bleck --help
```

Without uv, activate the venv first and drop the `uv run` prefix.
`scripts\lint.ps1` wraps the same logic, which lives in `scripts/lint.py` so no
shell is required.

---

## Use

```powershell
uv run bleck extract "path\to\Super Paper Mario.rvz" extracted\eu0
uv run bleck mod new my-mod
uv run bleck mod vendor my-mod lyt/title.bin.uk/arc/timg/mario.tpl
# edit mods\my-mod\overlay\files\lyt\title.bin.uk\arc\timg\mario.tpl
uv run bleck mod build my-mod out\my-mod.wbfs --launch
```

Disc paths use forward slashes on every platform — they address disc and archive
contents, not the host filesystem.

`--launch` boots the result once it is built; `bleck launch <image>` does the
same for an image you already have. Add `--batch` to skip Dolphin's game list and
go straight into the game.

### If you launch Dolphin yourself

⚠️ **Pass the path as a separate argument, not inside `--exec=`.** PowerShell's
`Start-Process -ArgumentList '--exec="C:\path\game.wbfs"'` forwards the quotes
literally, and Dolphin then reports:

> Could not be opened! This may happen with improper permissions, or use by
> another process.

which blames permissions for what is really a mangled argument. Use `-e` with the
path as its own token:

```powershell
Start-Process Dolphin.exe -ArgumentList '-b', '-e', 'W:\path\game.wbfs'
```

`bleck launch` always does this, so it cannot hit the trap.

### Reading a rebuilt disc's verification output

`DolphinTool verify` reports three **Low** severity problems on any disc `bleck`
builds. All three are expected and none prevent booting:

| Reported | Why |
|---|---|
| The update partition is missing | `--psel data` extracts only the data partition |
| The DATA partition is not correctly signed | It is modified; Dolphin does not enforce signing |
| The format does not store the size of the disc image | WBFS scrubs unused sectors |

---

## For code and script mods

Only needed if you write behaviour rather than swap assets.

**devkitPPC** supplies the cross-compiler:

```powershell
winget install devkitPro.devkitProUpdater
```

⚠️ If winget reports "No package found", grab the installer from
[the devkitPro releases](https://github.com/devkitPro/installer/releases)
directly — that happened here.

**Wiimms SZS Toolset** supplies `wstrt`, which embeds the Gecko loader into the
disc so a code mod runs with **no Dolphin cheat configuration at all**. It is a
different download from `wit`:

```powershell
$zip = "$env:TEMP\szs.zip"
Invoke-WebRequest "https://szs.wiimm.de/download/szs-v2.42a-r8989-cygwin64.zip" -OutFile $zip
Expand-Archive $zip "$env:USERPROFILE\tools\szs" -Force
```

⚠️ The extracted folder is **version-stamped** (`szs-v2.42a-r8989-cygwin64`), so
pointing `BLECK_WSTRT` at the binary is easier than adding it to PATH — a PATH
entry goes stale on every update:

```powershell
setx BLECK_WSTRT "$env:USERPROFILE\tools\szs\szs-v2.42a-r8989-cygwin64\bin\wstrt.exe"
setx BLECK_SYMBOLS_DIR "W:\Repos\bleck\symbols"
setx BLECK_GECKO_DIR   "W:\Repos\bleck\gecko"
```

The symbol list and the loader codelist are third-party and do not ship with
`bleck`; see [`scripting.md`](./scripting.md).

## Working on the docs site

`docs-site/` is a [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
site published to GitHub Pages. **No Node toolchain is needed** — it installs
with the same `uv` used for everything else:

```powershell
uv sync --extra docs
uv run mkdocs serve      # preview on http://127.0.0.1:8000
uv run mkdocs build --strict
```

`--strict` turns broken internal links into a build failure, and CI runs the
same command on every pull request.

⚠️ **`mkdocs.yml` sets `docs_dir: docs-site` deliberately.** MkDocs defaults to
`docs/`, which here is the internal design record. Publishing that would be a
mistake nobody would notice until it was indexed.

---

## What a fresh clone does *not* include

- **`work/roms/` and `work/extracted/`** are gitignored. Supply your own disc image.
- **`mods/*/overlay/`** is gitignored — it holds extracted game assets. The
  `title-invert` and `tex-koopa` manifests are committed, so they resolve as a
  dependency chain, but override nothing until re-vendored.
  `bleck mod status title-invert` reporting "overrides nothing yet" is correct,
  not a broken checkout.
- **Built disc images** (`*.iso`, `*.rvz`, `*.wbfs`, `out/`) are gitignored.

## Format choice for sharing builds

**Use `.wbfs`.** RVZ needs Dolphin **5.0-12188 (2020) or newer**; the last stable
release, 5.0 from 2016, rejects it as *"Is an invalid GCM/ISO file, or is not a
GC/Wii ISO"* (D24).

| Format | Size | Compatibility |
|---|---|---|
| `.wbfs` | ~424 MB | every Dolphin build |
| `.rvz` | ~249 MB | Dolphin ≥ 5.0-12188 |
| `.iso` | 4.5 GB | everything |

---

## Versions this was verified against

| | Version |
|---|---|
| Windows | 11 Home 10.0.26200 |
| Python | 3.13.14 |
| uv | 0.7.19 |
| `wit` | Wiimms ISO Tool v3.05a r8638 cygwin64 (2022-08-27) |
| Dolphin | 2606 (development build) |
| 7-Zip | 26.02 (`7zr.exe` standalone) |
