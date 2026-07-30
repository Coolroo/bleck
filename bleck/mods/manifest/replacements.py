"""`code.replace` — a vanilla script swapped out **whole**, by pointer.

`code.patches` overwrites one instruction in place, which is why it is limited to
same-size replacement: it is the only mutation that moves no jump-table label
(`jumptable[]` is cached per `EvtEntry`, D87/D91). Writing a *different pointer*
into the field instead lifts that limit entirely — the replacement is built whole,
so nothing moves and there is no jump table to rebuild.

✅ **Measured** (D146): a door's `interactScript` pointer was swapped and the
replacement ran **63 times** for one door use — the game's own calls, separated
from the harness by a self-test that only fires past frame 600 — and the map
still reached its destination.

⛔ **Doors only, and that is an evidence boundary rather than a shortcut** — see
`UNPROVEN_FOR` for why each other selector kind is refused by name.
"""

from __future__ import annotations

from dataclasses import dataclass

from bleck.mods.errors import ManifestError
from bleck.script import emit

from .opcodes import parse_expect
from .selectors import PatchKind, parse_selector

#: Why a pointer swap is refused for every selector kind except `door:`.
#:
#: Each entry is a *measured* or *reasoned* obstacle, not an unimplemented case,
#: so the message says which. The project's rule is to refuse rather than emit
#: something whose failure mode is a frozen game.
UNPROVEN_FOR: dict[PatchKind, str] = {
    PatchKind.MAP: (
        "⛔ Swapping `MapData.initScript` is KNOWN TO FAIL: D51 did exactly "
        "this, every mechanical check passed, and the map froze mid-load. The "
        "map loader appears to wait on the specific EvtEntry it created from "
        "that pointer, which a replacement never satisfies. Use "
        "`code.patches` for a map init script, or `code.maps` to run "
        "alongside it."
    ),
    PatchKind.ITEM: (
        "🔶 Unproven for item use scripts. `itemEventDataTable` is static, so "
        "the swap is plausible, but nothing has measured it -- and several "
        "item scripts are SHARED between ids (D91), so a swap would silently "
        "change every id that shares one. Use `code.patches` instead."
    ),
    PatchKind.NPC: (
        "🔶 Unproven for enemy behaviour scripts. `npcEnemyTemplates` is "
        "static and its scripts are SHARED between templates (D112), so a "
        "swap would affect every template sharing one. Use `code.patches`."
    ),
}


@dataclass(frozen=True)
class ScriptReplacement:
    """One vanilla script field repointed at a script this mod compiled.

    The mod's script is emitted as `evt` bytecode in the module's own data, so
    its address is a link-time constant; the swap is a single store at
    `_prolog`. ✅ It persists without re-application because a `DoorDesc` array
    is **static data** -- the init script carries the array's address as a
    literal argument, so it is not rebuilt per map entry (D146).
    """

    target: str
    """The selector's target as written, e.g. `he1_01:0:interact`."""

    script: str
    """A script declared in this mod's own source, whose bytecode replaces it."""

    expect: str = ""
    """Opcode the ORIGINAL script must open with, or `""` to swap unguarded."""

    expect_word: int = 0
    """`expect` resolved to a header word. 0 means unguarded."""

    kind: PatchKind = PatchKind.DOOR
    """Always `DOOR` today. Carried so the generated table stays uniform."""

    @property
    def selector(self) -> str:
        return f"{self.kind}:{self.target}"

    @property
    def guarded(self) -> bool:
        return self.expect_word != 0

    @property
    def map_name(self) -> str:
        """The map whose init script registers the door."""
        return self.target.split(":")[0]

    @property
    def index(self) -> int:
        """Which door of that map, as a position in its registration order."""
        return int(self.target.split(":")[1], 0)

    @property
    def field_offset(self) -> int:
        """Byte offset of the chosen script field within the `DoorDesc`.

        Omitting the script name means `interact`, matching `code.patches`.
        """
        parts = self.target.split(":")
        named = parts[2] if len(parts) == 3 else emit.DoorScript.INTERACT.value
        found = emit.DoorScript.parse(named)
        if found is None:  # pragma: no cover -- parse_selector rejects these
            raise ManifestError(f"script name in {self.target!r} was never validated")
        return found.offset


def parse_replacements(raw: object, source: str) -> list[ScriptReplacement]:
    """Read `code.replace`, a list of whole-script pointer swaps."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError(
            f"{source}: 'code.replace' must be a list of replacement objects, "
            f'e.g. [{{"script": "door:he1_01:0:interact", "with": "my_door"}}]'
        )
    return [
        _parse_replacement(entry, f"{source}: 'code.replace[{i}]'")
        for i, entry in enumerate(raw)
    ]


def _parse_replacement(raw: object, where: str) -> ScriptReplacement:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be an object")
    unknown = sorted(set(raw) - {"script", "with", "expect"})
    if unknown:
        raise ManifestError(
            f"{where} has unknown field(s): {', '.join(unknown)}\n"
            f"  A replacement takes 'script', 'with' and an optional 'expect'."
        )
    for name in ("script", "with"):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ManifestError(f"{where} needs a non-empty {name!r} string")
    expect = raw.get("expect", "")
    if not isinstance(expect, str):
        raise ManifestError(
            f"{where}: 'expect' must be an opcode name or header word as a "
            f"string, not {type(expect).__name__}"
        )
    return build_replacement(str(raw["script"]), str(raw["with"]), expect, where)


def build_replacement(
    script: str, with_script: str, expect: str, where: str
) -> ScriptReplacement:
    """Validate one replacement and resolve `expect`.

    Shared with the JSON API so both surfaces refuse the same things.
    """
    selector = parse_selector(script, where)
    if selector.kind is not PatchKind.DOOR:
        raise ManifestError(
            f"{where}: 'script' is {script!r}, and a whole-script pointer swap "
            f"is only supported for `door:` selectors.\n"
            f"  {UNPROVEN_FOR[selector.kind]}"
        )
    if not with_script.isidentifier():
        raise ManifestError(
            f"{where}: 'with' is {with_script!r}, which is not a script name.\n"
            f"  It names a script declared in this mod's own source, e.g. "
            f"'my_door'."
        )
    return ScriptReplacement(
        target=selector.target,
        script=with_script,
        expect=expect,
        expect_word=_resolve_expect(expect, where),
        kind=selector.kind,
    )


def _resolve_expect(expect: str, where: str) -> int:
    """Resolve the optional guard, importing the patch parser rather than
    reimplementing it -- `expect` must mean the same thing in both places.

    ⚠️ A door's `interact` script opens with **`MULF`**, not a call (D103), so a
    guessed guard is the common mistake. An empty `expect` is honest about being
    unguarded rather than guarding against a guess.
    """
    if not expect.strip():
        return 0
    return parse_expect(expect, where)
