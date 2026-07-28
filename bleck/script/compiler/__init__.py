"""Lowering a syntax tree onto `evt` bytecode.

`lower` does the work; `ir` is what it produces and what `emit` depends on.
"""

from bleck.script.compiler.ir import (
    ARITHMETIC,
    CASE_OPCODES,
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
    "CASE_OPCODES",
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
