"""Tests for the script language.

The assertions here are mostly about *encoding*, because that is where this
code can be wrong in ways nothing else catches. `evt` recovers an operand's
meaning from its numeric range, so an off-by-one in a base constant produces a
script that runs and does the wrong thing rather than one that fails. Several
tests therefore check exact words against values derived by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bleck.mods import code, registry, resolver
from bleck.mods import manifest as mod_manifest
from bleck.script import compile_source, emit, evt
from bleck.script.compiler import (
    Literal,
    ScriptWord,
    StringWord,
    SymbolWord,
    compile_program,
)
from bleck.script.errors import ScriptError
from bleck.script.lexer import TokenKind, tokenize
from bleck.script.parser import parse


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


#: The smallest useful program, for tests that only care about the scaffolding
#: the emitter wraps around every script.
SIMPLE = "script main {\n wait(1)\n}"


def header(opcode: evt.Opcode, count: int) -> int:
    return evt.instruction_header(opcode, count)


class TestLexer:
    def test_tracks_line_and_column(self):
        tokens = tokenize("script main {\n    wait(1)\n}")
        wait = next(t for t in tokens if t.text == "wait")
        assert wait.position.line == 2
        assert wait.position.column == 5

    def test_both_comment_styles_are_ignored(self):
        source = "script main {\n -- lua style\n // c style\n /* block */ wait(1)\n}"
        assert values(source) == [header(evt.Opcode.WAIT_FRM, 1), 1, 1]

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
        # Silently wrapping into the address window would produce an operand the
        # VM reads as a pointer.
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
            int(evt.Opcode.END_SCRIPT),
        ]

    def test_wait_milliseconds_uses_a_different_opcode(self):
        assert values("script main {\n wait_ms(30)\n}")[0] == header(
            evt.Opcode.WAIT_MSEC, 1
        )

    def test_every_script_is_terminated(self):
        # The VM scans for END_SCRIPT; without it execution runs into whatever
        # follows the array in memory.
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
        # Results must not be written back into an operand: `evt` arithmetic
        # updates its first argument in place, which would clobber `a`.
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
        # Matches C and Lua: `not a == 1` is `(not a) == 1`, not `not (a == 1)`.
        # Worth pinning down, because the two readings differ in behaviour and
        # a reader coming from Python would expect the other one.
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


class TestGeneratedC:
    def test_declares_called_functions_extern(self):
        out = compile_source("script main {\n evt_pouch_add_coins(1)\n}").generated
        assert "extern void evt_pouch_add_coins(void);" in out.text

    def test_takes_the_address_of_called_functions(self):
        # This is what keeps game addresses out of bleck: the linker resolves
        # the name, we never write a number.
        out = compile_source("script main {\n evt_pouch_add_coins(1)\n}").generated
        assert "(s32) &evt_pouch_add_coins" in out.text

    def test_no_game_addresses_appear(self):
        out = compile_source("script main {\n evt_pouch_add_coins(1)\n}").generated
        assert "0x80" not in out.text

    def test_entry_point_starts_the_main_script(self):
        out = compile_source("script main {\n wait(1)\n}").generated
        assert "void _prolog(void)" in out.text
        assert "evtEntry(bleck_script_main, 0, 0)" in out.text

    def test_prolog_only_arms_hooks(self):
        # Measured, not assumed: evtEntry from _prolog does nothing (D38), and
        # hooking .init does not work either (D40). Hooking .main does, verified
        # by reading the running game's memory (D43).
        out = compile_source(SIMPLE).generated
        prolog = out.text.split("void _prolog(void)")[1]
        assert "seq_data[i].main = bleck_hooks[i]" in prolog
        assert "evtEntry" not in prolog

    def test_every_sequence_is_hooked(self):
        # A script does not survive a map change (D43), so gameplay cannot be
        # the only sequence watched -- something has to notice we left it.
        out = compile_source(SIMPLE).generated
        for index in range(6):
            assert f"bleck_seq{index}" in out.text

    def test_leaving_gameplay_re_arms_the_start(self):
        out = compile_source(SIMPLE).generated
        body = out.text.split("static void bleck_after_seq")[1]
        assert "bleck_needs_start = 0" in body
        assert "bleck_needs_start = 1" in body
        assert body.index("bleck_needs_start = 0") < body.index("bleck_needs_start = 1")

    def test_the_original_sequence_function_is_still_called(self):
        assert "bleck_real_main[seq](work)" in compile_source(SIMPLE).generated.text

    def test_saved_pointers_avoid_bss(self):
        # The loader allocates this module's bss but nothing documents whether
        # it zeroes it, so the initialisers must be non-zero to force .data.
        out = compile_source(SIMPLE).generated
        assert "static u32 bleck_needs_start = 1;" in out.text
        assert "(SeqFunc *) 1" in out.text

    def test_sequence_table_is_referenced_by_name(self):
        out = compile_source(SIMPLE).generated
        assert "extern SeqDef seq_data[];" in out.text
        assert "0x80" not in out.text

    def test_all_rel_entry_points_are_defined(self):
        out = compile_source("script main {\n wait(1)\n}").generated
        for symbol in ("_prolog", "_epilog", "_unresolved"):
            assert f"void {symbol}(void)" in out.text

    def test_missing_main_is_rejected(self):
        with pytest.raises(ScriptError, match=r"no script named 'main'"):
            compile_source("script helper {\n wait(1)\n}")

    def test_output_is_ascii(self):
        # Mods build on three platforms whose compilers disagree about default
        # source encoding.
        out = compile_source(
            'script main {\n evt_msg_print_add(0, "café — ok")\n}'
        ).generated
        out.text.encode("ascii")

    def test_non_ascii_strings_survive_as_octal_escapes(self):
        out = compile_source('script main {\n evt_msg_print_add(0, "café")\n}').generated
        # 'é' is 0xC3 0xA9 in UTF-8 -> \303\251
        assert "\\303\\251" in out.text

    def test_quotes_and_backslashes_are_escaped(self):
        source = 'script main {\n evt_msg_print_add(0, "a\\"b\\\\c")\n}'
        assert '\\"' in compile_source(source).generated.text

    def test_forward_declares_scripts_when_several_exist(self):
        source = "script main {\n spawn helper\n}\nscript helper {\n wait(1)\n}"
        out = compile_source(source).generated
        assert "extern const s32 bleck_script_helper[];" in out.text


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


class TestManifestCodeBlock:
    """The `code` block that turns a mod into a code mod."""

    def test_absent_by_default(self):
        parsed = mod_manifest.Manifest.from_json('{"name": "m"}')
        assert parsed.code is None
        assert not parsed.has_code

    def test_omitted_from_output_when_absent(self):
        # An always-present empty block invites people to fill it in.
        assert "code" not in mod_manifest.Manifest(name="m").to_json()

    def test_parses_and_defaults(self):
        parsed = mod_manifest.Manifest.from_json(
            '{"name": "m", "code": {"script": "s/main.evt"}}'
        )
        assert parsed.code is not None
        assert parsed.code.script == "s/main.evt"
        assert parsed.code.target == "eu0"
        assert parsed.code.module_id == 2

    def test_round_trips(self):
        original = mod_manifest.Manifest(
            name="m",
            code=mod_manifest.CodeSpec(script="a.evt", target="us0", module_id=3),
        )
        assert mod_manifest.Manifest.from_json(original.to_json()).code == original.code

    def test_script_is_required(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"needs a 'script'"):
            mod_manifest.Manifest.from_json('{"name": "m", "code": {}}')

    @pytest.mark.parametrize("module_id", [0, 1])
    def test_reserved_module_ids_are_rejected(self, module_id):
        # 0 is the game binary and 1 is its own REL; either would collide with
        # something already linked when the mod loads.
        raw = json.dumps(
            {"name": "m", "code": {"script": "a.evt", "module_id": module_id}}
        )
        with pytest.raises(mod_manifest.ManifestError, match=r"must be 2 or more"):
            mod_manifest.Manifest.from_json(raw)

    def test_module_id_must_be_a_number(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"whole number"):
            mod_manifest.Manifest.from_json(
                '{"name": "m", "code": {"script": "a.evt", "module_id": "two"}}'
            )

    def test_code_must_be_an_object(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"must be an object"):
            mod_manifest.Manifest.from_json('{"name": "m", "code": "yes"}')


class TestOneCodeModPerBuild:
    """The loader opens exactly one /mod/mod.rel."""

    def _mod(self, name: str, has_code: bool):
        spec = mod_manifest.CodeSpec(script="s.evt") if has_code else None
        return registry.Mod(
            manifest=mod_manifest.Manifest(name=name, code=spec), root=Path(name)
        )

    def test_two_code_mods_fail_loudly_and_name_both(self):
        chain = resolver.Chain(
            entries=[
                resolver.ChainEntry(self._mod("alpha", True), ""),
                resolver.ChainEntry(self._mod("beta", True), "alpha"),
            ]
        )
        with pytest.raises(code.CodeError) as caught:
            code.build_chain(chain, workroot=Path("unused"))
        message = str(caught.value)
        assert "alpha" in message and "beta" in message

    def test_one_code_mod_alongside_asset_mods_is_fine(self):
        chain = resolver.Chain(
            entries=[
                resolver.ChainEntry(self._mod("textures", False), ""),
                resolver.ChainEntry(self._mod("behaviour", True), "textures"),
            ]
        )
        assert [m.name for m in code.mods_with_code(chain)] == ["behaviour"]


class TestNativeSources:
    """`code.sources`: native C compiled into the same module as the script.

    This exists because a script cannot reach ordinary game functions. Every
    evt builtin takes `(EvtEntry *, bool)`, so calling something like
    `mapDataPtr` -- which is how a mod attaches behaviour to a specific map --
    is only possible from C.
    """

    def _mod(self, tmp_path: Path, **code) -> registry.Mod:
        root = tmp_path / "m"
        (root / "src").mkdir(parents=True)
        spec = mod_manifest.CodeSpec(**code)
        return registry.Mod(
            manifest=mod_manifest.Manifest(name="m", code=spec), root=root
        )

    def test_a_named_file_is_collected(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src/hooks.c"])
        (mod.root / "src" / "hooks.c").write_text("void mod_prolog(void) {}")
        found = code.collect_sources(mod, mod.manifest.code)
        assert [p.name for p in found] == ["hooks.c"]

    def test_a_directory_contributes_every_c_file(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        for name in ("b.c", "a.c"):
            (mod.root / "src" / name).write_text("")
        found = code.collect_sources(mod, mod.manifest.code)
        # Sorted, so a build does not depend on filesystem ordering.
        assert [p.name for p in found] == ["a.c", "b.c"]

    def test_headers_are_not_mistaken_for_sources(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        (mod.root / "src" / "a.c").write_text("")
        (mod.root / "src" / "shared.h").write_text("")
        assert [p.name for p in code.collect_sources(mod, mod.manifest.code)] == ["a.c"]

    def test_an_empty_directory_is_an_error(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        with pytest.raises(code.CodeError, match=r"no .c files"):
            code.collect_sources(mod, mod.manifest.code)

    def test_a_missing_file_names_the_manifest_entry(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src/absent.c"])
        with pytest.raises(code.CodeError, match=r"code.sources"):
            code.collect_sources(mod, mod.manifest.code)


class TestGeneratedHandoff:
    """How generated scaffolding hands control to a mod's own C."""

    def test_the_hook_is_a_weak_definition_not_a_declaration(self):
        """A script-only module must leave `mod_prolog` defined, not undefined.

        This was a real build failure, not a style preference. A weak
        *declaration* leaves an undefined symbol, and `elf2rel` resolves every
        undefined symbol against the game's list -- so a mod with a script and
        no C of its own died with "Missing 1 required symbol(s): mod_prolog"
        before it could ever be built. A weak definition leaves nothing
        undefined, and a mod's own strong definition still overrides it.
        """
        out = compile_source(SIMPLE).generated.text
        assert "__attribute__((weak)) void mod_prolog(void)\n{\n}" in out
        assert "__attribute__((weak)) void mod_prolog(void);" not in out
        # With a definition present the address is never null, so a guard here
        # is dead code that -Waddress would flag.
        assert "if (mod_prolog != 0)" not in out

    def test_generated_code_keeps_ownership_of_prolog(self):
        """The sequence hooks must be installed before the mod's own code runs.

        If a mod owned `_prolog` it could start work before the scaffolding was
        in place, and the ordering would depend on link order.
        """
        out = compile_source(SIMPLE).generated.text
        prolog = out.split("void _prolog(void)")[1]
        assert prolog.index("seq_data[i].main") < prolog.index("mod_prolog()")

    def test_a_sources_only_module_still_has_the_entry_points(self):

        out = emit.generate_bare().text
        for symbol in ("_prolog", "_epilog", "_unresolved"):
            assert f"void {symbol}(void)" in out
        # Nothing to schedule, so no sequence machinery.
        assert "seq_data" not in out
        assert "evtEntry" not in out

    def test_a_sources_only_module_still_calls_the_mod(self):

        assert "mod_prolog();" in emit.generate_bare().text
