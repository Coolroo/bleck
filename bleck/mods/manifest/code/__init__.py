"""A mod's `code` block: scripts, native sources, hooks, patches, boot map.

Split out of a single `codespec.py` once it passed 690 lines and this feature was
about to add a fifth concern to it. The division is by *job*, not by size:

    specs.py     the shapes, data only
    parse.py     reading a `code` block out of mod.json
    patches.py   code.patches -- one vanilla instruction redirected
    hooks.py     code.hooks -- run before, after or instead of a game function

⚠️ `bleck.mods.manifest.codespec` still re-exports everything here, so existing
imports keep working. New code should import from this package directly.
"""

from __future__ import annotations

from bleck.mods.manifest.code.hooks import (
    _check_hook_address,
    _parse_hook,
    _parse_hook_mode,
    _parse_hooks,
    build_hook,
)
from bleck.mods.manifest.code.parse import (
    _parse_banner,
    _parse_boot,
    _parse_code,
    _parse_combos,
    _parse_maps,
)
from bleck.mods.manifest.code.patches import (
    _C_NAME_RE,
    _parse_patch,
    _parse_patches,
    build_patch,
)
from bleck.mods.manifest.code.specs import (
    REL_DISC_PATH,
    BannerSpec,
    CodeSpec,
    ComboBinding,
    FunctionHook,
    HookMode,
    MapHook,
    PatchKind,
    ScriptPatch,
)
from bleck.mods.manifest.selectors import DEFERRED_PATCH_KINDS

__all__ = [
    "DEFERRED_PATCH_KINDS",
    "REL_DISC_PATH",
    "_C_NAME_RE",
    "BannerSpec",
    "CodeSpec",
    "ComboBinding",
    "FunctionHook",
    "HookMode",
    "MapHook",
    "PatchKind",
    "ScriptPatch",
    "_check_hook_address",
    "_parse_banner",
    "_parse_boot",
    "_parse_code",
    "_parse_combos",
    "_parse_hook",
    "_parse_hook_mode",
    "_parse_hooks",
    "_parse_maps",
    "_parse_patch",
    "_parse_patches",
    "build_hook",
    "build_patch",
]
