"""Pylint plugin: a run of `#` comment lines may be at most 3 lines.

Long explanations belong in `docs/`, which is the project's durable record and is
where a reader looks for reasoning. A twelve-line block above a function is read
once, drifts out of date silently, and cannot be linked to.

Counts *consecutive* comment lines, so three separate two-line comments are fine
and one seven-line wall is not. A blank line or any code ends the run.

Escape hatch: `# pylint: disable=comment-too-long`, for a block that genuinely
has to sit with the code — a measured memory layout, or a table whose columns
need naming.
"""

from __future__ import annotations

import tokenize
from io import BytesIO
from typing import TYPE_CHECKING, ClassVar

from pylint.checkers import BaseRawFileChecker

if TYPE_CHECKING:
    from pylint.lint import PyLinter

#: Consecutive `#` lines allowed before the block is reported.
MAX_COMMENT_LINES = 3

#: Comment prefixes that are documentation of the *next* declaration rather than
#: prose, and are exempt. `#:` is the Sphinx attribute-docstring form and this
#: codebase uses it as the documented way to describe a module constant -- a cap
#: there would just push the same text into a worse place.
EXEMPT_PREFIXES = ("#:",)

#: Machine directives, which are instructions to a tool rather than prose. They
#: are not counted at all: a `# pylint: disable` sitting inside a comment block
#: is not what makes the block hard to read, and counting it would push authors
#: into deleting explanation to make room for a directive.
DIRECTIVE_PREFIXES = (
    "# pylint:",
    "# noqa",
    "# type:",
    "# fmt:",
    "# ruff:",
    "# pragma:",
    "# isort:",
)


class CommentLengthChecker(BaseRawFileChecker):
    """Reports any run of more than `MAX_COMMENT_LINES` comment lines."""

    name = "comment-length"
    msgs: ClassVar[dict] = {
        "C9003": (
            "Comment block is %d lines (at most %d); move the explanation to docs/",
            "comment-too-long",
            "A long comment block in code cannot be linked to, is read once, "
            "and goes stale silently. Put the reasoning in docs/ -- the "
            "decision log or a topic doc -- and leave a short pointer here.",
        ),
    }
    options = (
        (
            "max-comment-lines",
            {
                "default": MAX_COMMENT_LINES,
                "type": "int",
                "metavar": "<int>",
                "help": "Maximum consecutive # comment lines before C9003.",
            },
        ),
    )

    def process_module(self, node) -> None:
        limit = self.linter.config.max_comment_lines
        with node.stream() as stream:
            source = stream.read()
        for start, length in _comment_runs(source):
            if length > limit:
                self.add_message("comment-too-long", line=start, args=(length, limit))


def _comment_runs(source: bytes) -> list[tuple[int, int]]:
    """Every consecutive comment run, as `(first line, how many lines)`.

    ⚠️ Uses `tokenize` rather than counting lines that start with `#`, so a `#`
    inside a string literal is not mistaken for a comment.
    """
    # pylint: disable=container-return  # a token span is a position, not a record
    runs: list[tuple[int, int]] = []
    start = 0
    length = 0
    exempt = False

    def flush() -> None:
        nonlocal length, exempt
        if length and not exempt:
            runs.append((start, length))
        length = 0
        exempt = False

    try:
        tokens = list(tokenize.tokenize(BytesIO(source).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        # An unparseable file is pylint's problem to report, not this checker's.
        return runs

    previous_line = 0
    for token in tokens:
        if token.type == tokenize.COMMENT:
            text = token.string.strip()
            if text.startswith(DIRECTIVE_PREFIXES):
                previous_line = token.start[0]
                continue
            # A blank line between comments ends the run: two short blocks are
            # two blocks, and joining them would report a wall that is not there.
            if length and token.start[0] > previous_line + 1:
                flush()
            if not length:
                start = token.start[0]
            if text.startswith(EXEMPT_PREFIXES):
                exempt = True
            length += 1
            previous_line = token.start[0]
        elif token.type in (tokenize.NL, tokenize.NEWLINE) or token.type in (
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENCODING,
        ):
            continue
        else:
            flush()
    flush()
    return runs


def register(linter: PyLinter) -> None:
    linter.register_checker(CommentLengthChecker(linter))
