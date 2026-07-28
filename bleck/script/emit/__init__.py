"""The back end: a compiled program to one C translation unit.

`scaffold` is what a module is wired up to *do*, as values; `runtime_c` is the
C that ships inside every mod; `generate` assembles them.
"""

from bleck.script.emit.generate import (
    BoundCombo,
    BoundHook,
    GeneratedSource,
    ModPart,
    boot_source,
    generate,
    generate_bare,
    generate_merged,
)
from bleck.script.emit.scaffold import (
    BOOT_DELAY_FRAMES,
    BOOT_SCRIPT,
    DEFAULT_BANNER_SEQUENCES,
    ENTRY_SCRIPT,
    MAX_COMBOS,
    MAX_MAP_HOOKS,
    SEQUENCE_NAMES,
    Banner,
    ComboHook,
    MapHook,
    Scaffolding,
    ScriptPatch,
    mod_slug,
    prefix_for,
)

__all__ = [
    "BOOT_DELAY_FRAMES",
    "BOOT_SCRIPT",
    "DEFAULT_BANNER_SEQUENCES",
    "ENTRY_SCRIPT",
    "MAX_COMBOS",
    "MAX_MAP_HOOKS",
    "SEQUENCE_NAMES",
    "Banner",
    "BoundCombo",
    "BoundHook",
    "ComboHook",
    "GeneratedSource",
    "MapHook",
    "ModPart",
    "Scaffolding",
    "ScriptPatch",
    "boot_source",
    "generate",
    "generate_bare",
    "generate_merged",
    "mod_slug",
    "prefix_for",
]
