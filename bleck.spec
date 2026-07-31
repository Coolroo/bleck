# PyInstaller build for a single-file `bleck` executable.
#
# Run with `pyinstaller bleck.spec` -- a spec rather than a command line so the
# same file works on Linux, macOS and Windows. `--add-data` needs `:` on POSIX
# and `;` on Windows, and a matrix build that differs only in a separator is a
# matrix build that breaks on one platform and nobody notices.
#
# ⚠️ The five JSON catalogs must land at paths that mirror the package,
# because each is found with `Path(__file__).with_name(...)`:
#
#     bleck/backends/maps.py    -> mapcatalog.json
#     bleck/backends/doors.py   -> doorcatalog.json
#     bleck/formats/setup.py    -> npccatalog.json
#     bleck/formats/items.py    -> itemcatalog.json
#     bleck/script/catalog.py   -> catalog.json
#
# Under a frozen build `__file__` points inside the extraction directory, so as
# long as the data is bundled beside its module the lookup resolves unchanged.
# Getting this wrong produces a binary that runs and then reports an empty
# builtin catalog, which reads as a corrupt install rather than a packaging bug.

from PyInstaller.utils.hooks import collect_submodules

DATA = [
    ("bleck/backends/mapcatalog.json", "bleck/backends"),
    ("bleck/backends/doorcatalog.json", "bleck/backends"),
    ("bleck/formats/npccatalog.json", "bleck/formats"),
    ("bleck/formats/itemcatalog.json", "bleck/formats"),
    ("bleck/script/catalog.json", "bleck/script"),
]

# CLI commands are discovered by importing the package, so nothing statically
# references them by name. PyInstaller follows imports, not intentions.
HIDDEN = collect_submodules("bleck.cli.commands")

analysis = Analysis(
    ["bleck/__main__.py"],
    pathex=[],
    binaries=[],
    datas=DATA,
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # `pyelf2rel` and `dolphin-memory-engine` are dev-time tools, not part of
    # what a user runs; excluding them keeps the binary from carrying a REL
    # writer and a debugger attachment nobody asked for.
    excludes=["pytest", "mkdocs", "libWiiPy"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="bleck",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
