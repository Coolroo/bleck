"""The back end: a compiled program to one C translation unit.

Three files, three jobs. `scaffold` is what a module is wired up to *do*, as
values. `runtime_c` is the C that ships inside every mod, which is data rather
than logic. `generate` assembles them.

Every name the rest of the toolkit uses is re-exported here, so `emit.MapHook`
and `emit.generate` mean what they always have.
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
    "boot_source",
    "generate",
    "generate_bare",
    "generate_merged",
    "mod_slug",
    "prefix_for",
]
