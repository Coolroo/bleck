"""Recursive-descent parser: tokens to a `Program`.

The grammar is deliberately small. Every construct here has to survive being
lowered onto `evt`, a VM with two-operand instructions and no expression stack,
so syntax that would imply arbitrary nesting depth at runtime is not offered.
What is offered maps down cleanly — see `compiler.py`.
"""

from __future__ import annotations

from bleck.script.errors import Position, ScriptError
from bleck.script.evt import STORAGE_CLASSES
from bleck.script.syntax import tree
from bleck.script.syntax.lexer import Token, TokenKind, tokenize

#: Binding power for infix operators. Higher binds tighter.
_PRECEDENCE = {
    "or": 1,
    "||": 1,
    "and": 2,
    "&&": 2,
    "==": 3,
    "!=": 3,
    "<": 4,
    ">": 4,
    "<=": 4,
    ">=": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
    "%": 6,
}

_STORAGE_NAMES = {storage.name.lower() for storage in STORAGE_CLASSES}

#: Statements that are a single keyword and nothing else.
_KEYWORD_ONLY_STATEMENTS = {
    "break": tree.Break,
    "continue": tree.Continue,
    "return": tree.Return,
}


class _Parser:  # pylint: disable=too-many-public-methods
    """Token cursor with the usual expect/accept helpers.

    The method count is high by design: a recursive-descent parser has roughly
    one method per grammar production, and collapsing them would trade a long
    class for a long function.
    """

    def __init__(self, tokens: list[Token], source: str) -> None:
        self.tokens = tokens
        self.source = source
        self.index = 0
        # Statement dispatch as data, so `parse_statement` stays a lookup rather
        # than a ladder of keyword tests that grows with the language.
        self.compound_statements = {
            "var": self.parse_var,
            "if": self.parse_if,
            "while": self.parse_while,
            "loop": self.parse_loop,
            "wait": self.parse_wait,
            "wait_ms": self.parse_wait,
            "spawn": self.parse_spawn,
        }

    # --- cursor ----------------------------------------------------------

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        if token.kind is not TokenKind.END:
            self.index += 1
        return token

    def fail(self, message: str, token: Token | None = None) -> ScriptError:
        at = token or self.current
        return ScriptError(message, at.position, self.source)

    def accept_op(self, *candidates: str) -> Token | None:
        if self.current.is_op(*candidates):
            return self.advance()
        return None

    def accept_keyword(self, *candidates: str) -> Token | None:
        if self.current.is_keyword(*candidates):
            return self.advance()
        return None

    def expect_op(self, text: str) -> Token:
        if not self.current.is_op(text):
            raise self.fail(f"expected {text!r}, found {self.current}")
        return self.advance()

    def expect_ident(self, what: str) -> Token:
        if self.current.kind is not TokenKind.IDENT:
            raise self.fail(f"expected {what}, found {self.current}")
        return self.advance()

    def skip_newlines(self) -> None:
        while self.current.kind is TokenKind.NEWLINE:
            self.advance()

    def end_statement(self) -> None:
        """Consume the line break that terminates a statement."""
        if self.current.kind in (TokenKind.NEWLINE, TokenKind.END):
            self.skip_newlines()
            return
        # A closing brace ends the last statement in a block without needing a
        # line of its own, so `{ wait(1) }` on one line is legal.
        if self.current.is_op("}"):
            return
        raise self.fail(f"unexpected {self.current} after statement")

    # --- top level -------------------------------------------------------

    def parse_program(self) -> tree.Program:
        scripts: list[tree.Script] = []
        self.skip_newlines()
        while self.current.kind is not TokenKind.END:
            scripts.append(self.parse_script())
            self.skip_newlines()
        if not scripts:
            raise self.fail("this file declares no scripts")
        self._reject_duplicate_scripts(scripts)
        return tree.Program(scripts=scripts)

    def _reject_duplicate_scripts(self, scripts: list[tree.Script]) -> None:
        seen: dict[str, Position] = {}
        for script in scripts:
            if script.name in seen:
                raise ScriptError(
                    f"script {script.name!r} is declared twice "
                    f"(first at line {seen[script.name].line})",
                    script.position,
                    self.source,
                )
            seen[script.name] = script.position

    def parse_script(self) -> tree.Script:
        keyword = self.accept_keyword("script")
        if keyword is None:
            raise self.fail(
                f"expected 'script', found {self.current}; "
                "every statement must live inside a script block"
            )
        name = self.expect_ident("a script name")
        body = self.parse_block()
        return tree.Script(position=keyword.position, name=name.text, body=body)

    def parse_block(self) -> list[tree.Statement]:
        self.skip_newlines()
        self.expect_op("{")
        statements: list[tree.Statement] = []
        self.skip_newlines()
        while not self.current.is_op("}"):
            if self.current.kind is TokenKind.END:
                raise self.fail("unclosed '{'")
            statements.append(self.parse_statement())
            self.skip_newlines()
        self.expect_op("}")
        return statements

    # --- statements ------------------------------------------------------

    def parse_statement(self) -> tree.Statement:
        token = self.current
        if token.kind is not TokenKind.KEYWORD:
            return self.parse_assignment_or_call()

        keywordless = _KEYWORD_ONLY_STATEMENTS.get(token.text)
        if keywordless is not None:
            self.advance()
            self.end_statement()
            return keywordless(position=token.position)

        compound = self.compound_statements.get(token.text)
        if compound is not None:
            return compound()

        return self.parse_assignment_or_call()

    def parse_var(self) -> tree.VarDecl:
        keyword = self.advance()
        name = self.expect_ident("a variable name")
        value: tree.Expression | None = None
        if self.accept_op("="):
            value = self.parse_expression()
        self.end_statement()
        return tree.VarDecl(position=keyword.position, name=name.text, value=value)

    def parse_if(self) -> tree.If:
        keyword = self.advance()
        condition = self.parse_expression()
        then_body = self.parse_block()
        else_body: list[tree.Statement] = []

        # `else` may legally sit on the line after the closing brace.
        saved = self.index
        self.skip_newlines()
        if self.accept_keyword("else"):
            if self.current.is_keyword("if"):
                else_body = [self.parse_if()]
            else:
                else_body = self.parse_block()
                self.end_statement()
        else:
            self.index = saved

        return tree.If(
            position=keyword.position,
            condition=condition,
            then_body=then_body,
            else_body=else_body,
        )

    def parse_while(self) -> tree.While:
        keyword = self.advance()
        condition = self.parse_expression()
        body = self.parse_block()
        return tree.While(position=keyword.position, condition=condition, body=body)

    def parse_loop(self) -> tree.Loop:
        keyword = self.advance()
        count: tree.Expression | None = None
        if not self.current.is_op("{"):
            count = self.parse_expression()
        body = self.parse_block()
        return tree.Loop(position=keyword.position, count=count, body=body)

    def parse_wait(self) -> tree.Wait:
        keyword = self.advance()
        self.expect_op("(")
        duration = self.parse_expression()
        self.expect_op(")")
        self.end_statement()
        return tree.Wait(
            position=keyword.position,
            duration=duration,
            milliseconds=keyword.text == "wait_ms",
        )

    def parse_spawn(self) -> tree.Spawn:
        keyword = self.advance()
        name = self.expect_ident("a script name")
        self.end_statement()
        return tree.Spawn(position=keyword.position, name=name.text)

    def parse_assignment_or_call(self) -> tree.Statement:
        start = self.current
        target = self.parse_expression()

        if self.accept_op("="):
            value = self.parse_expression()
            self.end_statement()
            if not isinstance(target, (tree.Name, tree.SlotRef)):
                raise self.fail("cannot assign to this expression", start)
            return tree.Assign(position=start.position, target=target, value=value)

        self.end_statement()
        if not isinstance(target, tree.Call):
            raise self.fail(
                "this expression has no effect; "
                "did you mean to call a function or assign to a variable?",
                start,
            )
        return tree.ExpressionStatement(position=start.position, expression=target)

    # --- expressions -----------------------------------------------------

    def parse_expression(self, minimum: int = 0) -> tree.Expression:
        """Precedence climbing over `_PRECEDENCE`."""
        left = self.parse_unary()

        while True:
            token = self.current
            spelling = token.text
            is_infix = (
                token.kind is TokenKind.OPERATOR or token.kind is TokenKind.KEYWORD
            ) and spelling in _PRECEDENCE
            if not is_infix:
                return left

            precedence = _PRECEDENCE[spelling]
            if precedence < minimum:
                return left

            self.advance()
            # Every operator here is left-associative, so the right operand is
            # parsed at one level tighter.
            right = self.parse_expression(precedence + 1)
            left = tree.Binary(
                position=token.position,
                operator=_canonical_operator(spelling),
                left=left,
                right=right,
            )

    def parse_unary(self) -> tree.Expression:
        token = self.current
        if token.is_keyword("not") or token.is_op("-"):
            self.advance()
            operand = self.parse_unary()
            operator = "not" if token.is_keyword("not") else "-"
            return tree.Unary(position=token.position, operator=operator, operand=operand)
        return self.parse_primary()

    def parse_primary(self) -> tree.Expression:
        token = self.advance()

        if token.kind is TokenKind.INT:
            return tree.IntLiteral(position=token.position, value=int(token.text))
        if token.kind is TokenKind.FLOAT:
            return tree.FloatLiteral(position=token.position, value=float(token.text))
        if token.kind is TokenKind.STRING:
            return tree.StringLiteral(position=token.position, value=token.text)
        if token.is_keyword("true", "false"):
            return tree.BoolLiteral(position=token.position, value=token.text == "true")
        if token.is_op("("):
            inner = self.parse_expression()
            self.expect_op(")")
            return inner
        if token.kind is TokenKind.IDENT:
            return self.parse_after_identifier(token)

        raise self.fail(f"expected a value, found {token}", token)

    def parse_after_identifier(self, token: Token) -> tree.Expression:
        """An identifier may start a slot reference, a call, or a plain name."""
        lowered = token.text.lower()

        if lowered in _STORAGE_NAMES and self.current.is_op("["):
            self.advance()
            index_token = self.current
            if index_token.kind is not TokenKind.INT:
                raise self.fail(
                    f"{lowered}[...] needs a constant slot number", index_token
                )
            self.advance()
            self.expect_op("]")
            return tree.SlotRef(
                position=token.position,
                storage=lowered,
                index=int(index_token.text),
            )

        if self.current.is_op("("):
            self.advance()
            arguments = self.parse_arguments()
            return tree.Call(
                position=token.position, callee=token.text, arguments=arguments
            )

        return tree.Name(position=token.position, text=token.text)

    def parse_arguments(self) -> list[tree.Expression]:
        arguments: list[tree.Expression] = []
        self.skip_newlines()
        if self.accept_op(")"):
            return arguments
        while True:
            self.skip_newlines()
            arguments.append(self.parse_expression())
            self.skip_newlines()
            if self.accept_op(","):
                continue
            self.expect_op(")")
            return arguments


def _canonical_operator(spelling: str) -> str:
    """Fold the two accepted spellings of the boolean operators into one.

    `and`/`&&` and `or`/`||` are both allowed at the surface so neither the Lua
    reflex nor the C reflex is wrong; the tree only ever sees the word form.
    """
    if spelling == "&&":
        return "and"
    if spelling == "||":
        return "or"
    return spelling


def parse(source: str) -> tree.Program:
    """Parse script source into a `Program`."""
    return _Parser(tokenize(source), source).parse_program()
