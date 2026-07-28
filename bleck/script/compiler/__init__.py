"""Lowering a syntax tree onto `evt` bytecode.

`lower` does the work; `ir` is what it produces. They are separate because the
IR is what everything downstream depends on — `emit` needs to know what a `Word`
is and has no business importing the thing that lowers a tree.
"""

from bleck.script.compiler.ir import (
    ARITHMETIC,
    COMPARISONS,
    LOCAL_SLOTS,
    Arithmetic,
    Comparison,
    CompiledProgram,
    CompiledScript,
    Literal,
    ScriptWord,
    StringWord,
    SymbolWord,
    Value,
    ValueType,
    Word,
)
from bleck.script.compiler.lower import compile_program

__all__ = [
    "ARITHMETIC",
    "COMPARISONS",
    "LOCAL_SLOTS",
    "Arithmetic",
    "Comparison",
    "CompiledProgram",
    "CompiledScript",
    "Literal",
    "ScriptWord",
    "StringWord",
    "SymbolWord",
    "Value",
    "ValueType",
    "Word",
    "compile_program",
]
