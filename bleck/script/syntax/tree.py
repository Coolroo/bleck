"""The abstract syntax tree.

Named `syntax` rather than `ast` so it can never be confused with the standard
library module of that name.

Every node is a frozen dataclass carrying its `Position`, because a compile
error found three passes later still has to point at the source the author
wrote.
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
    """A call to a game function.

    Resolved by name at REL-link time, never by address here: the compiler emits
    a C reference to `callee` and lets `elf2rel` bind it through the symbol list.
    That is what keeps game addresses out of `bleck` entirely.
    """

    callee: str = ""
    arguments: list[Expression] = field(default_factory=list)


@dataclass(frozen=True)
class SlotRef(Expression):
    """An explicit storage slot, e.g. `gw[3]` or `gsw[120]`.

    The escape hatch for talking to the game's own variables, which is how a
    script observes progression state it did not set itself.
    """

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
    """Yield for a duration. `milliseconds` picks WAIT_MSEC over WAIT_FRM.

    This is the whole reason scripts are pleasant to write for a 60fps game:
    the VM resumes the script where it left off, so waiting does not block the
    frame the way it would in a native hook.
    """

    duration: Expression | None = None
    milliseconds: bool = False


@dataclass(frozen=True)
class ExpressionStatement(Statement):
    """A call evaluated for its side effect."""

    expression: Expression | None = None


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
