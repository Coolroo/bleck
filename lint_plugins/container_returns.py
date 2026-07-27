"""Pylint plugin: forbid returning bare `dict` or `tuple`.

A function returning `tuple[int, int]` tells the caller nothing about what the
two values mean, and a `dict[str, str]` return makes the key set invisible to
both readers and type checkers. Return a dataclass instead — it names the fields
and gives them a place to grow.

Containers of named things are fine: `list[Entry]` is clear, so only `dict` and
`tuple` themselves are rejected.

Escape hatch, for the rare library boundary that demands one:

    def as_kwargs(self) -> dict[str, str]:  # pylint: disable=container-return
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from astroid import nodes
from pylint.checkers import BaseChecker

if TYPE_CHECKING:
    from pylint.lint import PyLinter

FORBIDDEN = {"dict", "tuple", "Dict", "Tuple"}


class ContainerReturnChecker(BaseChecker):
    """Rejects `dict`/`tuple` anywhere in a return annotation."""

    name = "container-returns"
    msgs: ClassVar[dict] = {
        "C9001": (
            "Function %r returns %s; return a named type instead",
            "container-return",
            "Returning dict/tuple hides what the values mean. Define a small "
            "dataclass so fields are named and can be extended. This applies "
            "nested too — list[tuple[str, int]] should be list[SomeType].",
        ),
    }

    def visit_functiondef(self, node: nodes.FunctionDef) -> None:
        annotation = node.returns
        if annotation is None:
            return
        found = _find_forbidden(annotation)
        if found:
            self.add_message(
                "container-return",
                node=node,
                args=(node.name, _describe(found, annotation)),
            )

    visit_asyncfunctiondef = visit_functiondef


def _find_forbidden(annotation: nodes.NodeNG) -> str | None:
    """First forbidden type anywhere in an annotation, outermost first.

    Recurses through subscripts so `list[tuple[str, int]]` and
    `dict[str, list[Thing]]` are caught, not just bare `tuple`/`dict`. Handles
    `typing.Tuple[...]` and the string form used under
    `from __future__ import annotations`.
    """
    match annotation:
        case nodes.Subscript():
            return _find_forbidden(annotation.value) or _find_forbidden(annotation.slice)
        case nodes.Tuple() | nodes.List():
            return next(
                (
                    found
                    for element in annotation.elts
                    if (found := _find_forbidden(element))
                ),
                None,
            )
        case nodes.BinOp():  # `A | B` unions
            return _find_forbidden(annotation.left) or _find_forbidden(annotation.right)
        case nodes.Name(name=name) if name in FORBIDDEN:
            return name
        case nodes.Attribute(attrname=attr) if attr in FORBIDDEN:
            return attr
        case nodes.Const() if isinstance(annotation.value, str):
            value = annotation.value
            return next((w for w in FORBIDDEN if _mentions(value, w)), None)
    return None


def _mentions(text: str, word: str) -> bool:
    """Whether a stringified annotation names `word` as a type, not a substring."""
    for i in range(len(text)):
        if not text.startswith(word, i):
            continue
        before = text[i - 1] if i else ""
        after = text[i + len(word) :][:1]
        if before.isalnum() or before == "_":
            continue
        if after.isalnum() or after == "_":
            continue
        return True
    return False


def _describe(found: str, annotation: nodes.NodeNG) -> str:
    nested = not (
        isinstance(annotation, nodes.Name)
        or (
            isinstance(annotation, nodes.Subscript)
            and isinstance(annotation.value, nodes.Name)
            and annotation.value.name == found
        )
    )
    return f"a nested {found.lower()}" if nested else f"a bare {found.lower()}"


def register(linter: PyLinter) -> None:
    linter.register_checker(ContainerReturnChecker(linter))
