"""The back end: a compiled program to one C translation unit.

`scaffold` is what a module is wired up to *do*, as values; `runtime_c` is the
C that ships inside every mod; `blocks` renders one table at a time, `checks`
refuses a module that cannot be written, `generate` assembles a single
program's and `merge` several mods' at once.

⚠️ **This is the facade; the modules under it do not re-export each other.**
A caller imports `emit.generate` or `emit.ModPart` from here, and a module
inside the package imports the name from whichever module defines it.
"""

from bleck.script.emit.blocks import BoundCombo, BoundHook
from bleck.script.emit.generate import (
    GeneratedSource,
    boot_source,
    generate,
    generate_bare,
)
from bleck.script.emit.merge import ModPart, generate_merged
from bleck.script.emit.scaffold import (
    BOOT_DELAY_FRAMES,
    BOOT_SCRIPT,
    DEFAULT_BANNER_SEQUENCES,
    DOOR_SCRIPTS,
    ENTRY_SCRIPT,
    MAX_COMBOS,
    MAX_MAP_HOOKS,
    NPC_SCRIPTS,
    SEQUENCE_NAMES,
    SUPPORTED_SELECTORS,
    Banner,
    ComboHook,
    DoorScript,
    FunctionHook,
    HookMode,
    MapHook,
    NpcScript,
    PatchKind,
    Scaffolding,
    ScriptPatch,
    ScriptReplacement,
    Sequence,
    mod_slug,
    prefix_for,
)

__all__ = [
    "BOOT_DELAY_FRAMES",
    "BOOT_SCRIPT",
    "DEFAULT_BANNER_SEQUENCES",
    "DOOR_SCRIPTS",
    "ENTRY_SCRIPT",
    "MAX_COMBOS",
    "MAX_MAP_HOOKS",
    "NPC_SCRIPTS",
    "SEQUENCE_NAMES",
    "SUPPORTED_SELECTORS",
    "Banner",
    "BoundCombo",
    "BoundHook",
    "ComboHook",
    "DoorScript",
    "FunctionHook",
    "GeneratedSource",
    "HookMode",
    "MapHook",
    "ModPart",
    "NpcScript",
    "PatchKind",
    "Scaffolding",
    "ScriptPatch",
    "ScriptReplacement",
    "Sequence",
    "boot_source",
    "generate",
    "generate_bare",
    "generate_merged",
    "mod_slug",
    "prefix_for",
]
