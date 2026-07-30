"""Lowering the syntax tree onto `evt` bytecode.

`evt` is not a stack machine: every arithmetic instruction is two-operand and
writes back into its first operand, which must be a variable. So most of this
module flattens the tree into copies and in-place operations, renting
local-work slots for intermediates and returning them afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from bleck.script import catalog as builtin_catalog
from bleck.script import evt

# Re-exported: callers reach these through `compiler`.
from bleck.script.compiler.ir import (
    ARITHMETIC,
    CASE_OPCODES,
    COMPARISONS,
    LOCAL_SLOTS,
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
from bleck.script.errors import Position, ScriptError
from bleck.script.syntax import tree

_STORAGE_BY_NAME = {storage.name.lower(): storage for storage in evt.STORAGE_CLASSES}


@dataclass
class _Variable:
    """A declared variable and the slot holding it."""

    name: str
    slot: int
    type: ValueType


class _Block(Enum):
    """An open construct `break`/`continue` would have to jump out of."""

    LOOP = auto()
    SWITCH = auto()


class _ScriptCompiler:  # pylint: disable=too-many-public-methods
    """Compiles one `script` block."""

    def __init__(self, owner: _ProgramCompiler, script: tree.Script) -> None:
        self.owner = owner
        self.script = script
        self.words: list[Word] = []
        self.variables: dict[str, _Variable] = {}
        self.next_slot = 0
        self.scratch_low = LOCAL_SLOTS
        #: Innermost-last, so `break` can tell a loop from a switch arm.
        self.blocks: list[_Block] = []

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

    def direct_value(self, node: tree.Expression) -> Value | None:
        """A value usable as an operand without evaluating anything first."""
        folded = _fold_negation(node)
        if folded is not None:
            node = folded
        if isinstance(node, tree.IntLiteral):
            self.reject_ambiguous_literal(node.value, node.position)
            return Value(Literal(node.value), ValueType.INT)
        if isinstance(node, tree.BoolLiteral):
            return Value(Literal(1 if node.value else 0), ValueType.INT)
        if isinstance(node, tree.FloatLiteral):
            return Value(Literal(self.encode_float(node)), ValueType.FLOAT)
        if isinstance(node, tree.StringLiteral):
            return Value(StringWord(self.owner.intern(node.value)), ValueType.STRING)
        if isinstance(node, tree.ScriptRef):
            # ⚠️ Typed INT, not a fourth ValueType. It IS an address as far as
            # the VM is concerned, and giving it its own type would make every
            # arithmetic check reject it for no reason -- the point is to hand
            # it to a builtin, and builtins take words.
            self.owner.require_script(node.name, node.position)
            return Value(ScriptWord(node.name), ValueType.INT)
        if isinstance(node, tree.Name):
            return self.name_value(node)
        if isinstance(node, tree.SlotRef):
            return self.slot_ref_value(node)
        return None

    def reject_ambiguous_literal(self, value: int, at: Position) -> None:
        """Refuse integers the VM would decode as a variable reference.

        Storage class comes from an operand's numeric range, so -30000000 *is*
        `lw[0]`; no encoding distinguishes them.
        """
        if not evt.is_literal(value):
            raise self.fail(
                f"the literal {value} collides with evt's variable encoding and "
                "would be read as a variable reference, not a number",
                at,
            )

    def encode_float(self, node: tree.FloatLiteral) -> int:
        try:
            return evt.encode_float(node.value)
        except ValueError as exc:
            raise self.fail(str(exc), node.position) from exc

    def name_value(self, node: tree.Name) -> Value:
        variable = self.variables.get(node.text)
        if variable is None:
            raise self.fail(
                f"{node.text!r} is not declared; "
                f"use 'var {node.text} = ...' before using it",
                node.position,
            )
        return Value(self.slot_word(variable.slot), variable.type)

    def slot_ref_value(self, node: tree.SlotRef) -> Value:
        storage = _STORAGE_BY_NAME[node.storage]
        try:
            encoded = storage.encode(node.index)
        except ValueError as exc:
            raise self.fail(str(exc), node.position) from exc
        # Floats share the same work slots and are distinguished by the
        # instruction, so a bare slot reference is typed INT.
        return Value(Literal(encoded), ValueType.INT)

    def evaluate(self, node: tree.Expression) -> Value:
        """Produce a `Value` for `node`, emitting code if it needs computing."""
        direct = self.direct_value(node)
        if direct is not None:
            return direct

        if isinstance(node, tree.Unary):
            return self.evaluate_unary(node)
        if isinstance(node, tree.Binary):
            return self.evaluate_binary(node)
        if isinstance(node, tree.Call):
            raise self.fail(
                f"{node.callee}(...) cannot be used as a value; evt user "
                "functions return results through output slots, so call it on "
                "its own line and read the slot it writes",
                node.position,
            )

        raise self.fail("unsupported expression", node.position)

    def evaluate_unary(self, node: tree.Unary) -> Value:
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

    def evaluate_binary(self, node: tree.Binary) -> Value:
        assert node.left is not None and node.right is not None

        if node.operator in COMPARISONS or node.operator in ("and", "or"):
            return self.boolean_value(node)

        operation = ARITHMETIC.get(node.operator)
        if operation is None:
            raise self.fail(f"unknown operator {node.operator!r}", node.position)

        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        result_type = self.unify(left, right, node.operator, node.position)

        # Fresh slot: arithmetic writes back into its first operand, so reusing
        # `left` would clobber a variable the statement still needs.
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

    def boolean_value(self, node: tree.Expression) -> Value:
        """Materialise a condition as 0 or 1 in a scratch slot."""
        slot = self.take_scratch(node.position)
        self.emit(evt.Opcode.SET, self.slot_word(slot), Literal(0))
        self.branch_if(node, invert=False)
        self.emit(evt.Opcode.SET, self.slot_word(slot), Literal(1))
        self.emit(evt.Opcode.END_IF)
        return Value(self.slot_word(slot), ValueType.INT)

    # --- conditions ------------------------------------------------------

    def branch_if(self, node: tree.Expression, invert: bool) -> None:
        """Open an `IF` that runs its body when `node` is true (or false).

        The caller must emit the matching `END_IF`.
        """
        if isinstance(node, tree.Binary) and node.operator in COMPARISONS:
            self.branch_comparison(node, invert)
            return

        if isinstance(node, tree.Unary) and node.operator == "not":
            assert node.operand is not None
            self.branch_if(node.operand, invert=not invert)
            return

        if isinstance(node, tree.Binary) and node.operator in ("and", "or"):
            self.branch_boolean(node, invert)
            return

        value = self.evaluate(node)
        if value.type is ValueType.STRING:
            raise self.fail("a string is not a condition", node.position)
        opcode = evt.Opcode.IF_EQUAL if invert else evt.Opcode.IF_NOT_EQUAL
        self.emit(opcode, value.word, Literal(0))

    def branch_comparison(self, node: tree.Binary, invert: bool) -> None:
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
        node: tree.Binary,
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

    def branch_boolean(self, node: tree.Binary, invert: bool) -> None:
        """`and`/`or` via a 0/1 accumulator.

        No short-circuiting: `evt` has none, and expressions are side-effect
        free because calls are statements.
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

    def compile_body(self, body: list[tree.Statement]) -> None:
        for statement in body:
            # Scratch is statement-local; slots go back into the pool after.
            high_water = self.scratch_low
            self.compile_statement(statement)
            self.scratch_low = high_water

    def compile_statement(self, node: tree.Statement) -> None:
        if isinstance(node, tree.VarDecl):
            self.compile_var(node)
        elif isinstance(node, tree.Assign):
            self.compile_assign(node)
        elif isinstance(node, tree.If):
            self.compile_if(node)
        elif isinstance(node, tree.While):
            self.compile_while(node)
        elif isinstance(node, tree.Loop):
            self.compile_loop(node)
        elif isinstance(node, tree.Switch):
            self.compile_switch(node)
        elif isinstance(node, tree.Wait):
            self.compile_wait(node)
        elif isinstance(node, tree.Spawn):
            self.compile_spawn(node)
        elif isinstance(node, tree.ExpressionStatement):
            self.compile_call_statement(node)
        elif isinstance(node, (tree.Break, tree.Continue)):
            self.compile_loop_jump(node)
        elif isinstance(node, tree.Return):
            self.emit(evt.Opcode.END_EVT)
        else:
            raise self.fail("unsupported statement", node.position)

    def compile_var(self, node: tree.VarDecl) -> None:
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

    def compile_assign(self, node: tree.Assign) -> None:
        assert node.target is not None and node.value is not None
        value = self.evaluate(node.value)

        if isinstance(node.target, tree.Name):
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

    def compile_if(self, node: tree.If) -> None:
        assert node.condition is not None
        self.branch_if(node.condition, invert=False)
        self.compile_body(node.then_body)
        if node.else_body:
            self.emit(evt.Opcode.ELSE)
            self.compile_body(node.else_body)
        self.emit(evt.Opcode.END_IF)

    def compile_while(self, node: tree.While) -> None:
        """`while` on top of `evt`'s counted `DO`/`WHILE`.

        There is no condition-tested loop, so an unbounded `DO 0` with a guarded
        `DO_BREAK` at the top stands in for one.
        """
        assert node.condition is not None
        self.emit(evt.Opcode.DO, Literal(0))
        self.blocks.append(_Block.LOOP)

        high_water = self.scratch_low
        self.branch_if(node.condition, invert=True)
        self.emit(evt.Opcode.DO_BREAK)
        self.emit(evt.Opcode.END_IF)
        self.scratch_low = high_water

        self.compile_body(node.body)
        self.blocks.pop()
        self.emit(evt.Opcode.WHILE)

    def compile_loop(self, node: tree.Loop) -> None:
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
        self.blocks.append(_Block.LOOP)
        self.compile_body(node.body)
        self.blocks.pop()
        self.emit(evt.Opcode.WHILE)

    def compile_switch(self, node: tree.Switch) -> None:
        assert node.subject is not None
        subject = self.evaluate(node.subject)
        if subject.type is not ValueType.INT:
            raise self.fail(
                f"a switch subject must be an integer, not {subject.type}; "
                "evt has no float or string form of SWITCH",
                node.position,
            )
        # Always SWITCH, never SWITCHI: the subject is usually a slot, and only
        # SWITCH resolves an operand through evt's storage windows.
        self.emit(evt.Opcode.SWITCH, subject.word)
        self.blocks.append(_Block.SWITCH)
        for case in node.cases:
            self.compile_case(case)
        if node.has_else:
            self.emit(evt.Opcode.CASE_ETC)
            self.compile_body(node.else_body)
        self.blocks.pop()
        # No SWITCH_BREAK per arm: the next CASE_* ends the previous body.
        self.emit(evt.Opcode.END_SWITCH)

    def compile_case(self, case: tree.SwitchCase) -> None:
        if len(case.alternatives) > 1:
            for alternative in case.alternatives:
                self.emit(evt.Opcode.CASE_OR, self.case_operand(alternative))
            self.compile_body(case.body)
            self.emit(evt.Opcode.CASE_END)
            return
        opcode = CASE_OPCODES[case.operator]
        self.emit(opcode, self.case_operand(case.alternatives[0]))
        self.compile_body(case.body)

    def case_operand(self, node: tree.Expression) -> Word:
        """A case value, which must need no code to produce.

        Anything computed would emit its instructions between the arms, where
        they would run as part of the previous case's body.
        """
        value = self.direct_value(node)
        if value is None:
            raise self.fail(
                "a case value must be a literal, a variable or a slot; "
                "compute it into a variable before the switch",
                node.position,
            )
        if value.type is not ValueType.INT:
            raise self.fail(
                f"a case value must be an integer, not {value.type}; "
                "evt has no float or string form of CASE_*",
                node.position,
            )
        return value.word

    def compile_loop_jump(self, node: tree.Break | tree.Continue) -> None:
        breaking = isinstance(node, tree.Break)
        opcode = evt.Opcode.DO_BREAK if breaking else evt.Opcode.DO_CONTINUE
        spelling = "break" if breaking else "continue"
        if self.blocks and self.blocks[-1] is _Block.SWITCH:
            raise self.fail(
                f"'{spelling}' cannot cross a switch; it would jump past the "
                "END_SWITCH and leave the switch open. Cases do not fall "
                "through, so a plain 'break' is never needed here",
                node.position,
            )
        if _Block.LOOP not in self.blocks:
            raise self.fail(f"'{spelling}' is only valid inside a loop", node.position)
        self.emit(opcode)

    def compile_wait(self, node: tree.Wait) -> None:
        assert node.duration is not None
        value = self.evaluate(node.duration)
        if value.type is ValueType.STRING:
            raise self.fail("a wait duration must be a number", node.position)
        opcode = evt.Opcode.WAIT_MSEC if node.milliseconds else evt.Opcode.WAIT_FRM
        self.emit(opcode, value.word)

    def compile_spawn(self, node: tree.Spawn) -> None:
        self.owner.require_script(node.name, node.position)
        self.emit(evt.Opcode.RUN_CHILD_EVT, ScriptWord(node.name))

    def compile_call_statement(self, node: tree.ExpressionStatement) -> None:
        call = node.expression
        if not isinstance(call, tree.Call):
            raise self.fail("expected a call", node.position)

        self.owner.check_call(call)
        arguments = [self.evaluate(argument) for argument in call.arguments]
        self.owner.note_symbol(call.callee)
        # USER_FUNC takes the function pointer as its first argument.
        self.emit(
            evt.Opcode.USER_FUNC,
            SymbolWord(call.callee),
            *[argument.word for argument in arguments],
        )

    def compile(self) -> CompiledScript:
        self.compile_body(self.script.body)
        # TWO terminators, and they are not alternatives.
        #
        # END_EVT ends the running *entry*; END_SCRIPT ends the instruction
        # *list*. ⛔ Emitting only the second was D105: a script that fell off
        # its end left its entry alive, and the game hung a few frames later
        # with every value the script had written still correct. An explicit
        # `return` already emitted END_EVT, which is why every mod that ended
        # one way worked and every mod that ended the other did not.
        #
        # Emitted unconditionally. After a `return` this is unreachable, which
        # costs one word and removes the need to reason about whether the last
        # statement on every path happened to be one.
        self.emit(evt.Opcode.END_EVT)
        # Without this the VM runs off into adjacent memory.
        self.emit(evt.Opcode.END_SCRIPT)
        return CompiledScript(
            name=self.script.name, words=self.words, slots_used=self.slots_used
        )


class _ProgramCompiler:
    """Compiles every script in one source file."""

    def __init__(
        self,
        program: tree.Program,
        source: str,
        catalog: builtin_catalog.Catalog | None = None,
        symbol_table=None,
    ) -> None:
        self.program = program
        self.source = source
        self.catalog = catalog if catalog is not None else builtin_catalog.load()
        #: Optional; when present, unknown names are rejected here, not at link
        #: time -- see `_check_linkable`.
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

    def check_call(self, call: tree.Call) -> None:
        """Reject a call the catalog says cannot be right.

        Otherwise an unknown name surfaces only as an `elf2rel` link failure,
        and a wrong argument count is never caught at all.
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
            # Only show the signature when there is one.
            shape = f"\n  {known.signature}" if known.signature else ""
            raise ScriptError(
                f"{call.callee} takes {known.arity} argument(s), "
                f"but {len(call.arguments)} were given{shape}",
                call.position,
                self.source,
            )

    def _check_linkable(self, call: tree.Call) -> None:
        """Reject a call that will not survive the link.

        ⚠️ 148 of 443 documented builtins are absent from `spm.eu0.lst` (D61).
        They pass the catalog check above and then die at `elf2rel`.
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


def _fold_negation(node: tree.Expression) -> tree.Expression | None:
    """Rewrite a negated literal into a negative literal.

    Saves three instructions, and makes `reject_ambiguous_literal` reachable —
    only negative numbers land in `evt`'s variable-encoding windows, and the
    parser otherwise only ever produces a unary minus over a positive literal.
    """
    if not isinstance(node, tree.Unary) or node.operator != "-":
        return None
    if isinstance(node.operand, tree.IntLiteral):
        return tree.IntLiteral(position=node.position, value=-node.operand.value)
    if isinstance(node.operand, tree.FloatLiteral):
        return tree.FloatLiteral(position=node.position, value=-node.operand.value)
    return None


def compile_program(
    program: tree.Program,
    source: str = "",
    catalog: builtin_catalog.Catalog | None = None,
    symbol_table=None,
) -> CompiledProgram:
    """Compile a parsed program to `evt` bytecode."""
    return _ProgramCompiler(program, source, catalog, symbol_table).compile()
