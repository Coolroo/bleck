"""The front end: source text to a syntax tree.

`lexer` produces tokens, `parser` produces the tree, and `tree` is the tree's
own vocabulary. Nothing here knows what `evt` is — that separation is what lets
the language be checked without a game version selected.
"""

from bleck.script.syntax.lexer import Token, TokenKind, tokenize
from bleck.script.syntax.parser import parse

__all__ = ["Token", "TokenKind", "parse", "tokenize"]
