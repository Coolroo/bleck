"""Parsing `code.patches`: one vanilla `evt` instruction redirected into the mod."""

from __future__ import annotations

import re

from bleck.mods.errors import ManifestError
from bleck.mods.manifest.code.specs import ScriptPatch
from bleck.mods.manifest.opcodes import parse_expect
from bleck.mods.manifest.selectors import _parse_selector

_C_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_patches(raw: object, source: str) -> list[ScriptPatch]:
    """Read `code.patches`, a list of in-place bytecode replacements."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError(
            f"{source}: 'code.patches' must be a list of patch objects, e.g. "
            f'[{{"script": "map:he1_01", "at": 0, "expect": "DEBUG_PUT_MSG", '
            f'"call": "on_map_init"}}]'
        )
    return [
        _parse_patch(entry, f"{source}: 'code.patches[{i}]'")
        for i, entry in enumerate(raw)
    ]


def _parse_patch(raw: object, where: str) -> ScriptPatch:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    unknown = sorted(set(raw) - {"script", "at", "expect", "call"})
    if unknown:
        raise ManifestError(
            f"{where} has unknown field(s): {', '.join(unknown)}\n"
            f"  A patch takes 'script', 'at', 'expect' and 'call'."
        )
    for name in ("script", "expect", "call"):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ManifestError(f"{where} needs a non-empty {name!r} string")
    at = raw.get("at")
    if not isinstance(at, int) or isinstance(at, bool):
        raise ManifestError(
            f"{where}: 'at' must be a whole number of words from the start of "
            f"the script, not {type(at).__name__}"
        )
    return build_patch(
        str(raw["script"]), at, str(raw["expect"]), str(raw["call"]), where
    )


def build_patch(script: str, at: int, expect: str, call: str, where: str) -> ScriptPatch:
    """Validate one patch's four fields and resolve `expect` to a header word.

    Shared with the JSON API so both surfaces reject the same things.
    """
    selector = _parse_selector(script, where)
    if at < 0:
        raise ManifestError(
            f"{where}: 'at' is {at}, but a word offset cannot be negative"
        )
    if not _C_NAME_RE.match(call):
        raise ManifestError(
            f"{where}: 'call' is {call!r}, which is not a C function name.\n"
            f"  It names a function in this mod's own sources, e.g. 'on_map_init'."
        )
    return ScriptPatch(
        kind=selector.kind,
        target=selector.target,
        at=at,
        expect=expect,
        expect_word=parse_expect(expect, where),
        call=call,
        item_id=selector.item_id,
    )
