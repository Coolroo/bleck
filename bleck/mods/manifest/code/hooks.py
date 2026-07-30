"""Parsing `code.hooks`: a mod function running before, after or instead of a
game function.
"""

from __future__ import annotations

from bleck.mods.errors import ManifestError
from bleck.mods.manifest.code.patches import _C_NAME_RE
from bleck.mods.manifest.code.specs import FunctionHook, HookMode


def _parse_hooks(raw: object, source: str) -> list[FunctionHook]:
    """Read `code.hooks`, a list of functions replaced by the mod's own."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError(
            f"{source}: 'code.hooks' must be a list of hook objects, e.g. "
            f'[{{"function": "npcDispMain", "call": "count_npcs", '
            f'"mode": "replace"}}]'
        )
    return [
        _parse_hook(entry, f"{source}: 'code.hooks[{i}]'") for i, entry in enumerate(raw)
    ]


def _parse_hook(raw: object, where: str) -> FunctionHook:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    unknown = sorted(set(raw) - {"function", "call", "mode"})
    if unknown:
        raise ManifestError(
            f"{where} has unknown field(s): {', '.join(unknown)}\n"
            f"  A hook takes 'function', 'call' and 'mode'."
        )
    for name in ("function", "call"):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ManifestError(f"{where} needs a non-empty {name!r} string")
    mode = raw.get("mode", "replace")
    if not isinstance(mode, str):
        raise ManifestError(f"{where}: 'mode' must be a string")
    return build_hook(str(raw["function"]), str(raw["call"]), mode, where)


def build_hook(function: str, call: str, mode: str, where: str) -> FunctionHook:
    """Validate one hook's three fields. Shared with the JSON API.

    The symbol is *not* resolved here: that needs the target's list, which the
    build loads. This checks only what is decidable from the manifest alone.
    """
    hook = FunctionHook(
        function=function.strip(), call=call, mode=_parse_hook_mode(mode, where)
    )
    if not _C_NAME_RE.match(call):
        raise ManifestError(
            f"{where}: 'call' is {call!r}, which is not a C function name.\n"
            f"  It names a function in this mod's own sources, e.g. 'count_npcs'."
        )
    if hook.is_address:
        _check_hook_address(hook.function, where)
    elif not _C_NAME_RE.match(hook.function):
        raise ManifestError(
            f"{where}: 'function' is {function!r}, which is neither a symbol "
            f"name nor an address.\n"
            f"  Write the game function's name -- 'npcDispMain' -- so bleck "
            f"resolves it against the target's symbol list, or an address like "
            f"'0x801adef0' when it has no name.\n"
            f"  `bleck symbols search <text>` lists what the list holds."
        )
    return hook


def _parse_hook_mode(mode: str, where: str) -> HookMode:
    """The wire value decoded, or an error naming what each real mode does.

    The names alone do not say which order they run in, which is the one thing
    someone choosing between them needs.
    """
    found = HookMode.parse(mode)
    if found is not None:
        return found
    hint = "".join(f"\n    {known}: runs {known.means}" for known in HookMode)
    raise ManifestError(f"{where}: 'mode' is {mode!r}, which is not a hook mode.{hint}")


def _check_hook_address(text: str, where: str) -> None:
    try:
        value = int(text, 16)
    except ValueError:
        raise ManifestError(
            f"{where}: 'function' is {text!r}, which starts like an address but "
            f"is not hexadecimal. Write it as '0x801adef0'."
        ) from None
    if not 0x80000000 <= value <= 0x8FFFFFFF:
        raise ManifestError(
            f"{where}: 'function' is {text!r}, which is not a game address.\n"
            f"  The Wii's cached MEM1 window is 0x80000000..0x817FFFFF; code "
            f"lives there."
        )
    if value % 4:
        raise ManifestError(
            f"{where}: 'function' is {text!r}, which is not 4-byte aligned, so "
            f"no instruction begins there."
        )
