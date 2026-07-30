"""Resolving a patch's `expect` field to an `evt` header word.

Split out of `codespec` so `replacements` can reuse it: both surfaces must agree
on what an opcode name means, and importing it from `codespec` would be a cycle.
"""

from __future__ import annotations

import difflib

from bleck.mods.errors import ManifestError
from bleck.script import evt

#: The replacement is `USER_FUNC` with the replaced instruction's own argument
#: count: `EVT_HELPER_CMD(n, 92)`, the pointer to `call`, then the original's
#: words 2..n unchanged. So `n` must leave room for the pointer.
MIN_ARGUMENT_COUNT = 1

#: Why the size is fixed, said once and quoted by the errors.
_SAME_SIZE_ONLY = (
    "  bleck replaces an instruction with a USER_FUNC declaring the same "
    "number of arguments, so the patch is exactly the same size: a shorter or "
    "longer instruction moves every label after it, and each running script "
    "caches its jump table when it starts (D87)."
)


def parse_expect(raw: str, where: str) -> int:
    """Resolve `expect` -- a header word, or an opcode name and argument count.

    `DEBUG_PUT_MSG` takes its count from the arity table. A variadic opcode has
    no entry there, so `USER_FUNC 4` says the count outright.
    """
    text = raw.strip()
    if text.lower().startswith("0x"):
        return _parse_expect_word(text, raw, where)

    parts = text.split()
    opcode = evt.opcode_named(parts[0]) if parts else None
    if opcode is None or len(parts) > 2:
        raise ManifestError(_unknown_opcode(text, raw, where))
    declared = _parse_declared_count(parts[1], raw, where) if len(parts) == 2 else None

    argc = evt.argument_count(opcode)
    if argc is None:
        if declared is None:
            raise ManifestError(
                f"{where}: 'expect' is {opcode.name}, which is variadic -- it "
                f"declares its own argument count, so bleck cannot infer the "
                f"instruction's size.\n"
                f'  Say how many: "expect": "{opcode.name} 4".\n'
                f"  Counting: USER_FUNC's first argument is the function "
                f"pointer, so `USER_FUNC f, a, b, c` declares 4."
            )
        argc = declared
    elif declared is not None and declared != argc:
        raise ManifestError(
            f"{where}: 'expect' is {raw!r}, but {opcode.name} always takes "
            f"{argc} argument(s), not {declared}.\n"
            f"  Drop the count, or give the header word directly."
        )
    _check_room_for_pointer(argc, raw, where)
    return evt.instruction_header(opcode, argc)


def _parse_expect_word(text: str, raw: str, where: str) -> int:
    try:
        word = int(text, 16)
    except ValueError:
        raise ManifestError(
            f"{where}: 'expect' is {raw!r}, which is neither an opcode name "
            f"nor a hexadecimal header word like '0x00010072'"
        ) from None
    if not 0 <= word <= 0xFFFFFFFF:
        raise ManifestError(f"{where}: 'expect' {raw!r} is not a 32-bit word")
    _check_room_for_pointer(word >> 16, raw, where)
    return word


def _parse_declared_count(text: str, raw: str, where: str) -> int:
    try:
        return int(text, 0)
    except ValueError:
        raise ManifestError(
            f"{where}: 'expect' is {raw!r}; the part after the opcode name is "
            f'its argument count, e.g. "USER_FUNC 4"'
        ) from None


def _unknown_opcode(name: str, raw: str, where: str) -> str:
    names = [op.name for op in evt.Opcode]
    close = difflib.get_close_matches(name.upper(), names, n=1, cutoff=0.6)
    hint = (
        f"\n  Did you mean {close[0]!r}?"
        if close
        else "\n  Names come from spm/evtmgr_cmd.h, such as 'DEBUG_PUT_MSG'."
    )
    return (
        f"{where}: 'expect' is {raw!r}, which names no evt opcode.{hint}\n"
        f'  Write an opcode name, optionally with its argument count ("USER_FUNC '
        f'4"), or the header word directly ("0x00010072").'
    )


def _check_room_for_pointer(argc: int, raw: str, where: str) -> None:
    """Refuse a one-word instruction: the pointer to `call` has nowhere to go."""
    if argc >= MIN_ARGUMENT_COUNT:
        return
    raise ManifestError(
        f"{where}: 'expect' is {raw!r}, which declares no arguments and so is "
        f"one word. The replacement is a USER_FUNC header plus the pointer to "
        f"'call', which needs two words at least -- there is no room for the "
        f"pointer.\n{_SAME_SIZE_ONLY}\n"
        f"  Pick an instruction of two words or more."
    )
