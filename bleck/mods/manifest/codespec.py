"""Compatibility shim: the `code` block now lives in `manifest/code/`.

Kept because `api/v1/mods.py`, `mods/code/parts.py`, `manifest/__init__.py` and
the tests all import from here, and a rename that breaks the JSON API's imports
would be a breaking change for what is purely a file move.

New code should import `bleck.mods.manifest.code` instead.
"""

from __future__ import annotations

# pylint: disable=unused-import
from bleck.mods.manifest.code import (  # noqa: F401
    _C_NAME_RE,
    DEFERRED_PATCH_KINDS,
    REL_DISC_PATH,
    BannerSpec,
    CodeSpec,
    ComboBinding,
    FunctionHook,
    HookMode,
    MapHook,
    PatchKind,
    ScriptPatch,
    _check_hook_address,
    _parse_banner,
    _parse_boot,
    _parse_code,
    _parse_combos,
    _parse_hook,
    _parse_hook_mode,
    _parse_hooks,
    _parse_maps,
    _parse_patch,
    _parse_patches,
    build_hook,
    build_patch,
)
from bleck.mods.manifest.replacements import (  # noqa: F401
    ScriptReplacement,
    build_replacement,
    parse_replacements,
)
from bleck.mods.manifest.selectors import _MAP_NAME_RE, _parse_selector  # noqa: F401
from bleck.script import emit  # noqa: F401
