"""Pylint plugin: confine environment access to `bleck.common.env`, where each
variable is declared once. Flags `os.environ`, `os.getenv`, `os.putenv` and
`os.unsetenv` elsewhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from astroid import nodes
from pylint.checkers import BaseChecker

if TYPE_CHECKING:
    from pylint.lint import PyLinter

# Only this module may touch the environment.
ALLOWED_MODULES = frozenset({"bleck.common.env"})

FORBIDDEN_ATTRIBUTES = frozenset({"environ", "environb"})
FORBIDDEN_FUNCTIONS = frozenset({"getenv", "putenv", "unsetenv"})


class EnvAccessChecker(BaseChecker):
    """Rejects direct environment access outside `bleck.common.env`."""

    name = "env-access"
    msgs: ClassVar[dict] = {
        "C9002": (
            "Direct environment access (%s); declare it in bleck.common.env instead",
            "direct-env-access",
            "Environment variables must be declared in bleck/common/env.py so "
            "the full set is discoverable and names are not duplicated.",
        ),
    }

    def _allowed(self, node: nodes.NodeNG) -> bool:
        module = node.root()
        return getattr(module, "name", "") in ALLOWED_MODULES

    def visit_attribute(self, node: nodes.Attribute) -> None:
        """Catch `os.environ`, `os.getenv(...)`, and friends."""
        if node.attrname not in FORBIDDEN_ATTRIBUTES | FORBIDDEN_FUNCTIONS:
            return
        if not _is_os(node.expr):
            return
        if self._allowed(node):
            return
        self.add_message("direct-env-access", node=node, args=(f"os.{node.attrname}",))

    def visit_importfrom(self, node: nodes.ImportFrom) -> None:
        """Catch `from os import environ, getenv`."""
        if node.modname != "os":
            return
        if self._allowed(node):
            return
        for name, _alias in node.names:
            if name in FORBIDDEN_ATTRIBUTES | FORBIDDEN_FUNCTIONS:
                self.add_message(
                    "direct-env-access", node=node, args=(f"from os import {name}",)
                )


def _is_os(node: nodes.NodeNG) -> bool:
    """Whether an expression refers to the `os` module."""
    return isinstance(node, nodes.Name) and node.name == "os"


def register(linter: PyLinter) -> None:
    linter.register_checker(EnvAccessChecker(linter))
