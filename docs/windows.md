# Windows 11 Setup

Windows is a supported target for `bleck` (D27) and is where emulation testing
happens, since Dolphin runs SPM at full speed there.

⚠️ **Not yet verified on Windows.** The portability work is informed fixes plus
tests that simulate the Windows paths on Linux. Running `python -m pytest` on a
Windows machine is what turns "should work" into "does" — please report back.

---

## Install

```powershell
git clone git@github.com:Coolroo/bleck.git
cd bleck

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

If activation fails with a script-execution error, allow it for this session
only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Verify

```powershell
python -m pytest          # expect 134 passed
python scripts\lint.py    # expect "all checks passed"
bleck --help
```

`scripts\lint.ps1` is a wrapper around the same thing. The real logic lives in
`scripts/lint.py` so no shell is required.

## External tools

`bleck` shells out to two tools; neither is bundled.

| Tool | Where from | Needed for |
|---|---|---|
| `wit.exe` | https://wit.wiimm.de/ | `extract`, `build` |
| `DolphinTool.exe` | ships with Dolphin | RVZ read/write |

`bleck` searches PATH first, then these locations:

- `C:\Program Files\Dolphin`, `C:\Program Files (x86)\Dolphin`, `C:\Program Files\Dolphin-x64`
- `C:\Program Files\Wiimm\wit\bin`, `C:\Program Files (x86)\Wiimm\wit\bin`, `C:\wit\bin`

Anywhere else, point at them explicitly:

```powershell
$env:BLECK_WIT = "C:\path\to\wit.exe"
$env:BLECK_DOLPHIN_TOOL = "C:\Program Files\Dolphin\DolphinTool.exe"
```

Use `setx` instead of `$env:` to persist across sessions. Every configurable
path is declared in [`bleck/common/env.py`](../bleck/common/env.py) — that file
is the complete list.

## Use

```powershell
bleck extract "path\to\Super Paper Mario.rvz" extracted\eu0
bleck mod new my-mod
bleck mod vendor my-mod lyt/title.bin.uk/arc/timg/mario.tpl
# edit mods\my-mod\overlay\files\lyt\title.bin.uk\arc\timg\mario.tpl
bleck mod build my-mod out.wbfs
```

Disc paths use forward slashes on every platform — they address disc and archive
contents, not the host filesystem.

---

## What a fresh clone does *not* include

- **`roms/` and `extracted/`** are gitignored. Supply your own disc image.
- **`mods/*/overlay/`** is gitignored — it holds extracted game assets. The
  `title-invert` and `tex-koopa` manifests are committed, so they resolve as a
  dependency chain, but override nothing until re-vendored.
  `bleck mod status title-invert` reporting "overrides nothing yet" is correct,
  not a broken checkout.

## Format choice for sharing builds

**Use `.wbfs`.** RVZ needs Dolphin **5.0-12188 (2020) or newer**; the last stable
release, 5.0 from 2016, rejects it as *"Is an invalid GCM/ISO file, or is not a
GC/Wii ISO"* (D24).

| Format | Size | Compatibility |
|---|---|---|
| `.wbfs` | ~424 MB | every Dolphin build |
| `.rvz` | ~249 MB | Dolphin ≥ 5.0-12188 |
| `.iso` | 4.5 GB | everything |
