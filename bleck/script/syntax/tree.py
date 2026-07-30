"""The abstract syntax tree.

Every node is a frozen dataclass carrying its `Position`, so an error found
passes later can still point at the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bleck.script.errors import Position


@dataclass(frozen=True)
class Node:
    """Base for everything in the tree."""

    position: Position = field(default_factory=Position)


# --- expressions ----------------------------------------------------------


@dataclass(frozen=True)
class Expression(Node):
    """A value-producing node."""


@dataclass(frozen=True)
class IntLiteral(Expression):
    value: int = 0


@dataclass(frozen=True)
class FloatLiteral(Expression):
    value: float = 0.0


@dataclass(frozen=True)
class StringLiteral(Expression):
    value: str = ""


@dataclass(frozen=True)
class BoolLiteral(Expression):
    value: bool = False


@dataclass(frozen=True)
class Name(Expression):
    """A reference to a variable, or to a bare game symbol."""

    text: str = ""


@dataclass(frozen=True)
class Binary(Expression):
    """An infix operation. `operator` is the source spelling."""

    operator: str = ""
    left: Expression | None = None
    right: Expression | None = None


@dataclass(frozen=True)
class Unary(Expression):
    operator: str = ""
    operand: Expression | None = None


@dataclass(frozen=True)
class Call(Expression):
    """A call to a game function, resolved by name at REL-link time.

    The compiler emits a C reference to `callee`; `elf2rel` binds it through the
    symbol list, so no game address ever appears in `bleck`.
    """

    callee: str = ""
    arguments: list[Expression] = field(default_factory=list)


@dataclass(frozen=True)
class SlotRef(Expression):
    """An explicit storage slot, e.g. `gw[3]` or `gsw[120]` — the escape hatch
    for reading and writing the game's own variables."""

    storage: str = ""
    index: int = 0


# --- statements -----------------------------------------------------------


@dataclass(frozen=True)
class Statement(Node):
    """A node executed for its effect."""


@dataclass(frozen=True)
class VarDecl(Statement):
    name: str = ""
    value: Expression | None = None


@dataclass(frozen=True)
class Assign(Statement):
    target: Expression | None = None
    value: Expression | None = None


@dataclass(frozen=True)
class If(Statement):
    condition: Expression | None = None
    then_body: list[Statement] = field(default_factory=list)
    else_body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class While(Statement):
    condition: Expression | None = None
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class Loop(Statement):
    """A counted loop. A `count` of None repeats forever."""

    count: Expression | None = None
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class SwitchCase(Node):
    """One `case` arm. Several `alternatives` mean a comma-separated OR list."""

    operator: str = "=="
    alternatives: list[Expression] = field(default_factory=list)
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class Switch(Statement):
    """A `switch` over one subject. `has_else` distinguishes an empty `else`
    body from no `else` at all."""

    subject: Expression | None = None
    cases: list[SwitchCase] = field(default_factory=list)
    else_body: list[Statement] = field(default_factory=list)
    has_else: bool = False


@dataclass(frozen=True)
class Break(Statement):
    pass


@dataclass(frozen=True)
class Continue(Statement):
    pass


@dataclass(frozen=True)
class Return(Statement):
    pass


@dataclass(frozen=True)
class Wait(Statement):
    """Yield for a duration. `milliseconds` picks WAIT_MSEC over WAIT_FRM."""

    duration: Expression | None = None
    milliseconds: bool = False


@dataclass(frozen=True)
class ExpressionStatement(Statement):
    """A call evaluated for its side effect."""

    expression: Expression | None = None


@dataclass(frozen=True)
class ScriptRef(Expression):
    """`script <name>` -- the ADDRESS of another script in this source.

    ⚠️ Not a call and not a spawn. Some game builtins take an `EvtScriptCode *`
    and store it for later: `evt_door_set_event(door, which, script)` attaches
    one to a loading zone (D143). Without this there was no way to name a
    compiled script as a *value*, so those builtins were unreachable from a
    script even though the catalog lists them.
    """

    name: str = ""


@dataclass(frozen=True)
class Spawn(Statement):
    """Start another script as a child of this one."""

    name: str = ""
    detached: bool = False
    """Run independently rather than as a child that the parent waits on."""


# --- top level ------------------------------------------------------------


@dataclass(frozen=True)
class Script(Node):
    """One named script: the unit the game's scheduler runs."""

    name: str = ""
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class Program(Node):
    """Everything parsed out of one source file."""

    scripts: list[Script] = field(default_factory=list)
