"""Script diagnostics that point at a line and column.

Everything raised out of `bleck.script` carries a `Position`, and
`ScriptError.render` prints the offending line with a caret under it.
"""

from __future__ import annotations

from dataclasses import dataclass

from bleck.common.errors import BleckError


@dataclass(frozen=True)
class Position:
    """A place in a script source file. Lines and columns are 1-based."""

    line: int = 0
    column: int = 0

    def __str__(self) -> str:
        return f"{self.line}:{self.column}"


class ScriptError(BleckError):
    """A script could not be lexed, parsed, or compiled."""

    def __init__(self, message: str, position: Position, source: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.position = position
        self.source = source

    def render(self, filename: str = "") -> str:
        """The message with the offending source line and a caret beneath it."""
        where = f"{filename}:{self.position}" if filename else str(self.position)
        head = f"{where}: {self.message}"
        if not self.source or self.position.line < 1:
            return head

        lines = self.source.splitlines()
        if self.position.line > len(lines):
            return head

        text = lines[self.position.line - 1]
        gutter = f"{self.position.line} | "
        # Tabs are widened to one space so the caret lines up regardless of the
        # terminal's tab stops.
        shown = text.replace("\t", " ")
        caret = " " * (len(gutter) + max(self.position.column - 1, 0)) + "^"
        return f"{head}\n{gutter}{shown}\n{caret}"
