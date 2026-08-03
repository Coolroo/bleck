"""`bleck doctor`, the preflight check, and the hints they both print.

⚠️ These run on whatever host CI gives them, so nothing here may depend on a
tool being installed: every search and every probe is substituted. The macOS
and Linux answers are reached by swapping the `PlatformProfile`, the same way
`tests/test_platform.py` reaches the Windows ones from Linux.
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from bleck import platforms
from bleck.backends import disc, doctor
from bleck.backends.doctor import ToolState
from bleck.cli import app as cli
from bleck.cli import requirements
from bleck.platforms import ToolKey

ALL_PROFILES = [
    platforms.linux.PROFILE,
    platforms.macos.PROFILE,
    platforms.windows.PROFILE,
]

FAKE = "/opt/tools/thing"


def _found(key: ToolKey, path: str = FAKE) -> disc.ToolSearch:
    return disc.ToolSearch(key, path, "PATH")


def _absent(key: ToolKey) -> disc.ToolSearch:
    return disc.ToolSearch(key, problem=f"{key} not found (looked for: nothing)")


def _broken(key: ToolKey) -> disc.ToolSearch:
    return disc.ToolSearch(
        key,
        problem=f"{key.override.name} is set to /nowhere, which does not exist",
        override_is_broken=True,
    )


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[FAKE], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def searches(monkeypatch):
    """Substitute the whole search, so no test depends on this host's tools."""

    def install(answers: dict[ToolKey, disc.ToolSearch]) -> None:
        monkeypatch.setattr(doctor, "locate", lambda key: answers.get(key, _absent(key)))

    return install


@pytest.fixture
def runs(monkeypatch):
    """Substitute the probe's outcome, including the ways it can fail to run."""

    def install(outcome) -> None:
        def fake(*_args, **_kwargs):
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(doctor.subprocess, "run", fake)

    return install


class TestEveryToolIsProbeable:
    def test_every_key_declares_a_probe(self):
        """`check` reads `key.probe` unconditionally, so a gap is a KeyError."""
        for key in ToolKey:
            assert key.probe.args is not None, key

    def test_the_probe_never_does_work(self):
        """A version banner, or nothing at all. ⛔ Never a convert or a build."""
        for key in ToolKey:
            assert all(arg.startswith("-") for arg in key.probe.args), key

    def test_dolphin_tool_is_judged_on_starting_at_all(self):
        """It has no top-level --version or --help and answers a bare run with
        its usage and EXIT_FAILURE, which still proves the binary executes."""
        assert ToolKey.DOLPHIN_TOOL.probe.args == []
        assert not ToolKey.DOLPHIN_TOOL.probe.expect_success


class TestDistinctOutcomes:
    """Three failures that look alike from a traceback and are not alike here."""

    def test_absent_is_not_a_problem(self, searches, runs):
        searches({})
        runs(_completed(0))
        status = doctor.check(ToolKey.WIT)
        assert status.state is ToolState.ABSENT
        assert not status.is_problem
        assert "not found" in status.detail

    def test_an_override_pointing_nowhere_is_misconfiguration(self, searches, runs):
        searches({ToolKey.WIT: _broken(ToolKey.WIT)})
        runs(_completed(0))
        status = doctor.check(ToolKey.WIT)
        assert status.state is ToolState.BAD_OVERRIDE
        assert status.is_problem
        assert "BLECK_WIT" in status.detail

    def test_present_but_exiting_non_zero_is_its_own_answer(self, searches, runs):
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(_completed(2, stderr="wit: cannot load libfoo.so\n"))
        status = doctor.check(ToolKey.WIT)
        assert status.state is ToolState.ERRORED
        assert status.is_problem
        assert "cannot load libfoo.so" in status.detail
        assert status.path == FAKE

    def test_the_three_are_distinguishable(self, searches, runs):
        """⚠️ The point of the enum: one message for all three would be the bug
        this command exists to remove."""
        runs(_completed(2))
        states = set()
        for answer in (_absent, _broken, _found):
            searches({ToolKey.WIT: answer(ToolKey.WIT)})
            states.add(doctor.check(ToolKey.WIT).state)
        assert len(states) == 3

    def test_a_working_tool_records_where_it_came_from(self, searches, runs):
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(_completed(0))
        status = doctor.check(ToolKey.WIT)
        assert status.is_working
        assert status.where == "PATH"


class TestPresenceIsNotUsability:
    """The macOS trap: on disk, described, and dead."""

    def test_a_killed_binary_is_not_reported_as_working(self, searches, runs):
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(_completed(-9))
        status = doctor.check(ToolKey.WIT)
        assert status.state is ToolState.KILLED
        assert status.is_problem
        assert "signal 9" in status.detail

    def test_the_macos_remedy_is_named_in_full(self, monkeypatch, searches, runs):
        """⚠️ A bare "failed" here is what leaves a user staring at nothing."""
        monkeypatch.setattr(disc.platforms, "current", lambda: platforms.macos.PROFILE)
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(_completed(-9))
        status = doctor.check(ToolKey.WIT)
        assert "codesign --sign -" in status.remedy
        assert FAKE in status.remedy

    def test_platforms_without_the_gate_promise_nothing(
        self, monkeypatch, searches, runs
    ):
        """Only Apple Silicon kills unsigned code; inventing a fix elsewhere
        would be the same class of lie this work exists to remove."""
        monkeypatch.setattr(disc.platforms, "current", lambda: platforms.linux.PROFILE)
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(_completed(-9))
        assert doctor.check(ToolKey.WIT).remedy == ""

    def test_a_process_that_cannot_start_is_reported(self, searches, runs):
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(OSError("Exec format error"))
        status = doctor.check(ToolKey.WIT)
        assert status.state is ToolState.UNRUNNABLE
        assert "Exec format error" in status.detail

    def test_a_tool_that_never_answers_is_reported(self, searches, runs):
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(subprocess.TimeoutExpired(cmd=FAKE, timeout=doctor.PROBE_TIMEOUT))
        assert doctor.check(ToolKey.WIT).state is ToolState.UNRUNNABLE

    def test_no_run_skips_the_proof(self, searches, runs):
        """⚠️ Which is why `--no-run` says so in its own help text."""
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(_completed(-9))
        assert doctor.check(ToolKey.WIT, run=False).is_working

    def test_a_usage_message_still_counts_as_running(self, searches, runs):
        """dolphin-tool run bare exits non-zero by design."""
        searches({ToolKey.DOLPHIN_TOOL: _found(ToolKey.DOLPHIN_TOOL)})
        runs(_completed(1, stdout="usage: dolphin-tool COMMAND -h"))
        assert doctor.check(ToolKey.DOLPHIN_TOOL).is_working


@dataclass(frozen=True)
class Run:
    """One `bleck doctor` invocation: what it said and what it returned."""

    code: int
    out: str


def _doctor(capsys) -> Run:
    code = cli.main(["doctor"])
    return Run(code, capsys.readouterr().out)


class TestExitCode:
    """Absent is not the same as broken, and the exit status has to say so."""

    def test_a_machine_with_no_tools_at_all_is_not_an_error(self, searches, runs, capsys):
        searches({})
        runs(_completed(0))
        result = _doctor(capsys)
        assert result.code == 0
        assert "5 absent" in result.out
        assert "Absent is not an error" in result.out

    def test_one_broken_override_fails_the_whole_run(self, searches, runs, capsys):
        searches({ToolKey.DOLPHIN: _broken(ToolKey.DOLPHIN)})
        runs(_completed(0))
        result = _doctor(capsys)
        assert result.code == 1
        assert "1 misconfigured" in result.out

    def test_a_tool_that_will_not_run_fails_the_run(self, searches, runs, capsys):
        searches({ToolKey.WIT: _found(ToolKey.WIT)})
        runs(_completed(-9))
        assert _doctor(capsys).code == 1

    def test_every_problem_is_reported_not_just_the_first(self, searches, runs, capsys):
        searches(
            {
                ToolKey.WIT: _broken(ToolKey.WIT),
                ToolKey.DOLPHIN: _broken(ToolKey.DOLPHIN),
            }
        )
        runs(_completed(0))
        result = _doctor(capsys)
        assert result.code == 1
        assert "BLECK_WIT" in result.out
        assert "BLECK_DOLPHIN" in result.out


class TestReport:
    @pytest.fixture(autouse=True)
    def _all_absent(self, searches, runs):
        searches({})
        runs(_completed(0))

    def test_every_tool_appears(self, capsys):
        cli.main(["doctor"])
        out = capsys.readouterr().out
        for key in ToolKey:
            assert str(key) in out, key

    def test_it_says_what_each_tool_gates(self, capsys):
        cli.main(["doctor"])
        out = capsys.readouterr().out
        assert "extract, build" in out
        assert "launch" in out

    def test_the_environment_is_reported_from_its_declarations(self, capsys):
        """`env.describe_all` is the list; doctor is its consumer rather than a
        second, drifting copy."""
        cli.main(["doctor"])
        out = capsys.readouterr().out
        assert "BLECK_MODS_DIR" in out
        assert "BLECK_SYMBOLS_DIR" in out


class TestPreflight:
    """Declared needs are checked before dispatch, and only unconditional ones
    are declared."""

    def _parse(self, argv: list[str]) -> argparse.Namespace:
        return cli.build_parser().parse_args(argv)

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["extract", "game.iso"], [ToolKey.WIT]),
            (["build", "dir", "out.iso"], [ToolKey.WIT]),
            (["launch", "out.iso"], [ToolKey.DOLPHIN]),
            (["script", "build", "a.evt"], [ToolKey.PPC_GCC]),
        ],
    )
    def test_a_command_declares_what_it_cannot_start_without(
        self, argv: list[str], expected: list[ToolKey]
    ):
        assert requirements.declared(self._parse(argv)) == expected

    def test_mod_build_declares_nothing(self):
        """⛔ Load-bearing. `--output none` writes no image and a mod with no C
        sources needs no compiler, so a static requirement here would refuse
        work that succeeds today."""
        assert not requirements.declared(self._parse(["mod", "build", "demo"]))

    def test_reading_a_script_needs_no_compiler(self):
        """`check` and `dump` stop at the generated C."""
        assert not requirements.declared(self._parse(["script", "check", "a.evt"]))
        assert not requirements.declared(self._parse(["script", "dump", "a.evt"]))

    def test_extract_does_not_demand_the_rvz_converter(self):
        """dolphin-tool is needed only for an RVZ input, which is a property of
        the file named, not of the command."""
        declared = requirements.declared(self._parse(["extract", "game.iso"]))
        assert ToolKey.DOLPHIN_TOOL not in declared

    def test_a_missing_tool_stops_the_command_before_it_runs(self, monkeypatch, capsys):
        monkeypatch.setattr(requirements, "locate", _absent)
        assert cli.main(["launch", "nothing.iso"]) == 1
        err = capsys.readouterr().err
        assert "bleck launch" in err
        assert "dolphin" in err
        assert "bleck doctor" in err

    def test_a_satisfied_command_is_not_intercepted(self, monkeypatch, capsys):
        monkeypatch.setattr(requirements, "locate", _found)
        assert cli.main(["launch", "nothing.iso"]) == 1
        assert "no such image" in capsys.readouterr().err

    def test_every_unmet_need_is_named_at_once(self):
        report = requirements.Preflight(
            "bleck demo", [_absent(ToolKey.WIT), _absent(ToolKey.DOLPHIN)]
        )
        message = report.message()
        assert "wit" in message and "dolphin" in message
        assert "bleck doctor" in message

    def test_the_full_command_name_is_reported(self):
        """A nested command must not report itself as its top-level group."""
        args = self._parse(["script", "build", "a.evt"])
        assert requirements.preflight(args).invocation == "bleck script build"


class TestRolesMatchTheParser:
    """The gate table and the declarations cannot be allowed to drift apart."""

    def test_required_by_is_what_the_commands_actually_declare(self):
        declared: dict[ToolKey, set[str]] = {key: set() for key in ToolKey}
        for parser in _every_parser(cli.build_parser()):
            name = parser.prog.removeprefix("bleck ")
            for key in parser.get_default(requirements.REQUIRES) or ():
                declared[key].add(name)

        for role in requirements.ROLES:
            assert set(role.required_by) == declared[role.key], role.key

    def test_every_tool_key_has_a_role(self):
        described = {role.key for role in requirements.ROLES}
        assert described == set(ToolKey)

    def test_a_tool_nothing_needs_still_says_what_it_is_for(self):
        for role in requirements.ROLES:
            assert role.required_by or role.optional_for, role.key


def _every_parser(parser: argparse.ArgumentParser):
    """Walk the whole command tree, nested subcommands included.

    argparse exposes no public way to enumerate subparsers; the alternative is
    a hand-written list of commands, which is the drift this guards against.
    """
    for action in parser._actions:  # pylint: disable=protected-access
        if isinstance(action, argparse._SubParsersAction):  # pylint: disable=protected-access
            for child in action.choices.values():
                yield child
                yield from _every_parser(child)


class TestHintsThatUsedToLie:
    def test_no_platform_offers_a_command_that_does_not_exist(self):
        """⛔ `bleck toolchain install` was in three profiles and is not a
        command (D239, D274)."""
        for profile in ALL_PROFILES:
            for key in ToolKey:
                assert "toolchain install" not in profile.tool(key).hint, profile.name

    def test_every_compiler_hint_names_a_real_installer(self):
        for profile in ALL_PROFILES:
            hint = profile.tool(ToolKey.PPC_GCC).hint
            assert "devkitpro" in hint.lower(), profile.name
            assert "http" in hint or "apt install" in hint, profile.name

    def test_macos_does_not_send_users_to_the_debian_installer(self):
        """⛔ `apt.devkitpro.org/install-devkitpro-pacman` is Debian's."""
        hint = platforms.macos.PROFILE.tool(ToolKey.PPC_GCC).hint
        assert "apt.devkitpro.org" not in hint
        assert "dkp-pacman -S gamecube-dev" in hint

    def test_macos_stops_claiming_the_bundle_ships_dolphin_tool(self):
        """✅ Measured on an Apple Silicon MacBook installed from the Homebrew
        cask: the bundle's eight executables do not include it (D274)."""
        hint = platforms.macos.PROFILE.tool(ToolKey.DOLPHIN_TOOL).hint
        assert "does not ship dolphin-tool" in hint
        assert "brew install --cask dolphin" not in hint

    def test_macos_gives_the_two_things_that_do_work(self):
        """Neither of them is an install, because there is nothing to install."""
        hint = platforms.macos.PROFILE.tool(ToolKey.DOLPHIN_TOOL).hint
        assert "Convert File" in hint
        assert ".wbfs" in hint

    def test_only_macos_carries_a_signing_remedy(self):
        assert platforms.macos.PROFILE.signing_remedy
        assert not platforms.linux.PROFILE.signing_remedy
        assert not platforms.windows.PROFILE.signing_remedy

    def test_the_signing_remedy_takes_the_path_it_is_given(self):
        remedy = platforms.macos.PROFILE.signing_remedy
        assert remedy.format(path="/usr/local/bin/wit").endswith("/usr/local/bin/wit")


class TestUnreadableDiscSaysWhy:
    """⚠️ The bug this replaced: `identify` caught a DiscError naming the exact
    tool and the platform's advice, threw it away, and printed a guess with an
    `or` in it -- to the one person who could not answer the question.
    """

    @pytest.fixture
    def image(self, tmp_path: Path) -> Path:
        path = tmp_path / "spm_eu.rvz"
        path.write_bytes(b"RVZ\x01not really")
        return path

    def test_the_reason_reaches_the_user(self, monkeypatch, image: Path, capsys):
        monkeypatch.setattr(disc, "locate", _absent)
        assert cli.main(["info", str(image)]) == 0
        out = capsys.readouterr().out
        assert "dolphin-tool not found" in out
        assert "bleck doctor" in out

    def test_it_no_longer_asks_the_user_a_question(self, monkeypatch, image, capsys):
        monkeypatch.setattr(disc, "locate", _absent)
        cli.main(["info", str(image)])
        assert "installed?" not in capsys.readouterr().out

    def test_wit_is_not_offered_for_an_rvz(self, monkeypatch, image: Path, capsys):
        """It cannot read the format, so naming it is half a sentence of noise."""
        monkeypatch.setattr(disc, "locate", _absent)
        cli.main(["info", str(image)])
        assert "wit" not in capsys.readouterr().out

    def test_a_broken_override_names_the_variable(self, monkeypatch, image, capsys):
        monkeypatch.setattr(disc, "locate", _broken)
        cli.main(["info", str(image)])
        assert "BLECK_DOLPHIN_TOOL" in capsys.readouterr().out

    def test_the_platform_hint_travels_with_it(self, monkeypatch, image, capsys):
        """On macOS the honest answer is that the RVZ path is unavailable, not
        that something is unconfigured -- there is nothing to install.

        ⚠️ The real `locate` runs here, against a substituted profile: the
        wiring from a platform's hint to what a user reads is the thing under
        test, and stubbing the search would skip all of it.
        """
        monkeypatch.setattr(disc.platforms, "current", lambda: platforms.macos.PROFILE)
        monkeypatch.delenv(ToolKey.DOLPHIN_TOOL.override.name, raising=False)
        monkeypatch.setattr(disc.shutil, "which", lambda _name: None)
        assert cli.main(["info", str(image)]) == 0
        out = capsys.readouterr().out
        assert "does not ship dolphin-tool" in out
        assert "Convert File" in out

    def test_a_tool_that_ran_and_failed_is_quoted(self, monkeypatch, image, capsys):
        monkeypatch.setattr(disc, "locate", _found)
        monkeypatch.setattr(
            disc.subprocess,
            "run",
            lambda *_a, **_k: _completed(1, stderr="Error: Unable to open disc image"),
        )
        cli.main(["info", str(image)])
        assert "Unable to open disc image" in capsys.readouterr().out

    def test_a_killed_tool_does_not_report_as_silence(self, monkeypatch, image, capsys):
        """⚠️ `wit failed:` with nothing after the colon was the macOS failure
        mode nobody could act on."""
        monkeypatch.setattr(disc.platforms, "current", lambda: platforms.macos.PROFILE)
        monkeypatch.setattr(disc, "locate", _found)
        monkeypatch.setattr(disc.subprocess, "run", lambda *_a, **_k: _completed(-9))
        cli.main(["info", str(image)])
        out = capsys.readouterr().out
        assert "killed" in out
        assert "codesign" in out
