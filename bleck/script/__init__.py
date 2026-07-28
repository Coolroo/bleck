"""A small scripting language that compiles to the game's own `evt` VM.

The pipeline::

    source text
      -> lexer.tokenize    tokens with positions
      -> parser.parse      a syntax.Program
      -> compiler          evt bytecode, addresses still symbolic
      -> emit.generate     one C translation unit
      -> the REL toolchain devkitPPC, then pyelf2rel

Language reference and design notes: `docs/scripting.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

from bleck.script import compiler, emit, evt, syntax
from bleck.script.errors import Position, ScriptError
from bleck.script.syntax import parser

__all__ = [
    "CompiledSource",
    "Position",
    "ScriptError",
    "compile_source",
    "compiler",
    "emit",
    "evt",
    "parser",
    "syntax",
]


@dataclass(frozen=True)
class CompiledSource:
    """The result of taking one script file all the way to C."""

    origin: str
    generated: emit.GeneratedSource
    program: compiler.CompiledProgram

    @property
    def script_names(self) -> list[str]:
        return [script.name for script in self.program.scripts]

    @property
    def word_count(self) -> int:
        return sum(len(script.words) for script in self.program.scripts)

    def summary(self) -> str:
        scripts = ", ".join(self.script_names)
        return (
            f"{len(self.program.scripts)} script(s) [{scripts}], "
            f"{self.word_count} bytecode words, "
            f"{len(self.program.called_symbols)} game function(s) called"
        )


def compile_source(
    text: str,
    origin: str = "script",
    *,
    scaffolding: emit.Scaffolding | None = None,
    symbol_table=None,
) -> CompiledSource:
    """Compile script text to C.

    `scaffolding` says what the module does besides run its entry script — map
    hooks, a boot map, the on-screen banner. Calls are checked against
    `symbol_table` so link failures are reported here, not after a toolchain
    run (D61). Raises `ScriptError` with a source position.
    """
    tree = parser.parse(text)
    program = compiler.compile_program(tree, text, symbol_table=symbol_table)
    generated = emit.generate(program, origin=origin, scaffolding=scaffolding)
    return CompiledSource(origin=origin, generated=generated, program=program)
