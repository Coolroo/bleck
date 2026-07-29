"""The script language itself: lexing, encoding, statements, control flow.

Mostly about *encoding*: `evt` recovers an operand's meaning from its numeric
range, so an off-by-one in a base constant runs and misbehaves rather than
failing — hence the hand-derived exact-word assertions.

Generating C is `test_emit.py`; wiring a program into a mod is
`test_code_mods.py`.
"""

from __future__ import annotations

import pytest

from bleck.script import compile_source, evt
from bleck.script.compiler import (
    Literal,
    ScriptWord,
    StringWord,
    SymbolWord,
    compile_program,
)
from bleck.script.errors import ScriptError
from bleck.script.syntax.lexer import TokenKind, tokenize
from bleck.script.syntax.parser import parse


def words(source: str, script: str = "main") -> list:
    """Compile `source` and return one script's words."""
    program = compile_program(parse(source), source)
    for compiled in program.scripts:
        if compiled.name == script:
            return compiled.words
    raise AssertionError(f"no script named {script}")


def values(source: str, script: str = "main") -> list[int]:
    """The words of a script, as plain integers. Fails on symbolic words."""
    return [word.value for word in words(source, script) if isinstance(word, Literal)]


#: The smallest useful program, for tests that only care about the scaffolding.
SIMPLE = "script main {\n wait(1)\n}"


def header(opcode: evt.Opcode, count: int) -> int:
    return evt.instruction_header(opcode, count)


class TestTermination:
    """Every compiled script must end its evt ENTRY, not just its instruction
    list (D106).

    ⚠️ These are the tests the suite did not have. Every other bytecode
    assertion here compares the compiler against itself -- it says "emit these
    words", so it passes on any self-consistent compiler, including one that
    omits a terminator the VM requires. A script missing `END_EVT` left its
    entry alive and hung the game, and 809 tests passed on both versions.

    So these assert a property the *VM* imposes, across shapes rather than one
    example: whatever the body, the entry gets terminated.
    """

    @pytest.mark.parametrize(
        ("label", "body"),
        [
            ("empty", ""),
            ("one statement", " wait(1)"),
            ("explicit return", " return"),
            ("statement then return", " wait(1)\n return"),
            ("infinite loop", " loop {\n wait(1)\n }"),
            ("switch", " switch gw[0] {\n case 1 {\n wait(1)\n }\n }"),
        ],
    )
    def test_a_script_ends_its_entry_whatever_the_body(self, label, body):
        out = values(f"script main {{\n{body}\n}}")
        expected = [int(evt.Opcode.END_EVT), int(evt.Opcode.END_SCRIPT)]
        assert out[-2:] == expected, label

    def test_a_return_does_not_replace_the_trailing_pair(self):
        """`return` emits END_EVT where it stands, and the trailing pair is
        emitted anyway -- unreachable, so nothing has to reason about whether
        the last statement on every path happened to be one."""
        out = values("script main {\n return\n}")
        assert out.count(int(evt.Opcode.END_EVT)) == 2

    def test_every_script_in_a_program_terminates(self):
        """Not only the entry script. A map hook or a combo script that ends
        hung the game exactly the same way, which is what made patching `main`
        the wrong shape of fix."""
        source = (
            "script main {\n wait(1)\n}\n"
            "script on_arrive {\n gw[0] = 1\n}\n"
            "script on_combo {\n gw[1] = 2\n}\n"
        )
        expected = [int(evt.Opcode.END_EVT), int(evt.Opcode.END_SCRIPT)]
        for name in ("main", "on_arrive", "on_combo"):
            assert values(source, name)[-2:] == expected, name


class TestLexer:
    def test_tracks_line_and_column(self):
        tokens = tokenize("script main {\n    wait(1)\n}")
        wait = next(t for t in tokens if t.text == "wait")
        assert wait.position.line == 2
        assert wait.position.column == 5

    def test_both_comment_styles_are_ignored(self):
        source = "script main {\n -- lua style\n // c style\n /* block */ wait(1)\n}"
        assert values(source) == [header(evt.Opcode.WAIT_FRM, 1), 1, 2, 1]

    def test_blank_lines_collapse(self):
        tokens = tokenize("a\n\n\n\nb")
        newlines = [t for t in tokens if t.kind is TokenKind.NEWLINE]
        assert len(newlines) == 1

    def test_hex_literals(self):
        assert values("script main {\n wait(0x10)\n}")[1] == 16

    def test_underscores_in_numbers(self):
        assert values("script main {\n wait(1_000)\n}")[1] == 1000

    def test_dot_after_number_is_not_a_float(self):
        # `1.foo` must scan as an integer, not a malformed float.
        tokens = tokenize("1.foo")
        assert tokens[0].kind is TokenKind.INT
        assert tokens[1].is_op(".")

    def test_unterminated_string_reports_its_opening(self):
        with pytest.raises(ScriptError) as caught:
            tokenize('script main {\n evt_x("oops)\n}')
        assert caught.value.position.line == 2

    def test_unknown_escape_is_rejected(self):
        with pytest.raises(ScriptError, match=r"unknown escape"):
            tokenize(r'"\q"')


class TestEncoding:
    """The numeric windows that give `evt` operands their meaning."""

    def test_local_work_slots(self):
        assert evt.LW.encode(0) == -30000000
        assert evt.LW.encode(15) == -29999985

    def test_global_work_slots(self):
        assert evt.GW.encode(0) == -50000000

    def test_slot_out_of_range_is_rejected(self):
        with pytest.raises(ValueError, match=r"out of range"):
            evt.LW.encode(16)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(1.0, -239998976), (2.0, -239997952), (0.0, -240000000), (-1.0, -240001024)],
    )
    def test_floats_are_fixed_point(self, value, expected):
        assert evt.encode_float(value) == expected

    def test_huge_floats_are_rejected(self):
        # Wrapping into the address window gives the VM an operand it reads as
        # a pointer.
        with pytest.raises(ValueError, match=r"cannot be represented"):
            evt.encode_float(1e9)

    def test_instruction_header_packs_count_and_opcode(self):
        assert header(evt.Opcode.WAIT_FRM, 1) == 0x10009

    def test_literal_detection_matches_the_windows(self):
        assert evt.is_literal(5)
        assert evt.is_literal(-1)
        assert not evt.is_literal(evt.LW.encode(0))
        assert not evt.is_literal(evt.encode_float(1.0))


class TestStatements:
    def test_wait_frames(self):
        assert values("script main {\n wait(30)\n}") == [
            header(evt.Opcode.WAIT_FRM, 1),
            30,
            int(evt.Opcode.END_EVT),
            int(evt.Opcode.END_SCRIPT),
        ]

    def test_wait_milliseconds_uses_a_different_opcode(self):
        assert values("script main {\n wait_ms(30)\n}")[0] == header(
            evt.Opcode.WAIT_MSEC, 1
        )

    def test_every_script_is_terminated(self):
        # Without END_SCRIPT the VM runs into whatever follows the array.
        assert values("script main {\n wait(1)\n}")[-1] == int(evt.Opcode.END_SCRIPT)

    def test_variable_lands_in_slot_zero(self):
        assert values("script main {\n var x = 7\n}")[:3] == [
            header(evt.Opcode.SET, 2),
            evt.LW.encode(0),
            7,
        ]

    def test_float_variable_uses_the_float_setter(self):
        assert values("script main {\n var x = 1.5\n}")[0] == header(evt.Opcode.SETF, 2)

    def test_variables_get_distinct_slots(self):
        result = values("script main {\n var a = 1\n var b = 2\n}")
        assert evt.LW.encode(0) in result
        assert evt.LW.encode(1) in result

    def test_return_ends_the_script_not_the_array(self):
        result = values("script main {\n return\n}")
        assert result[0] == int(evt.Opcode.END_EVT)
        assert result[-1] == int(evt.Opcode.END_SCRIPT)

    def test_explicit_global_slot(self):
        assert evt.GW.encode(3) in values("script main {\n gw[3] = 1\n}")

    def test_redeclaring_a_variable_is_rejected(self):
        with pytest.raises(ScriptError, match=r"already declared"):
            words("script main {\n var x = 1\n var x = 2\n}")

    def test_undeclared_variable_is_rejected(self):
        with pytest.raises(ScriptError, match=r"not declared"):
            words("script main {\n x = 1\n}")

    def test_reassigning_a_different_type_is_rejected(self):
        with pytest.raises(ScriptError, match=r"holds int"):
            words("script main {\n var x = 1\n x = 1.0\n}")

    def test_running_out_of_slots_is_a_clear_error(self):
        source = "script main {\n" + "".join(f" var v{i} = 1\n" for i in range(17)) + "}"
        with pytest.raises(ScriptError, match=r"more than 16 local slots"):
            words(source)


class TestExpressions:
    def test_arithmetic_uses_a_scratch_slot(self):
        # `evt` arithmetic updates its first argument in place, so a result
        # written back into an operand would clobber `a`.
        result = values("script main {\n var a = 1\n var b = a + 2\n}")
        assert evt.LW.encode(15) in result
        assert header(evt.Opcode.ADD, 2) in result

    def test_float_arithmetic_uses_float_opcodes(self):
        result = values("script main {\n var a = 1.0\n var b = a * 2.0\n}")
        assert header(evt.Opcode.MULF, 2) in result
        assert header(evt.Opcode.MUL, 2) not in result

    def test_mixing_int_and_float_is_rejected(self):
        with pytest.raises(ScriptError, match=r"int and float|float and int"):
            words("script main {\n var a = 1.0\n var b = a + 1\n}")

    def test_modulo_has_no_float_form(self):
        with pytest.raises(ScriptError, match=r"no float form"):
            words("script main {\n var a = 1.0\n var b = a % 2.0\n}")

    def test_negative_literals_fold(self):
        # One operand, not a runtime subtract-from-zero.
        assert values("script main {\n var a = -5\n}") == [
            header(evt.Opcode.SET, 2),
            evt.LW.encode(0),
            -5,
            int(evt.Opcode.END_EVT),
            int(evt.Opcode.END_SCRIPT),
        ]

    def test_literal_colliding_with_a_slot_encoding_is_rejected(self):
        with pytest.raises(ScriptError, match=r"collides with evt's variable"):
            words("script main {\n var a = -30000000\n}")

    def test_calls_are_not_expressions(self):
        with pytest.raises(ScriptError, match=r"cannot be used as a value"):
            words("script main {\n var a = evt_sub_random(5)\n}")

    def test_precedence_multiplication_before_addition(self):
        # 1 + 2 * 3 must multiply first, so MUL is emitted before ADD.
        result = values("script main {\n var a = 1 + 2 * 3\n}")
        assert result.index(header(evt.Opcode.MUL, 2)) < result.index(
            header(evt.Opcode.ADD, 2)
        )

    def test_parentheses_override_precedence(self):
        result = values("script main {\n var a = (1 + 2) * 3\n}")
        assert result.index(header(evt.Opcode.ADD, 2)) < result.index(
            header(evt.Opcode.MUL, 2)
        )


class TestControlFlow:
    def test_if_emits_a_comparison_and_end_if(self):
        result = values("script main {\n var a = 1\n if a == 1 {\n wait(1)\n }\n}")
        assert header(evt.Opcode.IF_EQUAL, 2) in result
        assert int(evt.Opcode.END_IF) in result

    def test_else_emits_an_else_opcode(self):
        source = (
            "script main {\n var a=1\n if a == 1 {\n wait(1)\n } else {\n wait(2)\n }\n}"
        )
        assert int(evt.Opcode.ELSE) in values(source)

    def test_float_comparison_uses_float_opcode(self):
        source = "script main {\n var a = 1.0\n if a > 0.5 {\n wait(1)\n }\n}"
        assert header(evt.Opcode.IFF_LARGE, 2) in values(source)

    def test_while_becomes_a_guarded_infinite_do(self):
        # `evt` has no condition-tested loop, so `while` is DO 0 with an
        # inverted test and a DO_BREAK.
        source = "script main {\n var i = 0\n while i < 3 {\n wait(1)\n }\n}"
        result = values(source)
        assert header(evt.Opcode.DO, 1) in result
        assert int(evt.Opcode.DO_BREAK) in result
        assert int(evt.Opcode.WHILE) in result
        # `<` inverts to `>=` so the loop breaks when the condition fails.
        assert header(evt.Opcode.IF_LARGE_EQUAL, 2) in result

    def test_loop_with_count_passes_the_count(self):
        result = values("script main {\n loop 5 {\n wait(1)\n }\n}")
        assert result[:2] == [header(evt.Opcode.DO, 1), 5]

    def test_bare_loop_runs_forever(self):
        assert values("script main {\n loop {\n wait(1)\n }\n}")[:2] == [
            header(evt.Opcode.DO, 1),
            0,
        ]

    def test_break_and_continue_inside_a_loop(self):
        source = "script main {\n loop 2 {\n break\n }\n}"
        assert int(evt.Opcode.DO_BREAK) in values(source)

    def test_break_outside_a_loop_is_rejected(self):
        with pytest.raises(ScriptError, match=r"only valid inside a loop"):
            words("script main {\n break\n}")

    def test_not_inverts_a_parenthesised_comparison(self):
        source = "script main {\n var a=1\n if not (a == 1) {\n wait(1)\n }\n}"
        assert header(evt.Opcode.IF_NOT_EQUAL, 2) in values(source)

    def test_not_binds_tighter_than_comparison(self):
        # As in C and Lua, `not a == 1` is `(not a) == 1` -- Python reads it
        # the other way.
        source = "script main {\n var a=1\n if not a == 1 {\n wait(1)\n }\n}"
        result = values(source)
        assert header(evt.Opcode.IF_NOT_EQUAL, 2) not in result
        assert header(evt.Opcode.IF_EQUAL, 2) in result

    def test_not_on_a_bare_variable_tests_against_zero(self):
        source = "script main {\n var a=1\n if not a {\n wait(1)\n }\n}"
        assert header(evt.Opcode.IF_EQUAL, 2) in values(source)

    def test_and_combines_two_conditions(self):
        source = (
            "script main {\n var a=1\n var b=2\n if a == 1 and b == 2 {\n wait(1)\n }\n}"
        )
        assert header(evt.Opcode.AND, 2) in values(source)

    def test_or_combines_two_conditions(self):
        source = (
            "script main {\n var a=1\n var b=2\n if a == 1 or b == 2 {\n wait(1)\n }\n}"
        )
        assert header(evt.Opcode.OR, 2) in values(source)

    def test_else_if_chains(self):
        source = (
            "script main {\n var a=1\n"
            " if a == 1 {\n wait(1)\n } else if a == 2 {\n wait(2)\n }\n}"
        )
        result = values(source)
        assert result.count(int(evt.Opcode.END_IF)) == 2


class TestSwitch:
    def test_simple_equality_case(self):
        source = "script main {\n var a = 1\n switch a {\n case 1 {\n wait(1)\n }\n }\n}"
        result = values(source)
        assert header(evt.Opcode.SWITCH, 1) in result
        assert header(evt.Opcode.CASE_EQUAL, 1) in result
        assert int(evt.Opcode.END_SWITCH) in result

    @pytest.mark.parametrize(
        ("operator", "opcode"),
        [
            ("==", evt.Opcode.CASE_EQUAL),
            ("!=", evt.Opcode.CASE_NOT_EQUAL),
            ("<", evt.Opcode.CASE_SMALL),
            (">", evt.Opcode.CASE_LARGE),
            ("<=", evt.Opcode.CASE_SMALL_EQUAL),
            (">=", evt.Opcode.CASE_LARGE_EQUAL),
        ],
    )
    def test_comparison_cases(self, operator, opcode):
        source = (
            "script main {\n var a = 1\n switch a {\n"
            f" case {operator} 10 {{\n wait(1)\n }}\n }}\n}}"
        )
        assert header(opcode, 1) in values(source)

    def test_or_list_becomes_case_or_and_case_end(self):
        source = (
            "script main {\n var a = 1\n switch a {\n case 2, 3 {\n wait(1)\n }\n }\n}"
        )
        result = values(source)
        assert result.count(header(evt.Opcode.CASE_OR, 1)) == 2
        assert int(evt.Opcode.CASE_END) in result
        # The group closes after the body, not before it.
        assert result.index(header(evt.Opcode.WAIT_FRM, 1)) < result.index(
            int(evt.Opcode.CASE_END)
        )

    def test_else_becomes_case_etc(self):
        source = (
            "script main {\n var a = 1\n switch a {\n"
            " case 1 {\n wait(1)\n }\n else {\n wait(2)\n }\n }\n}"
        )
        assert int(evt.Opcode.CASE_ETC) in values(source)

    def test_empty_else_still_emits_case_etc(self):
        source = (
            "script main {\n var a = 1\n switch a {\n case 1 {\n }\n else {\n }\n }\n}"
        )
        assert int(evt.Opcode.CASE_ETC) in values(source)

    def test_no_switch_break_is_emitted(self):
        # Cases do not fall through, so the next CASE_* ends the previous body.
        source = (
            "script main {\n var a = 1\n switch a {\n"
            " case 1 {\n wait(1)\n }\n case 2 {\n wait(2)\n }\n }\n}"
        )
        assert int(evt.Opcode.SWITCH_BREAK) not in values(source)

    def test_exact_word_sequence(self):
        source = (
            "script main {\n var a = 1\n switch a {\n"
            " case 1 {\n wait(1)\n }\n else {\n wait(2)\n }\n }\n}"
        )
        assert values(source) == [
            header(evt.Opcode.SET, 2),
            evt.LW.encode(0),
            1,
            header(evt.Opcode.SWITCH, 1),
            evt.LW.encode(0),
            header(evt.Opcode.CASE_EQUAL, 1),
            1,
            header(evt.Opcode.WAIT_FRM, 1),
            1,
            int(evt.Opcode.CASE_ETC),
            header(evt.Opcode.WAIT_FRM, 1),
            2,
            int(evt.Opcode.END_SWITCH),
            int(evt.Opcode.END_EVT),
            int(evt.Opcode.END_SCRIPT),
        ]

    def test_subject_may_be_computed(self):
        # The subject is evaluated before SWITCH, so arithmetic is fine there.
        source = (
            "script main {\n var a = 1\n switch a + 1 {\n case 2 {\n wait(1)\n }\n }\n}"
        )
        result = values(source)
        assert result.index(header(evt.Opcode.ADD, 2)) < result.index(
            header(evt.Opcode.SWITCH, 1)
        )

    def test_computed_case_value_is_rejected(self):
        # Its instructions would land inside the previous case's body.
        source = (
            "script main {\n var a = 1\n switch a {\n case a + 1 {\n wait(1)\n }\n }\n}"
        )
        with pytest.raises(ScriptError, match=r"case value must be a literal"):
            words(source)

    def test_float_subject_is_rejected(self):
        source = "script main {\n var a = 1.0\n switch a {\n case 1 {\n }\n }\n}"
        with pytest.raises(ScriptError, match=r"switch subject must be an integer"):
            words(source)

    def test_second_else_is_rejected(self):
        source = (
            "script main {\n var a = 1\n switch a {\n"
            " case 1 {\n }\n else {\n }\n else {\n }\n }\n}"
        )
        with pytest.raises(ScriptError, match=r"already has an 'else'"):
            words(source)

    def test_else_before_a_case_is_rejected(self):
        source = (
            "script main {\n var a = 1\n switch a {\n else {\n }\n case 1 {\n }\n }\n}"
        )
        with pytest.raises(ScriptError, match=r"must be the last arm"):
            words(source)

    def test_comparison_case_cannot_take_a_comma_list(self):
        source = "script main {\n var a = 1\n switch a {\n case > 1, 2 {\n }\n }\n}"
        with pytest.raises(ScriptError, match=r"cannot\s+take a comma list"):
            words(source)

    def test_a_statement_in_the_switch_body_is_rejected(self):
        source = "script main {\n var a = 1\n switch a {\n wait(1)\n }\n}"
        with pytest.raises(ScriptError, match=r"expected 'case' or 'else'"):
            words(source)

    def test_break_inside_a_switch_is_rejected(self):
        source = (
            "script main {\n var a = 1\n loop 2 {\n switch a {\n"
            " case 1 {\n break\n }\n }\n }\n}"
        )
        with pytest.raises(ScriptError, match=r"cannot cross a switch"):
            words(source)

    def test_break_in_a_loop_inside_a_case_still_works(self):
        source = (
            "script main {\n var a = 1\n switch a {\n"
            " case 1 {\n loop 2 {\n break\n }\n }\n }\n}"
        )
        assert int(evt.Opcode.DO_BREAK) in values(source)

    def test_nested_switches(self):
        source = (
            "script main {\n var a = 1\n switch a {\n case 1 {\n"
            " switch a {\n case 2 {\n wait(1)\n }\n }\n }\n }\n}"
        )
        result = values(source)
        assert result.count(header(evt.Opcode.SWITCH, 1)) == 2
        assert result.count(int(evt.Opcode.END_SWITCH)) == 2


class TestCalls:
    def test_user_func_takes_the_pointer_as_first_argument(self):
        result = words("script main {\n evt_mario_set_pos(1.0, 2.0, 3.0)\n}")
        # Three script arguments plus the function pointer.
        assert result[0].value == header(evt.Opcode.USER_FUNC, 4)
        assert isinstance(result[1], SymbolWord)
        assert result[1].name == "evt_mario_set_pos"

    def test_strings_become_symbolic_words(self):
        result = words('script main {\n evt_msg_print(0, "hi", 0, 0)\n}')
        assert any(isinstance(word, StringWord) for word in result)

    def test_identical_strings_are_interned_once(self):
        source = (
            'script main {\n evt_msg_print_add(0, "a")\n evt_msg_print_add(1, "a")\n}'
        )
        assert compile_program(parse(source), source).strings == ["a"]

    def test_called_symbols_are_reported(self):
        program = compile_program(parse("script main {\n evt_pouch_add_coins(1)\n}"), "")
        assert program.called_symbols == ["evt_pouch_add_coins"]

    def test_spawn_references_another_script(self):
        source = "script main {\n spawn helper\n}\nscript helper {\n wait(1)\n}"
        result = words(source)
        assert result[0].value == header(evt.Opcode.RUN_CHILD_EVT, 1)
        assert isinstance(result[1], ScriptWord)

    def test_spawning_an_unknown_script_is_rejected(self):
        with pytest.raises(ScriptError, match=r"no script named"):
            words("script main {\n spawn nope\n}")


class TestDuplicateScripts:
    def test_two_scripts_with_one_name_are_rejected(self):
        with pytest.raises(ScriptError, match=r"declared twice"):
            parse("script main {\n}\nscript main {\n}")


class TestErrorRendering:
    def test_error_shows_the_line_and_a_caret(self):
        try:
            compile_source("script main {\n    x = 1\n}", origin="t.evt")
        except ScriptError as exc:
            rendered = exc.render("t.evt")
            assert "t.evt:2:5" in rendered
            assert "x = 1" in rendered
            assert "^" in rendered
        else:
            raise AssertionError("expected a ScriptError")

    def test_tabs_do_not_misplace_the_caret(self):
        error = ScriptError(
            "boom",
            __import__("bleck.script.errors", fromlist=["Position"]).Position(1, 2),
            "\tx",
        )
        # The echoed line and the caret must agree about width.
        assert "\t" not in error.render("f")
