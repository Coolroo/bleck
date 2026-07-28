"""The intermediate representation a compiled script is made of.

A script is a list of `Word`s rather than integers because three kinds of value
— game functions, string constants and other scripts — are addresses that only
exist after linking. They stay symbolic, and `emit` writes them as C
expressions, so no game address ever appears in `bleck`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from bleck.script import evt
from bleck.script.errors import Position, ScriptError

#: Local work slots per script. Variables allocate upward from 0, scratch
#: downward from 15; meeting in the middle is a compile error.
LOCAL_SLOTS = 16


class ValueType(Enum):
    """What kind of thing an expression produced.

    `evt` has separate int and float instructions and no coercion, so picking
    the wrong opcode reinterprets the operand's bits.
    """

    INT = auto()
    FLOAT = auto()
    STRING = auto()

    def __str__(self) -> str:
        return self.name.lower()


# --- words ----------------------------------------------------------------


@dataclass(frozen=True)
class Word:
    """One `s32` in a compiled script."""


@dataclass(frozen=True)
class Literal(Word):
    """A value known at compile time."""

    value: int


@dataclass(frozen=True)
class SymbolWord(Word):
    """The address of a game function, resolved by name at link time."""

    name: str


@dataclass(frozen=True)
class StringWord(Word):
    """The address of a string constant in the generated module."""

    index: int


@dataclass(frozen=True)
class ScriptWord(Word):
    """The address of another script compiled from the same source."""

    name: str


@dataclass(frozen=True)
class Value:
    """An operand, plus what type it holds."""

    word: Word
    type: ValueType


@dataclass(frozen=True)
class CompiledScript:
    """One script, ready to emit."""

    name: str
    words: list[Word]
    slots_used: int


@dataclass(frozen=True)
class CompiledProgram:
    """Everything compiled from one source file."""

    scripts: list[CompiledScript]
    strings: list[str]
    called_symbols: list[str]
    """Game functions this program references, for reporting and validation."""


# --- comparison lowering ---------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """The `evt` opcodes implementing one comparison, per operand type."""

    integer: evt.Opcode
    floating: evt.Opcode
    inverse: str
    """Source spelling of the negated comparison."""

    def opcode(self, value_type: ValueType) -> evt.Opcode:
        return self.floating if value_type is ValueType.FLOAT else self.integer


COMPARISONS = {
    "==": Comparison(evt.Opcode.IF_EQUAL, evt.Opcode.IFF_EQUAL, "!="),
    "!=": Comparison(evt.Opcode.IF_NOT_EQUAL, evt.Opcode.IFF_NOT_EQUAL, "=="),
    "<": Comparison(evt.Opcode.IF_SMALL, evt.Opcode.IFF_SMALL, ">="),
    ">": Comparison(evt.Opcode.IF_LARGE, evt.Opcode.IFF_LARGE, "<="),
    "<=": Comparison(evt.Opcode.IF_SMALL_EQUAL, evt.Opcode.IFF_SMALL_EQUAL, ">"),
    ">=": Comparison(evt.Opcode.IF_LARGE_EQUAL, evt.Opcode.IFF_LARGE_EQUAL, "<"),
}


@dataclass(frozen=True)
class Arithmetic:
    """The `evt` opcodes implementing one arithmetic operator."""

    integer: evt.Opcode
    floating: evt.Opcode | None

    def opcode(self, value_type: ValueType, operator: str, at: Position) -> evt.Opcode:
        if value_type is not ValueType.FLOAT:
            return self.integer
        if self.floating is None:
            raise ScriptError(
                f"'{operator}' has no float form in evt; convert to an integer first",
                at,
            )
        return self.floating


ARITHMETIC = {
    "+": Arithmetic(evt.Opcode.ADD, evt.Opcode.ADDF),
    "-": Arithmetic(evt.Opcode.SUB, evt.Opcode.SUBF),
    "*": Arithmetic(evt.Opcode.MUL, evt.Opcode.MULF),
    "/": Arithmetic(evt.Opcode.DIV, evt.Opcode.DIVF),
    "%": Arithmetic(evt.Opcode.MOD, None),
}
