"""Lowering the syntax tree onto `evt` bytecode.

The interesting constraint is that `evt` is not a stack machine. There is no
expression stack and no register file — every arithmetic instruction is
two-operand and writes back into its first operand, which must be a variable.
So `x = (a + b) * c` cannot be emitted as written; it becomes a sequence of
copies and in-place operations through scratch slots.

That is what most of this module does: turn a tree into a flat sequence, renting
local-work slots for intermediate results and giving them back afterwards.

Words, not integers
-------------------
A compiled script is a list of `Word`, not a list of `int`, because three of the
values in a finished script are addresses that only exist after linking: game
functions called by `USER_FUNC`, string constants, and other scripts. Those stay
symbolic all the way through, and `emit.py` writes them as C expressions for the
linker to resolve. This is deliberate — it is what keeps game addresses out of
`bleck` entirely, so no symbol list has to be redistributed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from bleck.script import catalog as builtin_catalog
from bleck.script import evt, syntax
from bleck.script.errors import Position, ScriptError

#: `evt` gives each script 16 local work slots. Declared variables are handed
#: out from slot 0 upward and scratch from slot 15 downward; they meet in the
#: middle, and running out is a compile error rather than silent corruption.
LOCAL_SLOTS = 16


class ValueType(Enum):
    """What kind of thing an expression produced.

    `evt` has separate instructions for integer and float arithmetic, and no
    coercion between them, so this is load-bearing rather than advisory: adding
    with the wrong opcode reinterprets the operand's bits.
    """

    INT = auto()
    FLOAT = auto()
    STRING = auto()

    def __str__(self) -> str:
        return self.name.lower()


# --- words ----------------------------------------------------------------


@dataclass(frozen=True)
class Word:
    """One `s32` in a compiled script."""


@dataclass(frozen=True)
class Literal(Word):
    """A value known at compile time."""

    value: int


@dataclass(frozen=True)
class SymbolWord(Word):
    """The address of a game function, resolved by name at link time."""

    name: str


@dataclass(frozen=True)
class StringWord(Word):
    """The address of a string constant in the generated module."""

    index: int


@dataclass(frozen=True)
class ScriptWord(Word):
    """The address of another script compiled from the same source."""

    name: str


@dataclass(frozen=True)
class Value:
    """An operand, plus what type it holds."""

    word: Word
    type: ValueType


@dataclass(frozen=True)
class CompiledScript:
    """One script, ready to emit."""

    name: str
    words: list[Word]
    slots_used: int


@dataclass(frozen=True)
class CompiledProgram:
    """Everything compiled from one source file."""

    scripts: list[CompiledScript]
    strings: list[str]
    called_symbols: list[str]
    """Game functions this program references, for reporting and validation."""


# --- comparison lowering ---------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """The `evt` opcodes implementing one comparison, per operand type."""

    integer: evt.Opcode
    floating: evt.Opcode
    inverse: str
    """Source spelling of the negated comparison."""

    def opcode(self, value_type: ValueType) -> evt.Opcode:
        return self.floating if value_type is ValueType.FLOAT else self.integer


COMPARISONS = {
    "==": Comparison(evt.Opcode.IF_EQUAL, evt.Opcode.IFF_EQUAL, "!="),
    "!=": Comparison(evt.Opcode.IF_NOT_EQUAL, evt.Opcode.IFF_NOT_EQUAL, "=="),
    "<": Comparison(evt.Opcode.IF_SMALL, evt.Opcode.IFF_SMALL, ">="),
    ">": Comparison(evt.Opcode.IF_LARGE, evt.Opcode.IFF_LARGE, "<="),
    "<=": Comparison(evt.Opcode.IF_SMALL_EQUAL, evt.Opcode.IFF_SMALL_EQUAL, ">"),
    ">=": Comparison(evt.Opcode.IF_LARGE_EQUAL, evt.Opcode.IFF_LARGE_EQUAL, "<"),
}


@dataclass(frozen=True)
class Arithmetic:
    """The `evt` opcodes implementing one arithmetic operator."""

    integer: evt.Opcode
    floating: evt.Opcode | None

    def opcode(self, value_type: ValueType, operator: str, at: Position) -> evt.Opcode:
        if value_type is not ValueType.FLOAT:
            return self.integer
        if self.floating is None:
            raise ScriptError(
                f"'{operator}' has no float form in evt; convert to an integer first",
                at,
            )
        return self.floating


ARITHMETIC = {
    "+": Arithmetic(evt.Opcode.ADD, evt.Opcode.ADDF),
    "-": Arithmetic(evt.Opcode.SUB, evt.Opcode.SUBF),
    "*": Arithmetic(evt.Opcode.MUL, evt.Opcode.MULF),
    "/": Arithmetic(evt.Opcode.DIV, evt.Opcode.DIVF),
    "%": Arithmetic(evt.Opcode.MOD, None),
}

_STORAGE_BY_NAME = {storage.name.lower(): storage for storage in evt.STORAGE_CLASSES}


@dataclass
class _Variable:
    """A declared variable and the slot holding it."""

    name: str
    slot: int
    type: ValueType


class _ScriptCompiler:  # pylint: disable=too-many-public-methods
    """Compiles one `script` block.

    As with the parser, the method count tracks the size of the language rather
    than any tangling: there is roughly one method per node kind, plus the slot
    bookkeeping they all share.
    """

    def __init__(self, owner: _ProgramCompiler, script: syntax.Script) -> None:
        self.owner = owner
        self.script = script
        self.words: list[Word] = []
        self.variables: dict[str, _Variable] = {}
        self.next_slot = 0
        self.scratch_low = LOCAL_SLOTS
        self.loop_depth = 0

    # --- emission --------------------------------------------------------

    def emit(self, opcode: evt.Opcode, *arguments: Word) -> None:
        self.words.append(Literal(evt.instruction_header(opcode, len(arguments))))
        self.words.extend(arguments)

    def fail(self, message: str, at: Position) -> ScriptError:
        return ScriptError(message, at, self.owner.source)

    # --- slots -----------------------------------------------------------

    def declare(self, name: str, value_type: ValueType, at: Position) -> _Variable:
        if name in self.variables:
            raise self.fail(f"variable {name!r} is already declared", at)
        if self.next_slot >= self.scratch_low:
            raise self.fail(
                f"script {self.script.name!r} needs more than {LOCAL_SLOTS} local "
                "slots; evt provides no more. Split it into smaller scripts, or "
                "move state into gw[...] which is shared and larger",
                at,
            )
        variable = _Variable(name, self.next_slot, value_type)
        self.variables[name] = variable
        self.next_slot += 1
        return variable

    def take_scratch(self, at: Position) -> int:
        if self.scratch_low <= self.next_slot:
            raise self.fail(
                "this expression is too deeply nested to evaluate with the 16 "
                "local slots evt provides; split it across statements",
                at,
            )
        self.scratch_low -= 1
        return self.scratch_low

    def release_scratch(self, count: int) -> None:
        self.scratch_low += count

    @property
    def slots_used(self) -> int:
        return max(self.next_slot, LOCAL_SLOTS - self.scratch_low)

    def slot_word(self, slot: int) -> Word:
        return Literal(evt.LW.encode(slot))

    # --- values ----------------------------------------------------------

    def direct_value(self, node: syntax.Expression) -> Value | None:
        """A value usable as an operand without evaluating anything first."""
        folded = _fold_negation(node)
        if folded is not None:
            node = folded
        if isinstance(node, syntax.IntLiteral):
            self.reject_ambiguous_literal(node.value, node.position)
            return Value(Literal(node.value), ValueType.INT)
        if isinstance(node, syntax.BoolLiteral):
            return Value(Literal(1 if node.value else 0), ValueType.INT)
        if isinstance(node, syntax.FloatLiteral):
            return Value(Literal(self.encode_float(node)), ValueType.FLOAT)
        if isinstance(node, syntax.StringLiteral):
            return Value(StringWord(self.owner.intern(node.value)), ValueType.STRING)
        if isinstance(node, syntax.Name):
            return self.name_value(node)
        if isinstance(node, syntax.SlotRef):
            return self.slot_ref_value(node)
        return None

    def reject_ambiguous_literal(self, value: int, at: Position) -> None:
        """Refuse integers the VM would decode as a variable reference.

        `evt` recovers an operand's storage class from its numeric range, so a
        literal like -30000000 *is* `lw[0]` as far as the VM is concerned. There
        is no encoding that distinguishes them, so the only honest thing to do
        is reject the literal rather than emit something that silently reads a
        variable.
        """
        if not evt.is_literal(value):
            raise self.fail(
                f"the literal {value} collides with evt's variable encoding and "
                "would be read as a variable reference, not a number",
                at,
            )

    def encode_float(self, node: syntax.FloatLiteral) -> int:
        try:
            return evt.encode_float(node.value)
        except ValueError as exc:
            raise self.fail(str(exc), node.position) from exc

    def name_value(self, node: syntax.Name) -> Value:
        variable = self.variables.get(node.text)
        if variable is None:
            raise self.fail(
                f"{node.text!r} is not declared; "
                f"use 'var {node.text} = ...' before using it",
                node.position,
            )
        return Value(self.slot_word(variable.slot), variable.type)

    def slot_ref_value(self, node: syntax.SlotRef) -> Value:
        storage = _STORAGE_BY_NAME[node.storage]
        try:
            encoded = storage.encode(node.index)
        except ValueError as exc:
            raise self.fail(str(exc), node.position) from exc
        # Flags are booleans; everything else is read as an integer. Floats live
        # in the same work slots and are distinguished by the instruction used,
        # so a bare slot reference is typed INT and float use is explicit.
        return Value(Literal(encoded), ValueType.INT)

    def evaluate(self, node: syntax.Expression) -> Value:
        """Produce a `Value` for `node`, emitting code if it needs computing."""
        direct = self.direct_value(node)
        if direct is not None:
            return direct

        if isinstance(node, syntax.Unary):
            return self.evaluate_unary(node)
        if isinstance(node, syntax.Binary):
            return self.evaluate_binary(node)
        if isinstance(node, syntax.Call):
            raise self.fail(
                f"{node.callee}(...) cannot be used as a value; evt user "
                "functions return results through output slots, so call it on "
                "its own line and read the slot it writes",
                node.position,
            )

        raise self.fail("unsupported expression", node.position)

    def evaluate_unary(self, node: syntax.Unary) -> Value:
        assert node.operand is not None
        if node.operator == "not":
            return self.boolean_value(node)

        # Negation: 0 - operand, in a scratch slot.
        inner = self.evaluate(node.operand)
        if inner.type is ValueType.STRING:
            raise self.fail("cannot negate a string", node.position)
        slot = self.take_scratch(node.position)
        zero = (
            Literal(evt.encode_float(0.0))
            if inner.type is ValueType.FLOAT
            else Literal(0)
        )
        setter = evt.Opcode.SETF if inner.type is ValueType.FLOAT else evt.Opcode.SET
        self.emit(setter, self.slot_word(slot), zero)
        self.emit(
            ARITHMETIC["-"].opcode(inner.type, "-", node.position),
            self.slot_word(slot),
            inner.word,
        )
        return Value(self.slot_word(slot), inner.type)

    def evaluate_binary(self, node: syntax.Binary) -> Value:
        assert node.left is not None and node.right is not None

        if node.operator in COMPARISONS or node.operator in ("and", "or"):
            return self.boolean_value(node)

        operation = ARITHMETIC.get(node.operator)
        if operation is None:
            raise self.fail(f"unknown operator {node.operator!r}", node.position)

        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        result_type = self.unify(left, right, node.operator, node.position)

        # The accumulator must be a fresh slot: `evt` arithmetic writes back
        # into its first operand, so reusing `left` would clobber a variable the
        # rest of the statement still needs.
        slot = self.take_scratch(node.position)
        setter = evt.Opcode.SETF if result_type is ValueType.FLOAT else evt.Opcode.SET
        self.emit(setter, self.slot_word(slot), left.word)
        self.emit(
            operation.opcode(result_type, node.operator, node.position),
            self.slot_word(slot),
            right.word,
        )
        return Value(self.slot_word(slot), result_type)

    def unify(self, left: Value, right: Value, operator: str, at: Position) -> ValueType:
        if left.type is right.type and left.type is not ValueType.STRING:
            return left.type
        if ValueType.STRING in (left.type, right.type):
            raise self.fail(f"'{operator}' does not work on strings", at)
        raise self.fail(
            f"cannot apply '{operator}' to {left.type} and {right.type}; "
            "evt keeps integer and float arithmetic separate, so mixing them "
            "would silently reinterpret the operand",
            at,
        )

    def boolean_value(self, node: syntax.Expression) -> Value:
        """Materialise a condition as 0 or 1 in a scratch slot."""
        slot = self.take_scratch(node.position)
        self.emit(evt.Opcode.SET, self.slot_word(slot), Literal(0))
        self.branch_if(node, invert=False)
        self.emit(evt.Opcode.SET, self.slot_word(slot), Literal(1))
        self.emit(evt.Opcode.END_IF)
        return Value(self.slot_word(slot), ValueType.INT)

    # --- conditions ------------------------------------------------------

    def branch_if(self, node: syntax.Expression, invert: bool) -> None:
        """Open an `IF` that runs its body when `node` is true (or false).

        The caller is responsible for the matching `END_IF`. Comparisons lower
        straight to an `IF_*` opcode; anything else is reduced to a 0/1 value
        first and then compared against zero.
        """
        if isinstance(node, syntax.Binary) and node.operator in COMPARISONS:
            self.branch_comparison(node, invert)
            return

        if isinstance(node, syntax.Unary) and node.operator == "not":
            assert node.operand is not None
            self.branch_if(node.operand, invert=not invert)
            return

        if isinstance(node, syntax.Binary) and node.operator in ("and", "or"):
            self.branch_boolean(node, invert)
            return

        value = self.evaluate(node)
        if value.type is ValueType.STRING:
            raise self.fail("a string is not a condition", node.position)
        opcode = evt.Opcode.IF_EQUAL if invert else evt.Opcode.IF_NOT_EQUAL
        self.emit(opcode, value.word, Literal(0))

    def branch_comparison(self, node: syntax.Binary, invert: bool) -> None:
        assert node.left is not None and node.right is not None
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)

        operator = node.operator
        if left.type is ValueType.STRING or right.type is ValueType.STRING:
            self.branch_string_comparison(left, right, operator, invert, node)
            return

        value_type = self.unify(left, right, operator, node.position)
        if invert:
            operator = COMPARISONS[operator].inverse
        self.emit(COMPARISONS[operator].opcode(value_type), left.word, right.word)

    def branch_string_comparison(
        self,
        left: Value,
        right: Value,
        operator: str,
        invert: bool,
        node: syntax.Binary,
    ) -> None:
        if left.type is not right.type:
            raise self.fail(
                f"cannot compare {left.type} with {right.type}", node.position
            )
        if operator not in ("==", "!="):
            raise self.fail(
                f"strings support only '==' and '!=', not '{operator}'",
                node.position,
            )
        wanted = operator if not invert else COMPARISONS[operator].inverse
        opcode = (
            evt.Opcode.IF_STR_EQUAL if wanted == "==" else evt.Opcode.IF_STR_NOT_EQUAL
        )
        self.emit(opcode, left.word, right.word)

    def branch_boolean(self, node: syntax.Binary, invert: bool) -> None:
        """`and`/`or` via a 0/1 accumulator.

        `evt` has no short-circuit control flow, so both sides are evaluated.
        That is safe here because expressions have no side effects — calls are
        statements, not expressions.
        """
        assert node.left is not None and node.right is not None
        left = self.boolean_value(node.left)
        right = self.boolean_value(node.right)
        slot = self.take_scratch(node.position)
        self.emit(evt.Opcode.SET, self.slot_word(slot), left.word)
        combine = evt.Opcode.AND if node.operator == "and" else evt.Opcode.OR
        self.emit(combine, self.slot_word(slot), right.word)
        opcode = evt.Opcode.IF_EQUAL if invert else evt.Opcode.IF_NOT_EQUAL
        self.emit(opcode, self.slot_word(slot), Literal(0))

    # --- statements ------------------------------------------------------

    def compile_body(self, body: list[syntax.Statement]) -> None:
        for statement in body:
            # Scratch is statement-local: nothing computed for one statement is
            # readable by the next, so the slots go back into the pool.
            high_water = self.scratch_low
            self.compile_statement(statement)
            self.scratch_low = high_water

    def compile_statement(self, node: syntax.Statement) -> None:
        if isinstance(node, syntax.VarDecl):
            self.compile_var(node)
        elif isinstance(node, syntax.Assign):
            self.compile_assign(node)
        elif isinstance(node, syntax.If):
            self.compile_if(node)
        elif isinstance(node, syntax.While):
            self.compile_while(node)
        elif isinstance(node, syntax.Loop):
            self.compile_loop(node)
        elif isinstance(node, syntax.Wait):
            self.compile_wait(node)
        elif isinstance(node, syntax.Spawn):
            self.compile_spawn(node)
        elif isinstance(node, syntax.ExpressionStatement):
            self.compile_call_statement(node)
        elif isinstance(node, syntax.Break):
            self.compile_loop_jump(node, evt.Opcode.DO_BREAK, "break")
        elif isinstance(node, syntax.Continue):
            self.compile_loop_jump(node, evt.Opcode.DO_CONTINUE, "continue")
        elif isinstance(node, syntax.Return):
            self.emit(evt.Opcode.END_EVT)
        else:
            raise self.fail("unsupported statement", node.position)

    def compile_var(self, node: syntax.VarDecl) -> None:
        if node.value is None:
            variable = self.declare(node.name, ValueType.INT, node.position)
            self.emit(evt.Opcode.SET, self.slot_word(variable.slot), Literal(0))
            return

        value = self.evaluate(node.value)
        if value.type is ValueType.STRING:
            raise self.fail(
                "a variable cannot hold a string; evt work slots are 32-bit "
                "numbers. Pass the string literal directly to the call instead",
                node.position,
            )
        variable = self.declare(node.name, value.type, node.position)
        setter = evt.Opcode.SETF if value.type is ValueType.FLOAT else evt.Opcode.SET
        self.emit(setter, self.slot_word(variable.slot), value.word)

    def compile_assign(self, node: syntax.Assign) -> None:
        assert node.target is not None and node.value is not None
        value = self.evaluate(node.value)

        if isinstance(node.target, syntax.Name):
            variable = self.variables.get(node.target.text)
            if variable is None:
                raise self.fail(
                    f"{node.target.text!r} is not declared; "
                    f"use 'var {node.target.text} = ...' to introduce it",
                    node.position,
                )
            if variable.type is not value.type:
                raise self.fail(
                    f"{variable.name!r} holds {variable.type}, "
                    f"but this assigns {value.type}",
                    node.position,
                )
            target_word = self.slot_word(variable.slot)
            target_type = variable.type
        else:
            target = self.slot_ref_value(node.target)
            target_word = target.word
            target_type = value.type

        setter = evt.Opcode.SETF if target_type is ValueType.FLOAT else evt.Opcode.SET
        self.emit(setter, target_word, value.word)

    def compile_if(self, node: syntax.If) -> None:
        assert node.condition is not None
        self.branch_if(node.condition, invert=False)
        self.compile_body(node.then_body)
        if node.else_body:
            self.emit(evt.Opcode.ELSE)
            self.compile_body(node.else_body)
        self.emit(evt.Opcode.END_IF)

    def compile_while(self, node: syntax.While) -> None:
        """`while` on top of `evt`'s counted `DO`/`WHILE`.

        `evt` has no condition-tested loop, only `DO n` ... `WHILE`, which
        repeats a fixed number of times. An unbounded `DO 0` with a guarded
        `DO_BREAK` at the top reproduces `while` exactly.
        """
        assert node.condition is not None
        self.emit(evt.Opcode.DO, Literal(0))
        self.loop_depth += 1

        high_water = self.scratch_low
        self.branch_if(node.condition, invert=True)
        self.emit(evt.Opcode.DO_BREAK)
        self.emit(evt.Opcode.END_IF)
        self.scratch_low = high_water

        self.compile_body(node.body)
        self.loop_depth -= 1
        self.emit(evt.Opcode.WHILE)

    def compile_loop(self, node: syntax.Loop) -> None:
        if node.count is None:
            count: Word = Literal(0)
        else:
            value = self.evaluate(node.count)
            if value.type is not ValueType.INT:
                raise self.fail(
                    f"a loop count must be an integer, not {value.type}",
                    node.position,
                )
            count = value.word
        self.emit(evt.Opcode.DO, count)
        self.loop_depth += 1
        self.compile_body(node.body)
        self.loop_depth -= 1
        self.emit(evt.Opcode.WHILE)

    def compile_loop_jump(
        self, node: syntax.Statement, opcode: evt.Opcode, spelling: str
    ) -> None:
        if self.loop_depth == 0:
            raise self.fail(f"'{spelling}' is only valid inside a loop", node.position)
        self.emit(opcode)

    def compile_wait(self, node: syntax.Wait) -> None:
        assert node.duration is not None
        value = self.evaluate(node.duration)
        if value.type is ValueType.STRING:
            raise self.fail("a wait duration must be a number", node.position)
        opcode = evt.Opcode.WAIT_MSEC if node.milliseconds else evt.Opcode.WAIT_FRM
        self.emit(opcode, value.word)

    def compile_spawn(self, node: syntax.Spawn) -> None:
        self.owner.require_script(node.name, node.position)
        self.emit(evt.Opcode.RUN_CHILD_EVT, ScriptWord(node.name))

    def compile_call_statement(self, node: syntax.ExpressionStatement) -> None:
        call = node.expression
        if not isinstance(call, syntax.Call):
            raise self.fail("expected a call", node.position)

        self.owner.check_call(call)
        arguments = [self.evaluate(argument) for argument in call.arguments]
        self.owner.note_symbol(call.callee)
        # USER_FUNC takes the function pointer as its first argument, so the
        # declared argument count is one more than the script wrote.
        self.emit(
            evt.Opcode.USER_FUNC,
            SymbolWord(call.callee),
            *[argument.word for argument in arguments],
        )

    def compile(self) -> CompiledScript:
        self.compile_body(self.script.body)
        # Every script array ends with END_SCRIPT; the VM scans for it, so a
        # missing terminator runs off into whatever follows in memory.
        self.emit(evt.Opcode.END_SCRIPT)
        return CompiledScript(
            name=self.script.name, words=self.words, slots_used=self.slots_used
        )


class _ProgramCompiler:
    """Compiles every script in one source file."""

    def __init__(
        self,
        program: syntax.Program,
        source: str,
        catalog: builtin_catalog.Catalog | None = None,
        symbol_table=None,
    ) -> None:
        self.program = program
        self.source = source
        self.catalog = catalog if catalog is not None else builtin_catalog.load()
        #: Optional. When present, a call to a name it does not know is rejected
        #: here rather than at link time -- see `_check_linkable`.
        self.symbol_table = symbol_table
        self.strings: list[str] = []
        self.symbols: list[str] = []
        self.names = {script.name for script in program.scripts}

    def intern(self, text: str) -> int:
        if text not in self.strings:
            self.strings.append(text)
        return self.strings.index(text)

    def note_symbol(self, name: str) -> None:
        if name not in self.symbols:
            self.symbols.append(name)

    def require_script(self, name: str, at: Position) -> None:
        if name not in self.names:
            known = ", ".join(sorted(self.names)) or "none"
            raise ScriptError(
                f"no script named {name!r} in this file (declared: {known})",
                at,
                self.source,
            )

    def check_call(self, call: syntax.Call) -> None:
        """Reject a call the catalog says cannot be right.

        Both failures below are otherwise found far too late: an unknown name
        surfaces as `elf2rel`'s "Missing 1 required symbol(s)" after a compile
        and a toolchain, and a wrong argument count is not caught at all -- it
        links cleanly and misbehaves in-game.
        """
        if not self.catalog.builtins:
            return  # No catalog generated; nothing to check against.

        known = self.catalog.find(call.callee)
        if known is None:
            suggestions = self.catalog.suggest(call.callee)
            if len(suggestions) == 1:
                hint = f" Did you mean {suggestions[0]}?"
            elif suggestions:
                hint = f" Did you mean one of: {', '.join(suggestions)}?"
            else:
                hint = " Run `bleck script builtins` to see what is available."
            raise ScriptError(
                f"{call.callee!r} is not a known game function.{hint}",
                call.position,
                self.source,
            )

        self._check_linkable(call)

        if known.arity is not None and len(call.arguments) != known.arity:
            # Only show the signature when there is one; the fallback would
            # just restate the sentence above it.
            shape = f"\n  {known.signature}" if known.signature else ""
            raise ScriptError(
                f"{call.callee} takes {known.arity} argument(s), "
                f"but {len(call.arguments)} were given{shape}",
                call.position,
                self.source,
            )

    def _check_linkable(self, call: syntax.Call) -> None:
        """Reject a call that will not survive the link.

        ⚠️ **A third of the catalog is not linkable against the lst alone.** Of
        443 documented builtins, 148 are absent from `spm.eu0.lst`: 94 are in
        `spm-decomp`'s table, 21 live in the game's own REL at REL-relative
        addresses, and 33 have no known address anywhere (D61).

        All of them pass the catalog check above -- the header declares them --
        and then die at `elf2rel` with "Missing 1 required symbol(s)", after a
        compile and a toolchain run. Saying it here costs nothing and names the
        fix.
        """
        table = self.symbol_table
        if table is None or table.find(call.callee) is not None:
            return
        raise ScriptError(
            f"{call.callee} is declared in the headers but has no address in "
            f"{table.source.name}, so the module would fail to link.\n"
            f"  Some builtins live in the game's own REL, which cannot be "
            f"linked against; others are only in spm-decomp's table.\n"
            f"  Try pointing BLECK_DECOMP at a spm-decomp clone -- that covers "
            f"94 of them.",
            call.position,
            self.source,
        )

    def compile(self) -> CompiledProgram:
        scripts = [
            _ScriptCompiler(self, script).compile() for script in self.program.scripts
        ]
        return CompiledProgram(
            scripts=scripts,
            strings=list(self.strings),
            called_symbols=list(self.symbols),
        )


def _fold_negation(node: syntax.Expression) -> syntax.Expression | None:
    """Rewrite `-&lt;literal&gt;` into a negative literal.

    Without this, a negative constant becomes three instructions (set a scratch
    slot to zero, subtract, read it back) instead of one operand. It also makes
    the ambiguous-literal check reachable: a negative number is the only way to
    land in `evt`'s variable-encoding windows, and the check would otherwise
    never see one, because the parser always produces a unary minus applied to a
    positive literal.
    """
    if not isinstance(node, syntax.Unary) or node.operator != "-":
        return None
    if isinstance(node.operand, syntax.IntLiteral):
        return syntax.IntLiteral(position=node.position, value=-node.operand.value)
    if isinstance(node.operand, syntax.FloatLiteral):
        return syntax.FloatLiteral(position=node.position, value=-node.operand.value)
    return None


def compile_program(
    program: syntax.Program,
    source: str = "",
    catalog: builtin_catalog.Catalog | None = None,
    symbol_table=None,
) -> CompiledProgram:
    """Compile a parsed program to `evt` bytecode."""
    return _ProgramCompiler(program, source, catalog, symbol_table).compile()
