"""Turning script text into tokens, each carrying an exact source position."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from bleck.script.errors import Position, ScriptError


class TokenKind(Enum):
    """What a token is, independent of its text."""

    IDENT = auto()
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    KEYWORD = auto()
    OPERATOR = auto()
    NEWLINE = auto()
    END = auto()


KEYWORDS = frozenset(
    {
        "script",
        "var",
        "if",
        "else",
        "while",
        "loop",
        "switch",
        "case",
        "break",
        "continue",
        "return",
        "wait",
        "wait_ms",
        "spawn",
        "and",
        "or",
        "not",
        "true",
        "false",
    }
)

# Longest first: `==` must win over `=`, or `a == b` scans as two assignments.
OPERATORS = [
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "<",
    ">",
    "=",
    "+",
    "-",
    "*",
    "/",
    "%",
    "(",
    ")",
    "{",
    "}",
    "[",
    "]",
    ",",
    ".",
    ":",
]


@dataclass(frozen=True)
class Token:
    """One lexical unit and where it came from."""

    kind: TokenKind
    text: str
    position: Position

    def is_op(self, *candidates: str) -> bool:
        return self.kind is TokenKind.OPERATOR and self.text in candidates

    def is_keyword(self, *candidates: str) -> bool:
        return self.kind is TokenKind.KEYWORD and self.text in candidates

    def __str__(self) -> str:
        if self.kind is TokenKind.NEWLINE:
            return "end of line"
        if self.kind is TokenKind.END:
            return "end of file"
        return repr(self.text)


class _Scanner:
    """Cursor over the source text, tracking line and column."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.index = 0
        self.line = 1
        self.column = 1

    @property
    def done(self) -> bool:
        return self.index >= len(self.source)

    def peek(self, offset: int = 0) -> str:
        at = self.index + offset
        return self.source[at] if at < len(self.source) else ""

    def position(self) -> Position:
        return Position(self.line, self.column)

    def advance(self) -> str:
        char = self.source[self.index]
        self.index += 1
        if char == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return char

    def fail(self, message: str, position: Position) -> ScriptError:
        return ScriptError(message, position, self.source)


def tokenize(source: str) -> list[Token]:
    """Scan `source` into tokens, ending with a single `END`.

    Newlines are tokens — they terminate statements. Runs of blank lines
    collapse to one, so formatting never changes meaning.
    """
    scanner = _Scanner(source)
    tokens: list[Token] = []

    while not scanner.done:
        char = scanner.peek()

        if char == "\n":
            position = scanner.position()
            scanner.advance()
            # Collapse blank lines.
            if tokens and tokens[-1].kind is not TokenKind.NEWLINE:
                tokens.append(Token(TokenKind.NEWLINE, "\n", position))
            continue

        if char in " \t\r":
            scanner.advance()
            continue

        # `--` (SPM community style) and `//` are both accepted.
        if char == "-" and scanner.peek(1) == "-":
            _skip_line(scanner)
            continue
        if char == "/" and scanner.peek(1) == "/":
            _skip_line(scanner)
            continue
        if char == "/" and scanner.peek(1) == "*":
            _skip_block_comment(scanner)
            continue

        # `#[map("he1_04")]` -- an attribute. It addresses the manifest, not
        # the compiler, so it is skipped here and read separately by
        # `mods/manifest/code/tags.py`.
        if char == "#" and scanner.peek(1) == "[":
            _skip_line(scanner)
            continue

        if char.isdigit():
            tokens.append(_number(scanner))
            continue

        if char.isalpha() or char == "_":
            tokens.append(_word(scanner))
            continue

        if char == '"':
            tokens.append(_string(scanner))
            continue

        operator = _operator(scanner)
        if operator is not None:
            tokens.append(operator)
            continue

        position = scanner.position()
        raise scanner.fail(f"unexpected character {char!r}", position)

    tokens.append(Token(TokenKind.END, "", scanner.position()))
    return tokens


def _skip_line(scanner: _Scanner) -> None:
    while not scanner.done and scanner.peek() != "\n":
        scanner.advance()


def _skip_block_comment(scanner: _Scanner) -> None:
    opened = scanner.position()
    scanner.advance()
    scanner.advance()
    while True:
        if scanner.done:
            raise scanner.fail("unterminated /* comment", opened)
        if scanner.peek() == "*" and scanner.peek(1) == "/":
            scanner.advance()
            scanner.advance()
            return
        scanner.advance()


def _number(scanner: _Scanner) -> Token:
    position = scanner.position()
    digits = ""

    if scanner.peek() == "0" and scanner.peek(1) in "xX":
        scanner.advance()
        scanner.advance()
        while not scanner.done and (scanner.peek().isalnum() or scanner.peek() == "_"):
            digits += scanner.advance()
        if not digits:
            raise scanner.fail("'0x' needs at least one hex digit", position)
        try:
            value = int(digits.replace("_", ""), 16)
        except ValueError as exc:
            raise scanner.fail(f"bad hex literal '0x{digits}'", position) from exc
        return Token(TokenKind.INT, str(value), position)

    seen_dot = False
    while not scanner.done:
        char = scanner.peek()
        if char.isdigit() or char == "_":
            digits += scanner.advance()
            continue
        # A dot only continues the number if a digit follows, so `1.foo` scans
        # as an integer then a field access rather than a malformed float.
        if char == "." and not seen_dot and scanner.peek(1).isdigit():
            seen_dot = True
            digits += scanner.advance()
            continue
        break

    text = digits.replace("_", "")
    return Token(TokenKind.FLOAT if seen_dot else TokenKind.INT, text, position)


def _word(scanner: _Scanner) -> Token:
    position = scanner.position()
    text = ""
    while not scanner.done and (scanner.peek().isalnum() or scanner.peek() == "_"):
        text += scanner.advance()
    kind = TokenKind.KEYWORD if text in KEYWORDS else TokenKind.IDENT
    return Token(kind, text, position)


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", '"': '"', "\\": "\\"}


def _string(scanner: _Scanner) -> Token:
    position = scanner.position()
    scanner.advance()
    text = ""
    while True:
        if scanner.done:
            raise scanner.fail("unterminated string", position)
        char = scanner.advance()
        if char == '"':
            return Token(TokenKind.STRING, text, position)
        if char == "\n":
            raise scanner.fail("unterminated string", position)
        if char != "\\":
            text += char
            continue

        if scanner.done:
            raise scanner.fail("unterminated string", position)
        escape_at = scanner.position()
        code = scanner.advance()
        if code not in _ESCAPES:
            raise scanner.fail(f"unknown escape '\\{code}'", escape_at)
        text += _ESCAPES[code]


def _operator(scanner: _Scanner) -> Token | None:
    position = scanner.position()
    for candidate in OPERATORS:
        if scanner.source.startswith(candidate, scanner.index):
            for _ in candidate:
                scanner.advance()
            return Token(TokenKind.OPERATOR, candidate, position)
    return None
