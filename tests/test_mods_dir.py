"""`--mods-dir`, and the parser trap that makes it worth testing.

The flag exists because `mods/` is now the user's own directory and the shipped
examples live in `example-mods/` (D147). Every one of these tests would have
passed trivially before that split; what they actually pin is that the flag
reaches *nested* subcommands, which `parents=` does not give for free.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bleck.cli import app as cli
from bleck.common import env
from bleck.mods import registry


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch):
    """`env.override` writes the real process environment, by design.

    ⚠️ Without this every test after one of these would see the last one's
    mods directory. `monkeypatch.setenv` is used only to establish a starting
    value; the undo is what matters.
    """
    monkeypatch.delenv(env.MODS_DIR.name, raising=False)


def a_mod(root: Path, name: str) -> Path:
    where = root / name
    where.mkdir(parents=True)
    (where / "mod.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", "description": name}),
        encoding="utf-8",
    )
    return where


class TestTheFlagChangesTheRoot:
    def test_a_top_level_command_sees_it(self, tmp_path: Path, capsys):
        a_mod(tmp_path, "over-here")
        assert cli.main(["mod", "list", "--mods-dir", str(tmp_path)]) == 0
        assert "over-here" in capsys.readouterr().out

    def test_a_nested_subcommand_sees_it(self, tmp_path: Path, capsys):
        """⚠️ The regression this file exists for.

        `bleck mod list` is a subparser of a subparser. `cli.app` applies
        `parents=[shared]` to `mod`, and that does **not** propagate to `list` --
        so a flag added only there parses at `bleck --mods-dir mod list` and
        fails at the position anyone would actually type it.
        """
        a_mod(tmp_path, "nested-ok")
        # The flag trailing the nested subcommand: the form users type.
        assert cli.main(["mod", "list", "--mods-dir", str(tmp_path)]) == 0
        assert "nested-ok" in capsys.readouterr().out

    def test_without_it_the_default_root_is_used(self, tmp_path: Path, capsys):
        a_mod(tmp_path, "invisible")
        assert cli.main(["mod", "list"]) == 0
        assert "invisible" not in capsys.readouterr().out


class TestPrecedence:
    def test_the_flag_beats_the_environment(self, tmp_path: Path, monkeypatch):
        """A path typed on the command line is more specific than one in `.env`."""
        chosen, ignored = tmp_path / "chosen", tmp_path / "ignored"
        a_mod(chosen, "wanted")
        a_mod(ignored, "unwanted")
        monkeypatch.setenv(env.MODS_DIR.name, str(ignored))

        cli.main(["mod", "list", "--mods-dir", str(chosen)])
        assert registry.mods_root() == chosen

    def test_the_environment_is_used_when_the_flag_is_absent(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setenv(env.MODS_DIR.name, str(tmp_path))
        cli.main(["mod", "list"])
        assert registry.mods_root() == tmp_path


class TestEveryCommandThatReadsMods:
    """A flag that works on some registry commands and not others is worse than
    one that works on none, because the failure is silent -- the command reads
    the *wrong* directory rather than refusing."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["mod", "list"],
            ["mod", "check", "probe"],
            ["mod", "build", "probe"],
            ["setup", "edits", "probe"],
            ["setup", "apply", "probe", "--json", "edits.json"],
        ],
    )
    def test_it_parses(self, argv: list[str]):
        parsed = cli.build_parser().parse_args([*argv, "--mods-dir", "somewhere"])
        assert parsed.mods_dir == "somewhere"


class TestTheShippedExamples:
    """`example-mods/` is a real directory in this repo, not a fixture."""

    def test_it_is_where_the_examples_live(self, capsys):
        examples = Path(__file__).resolve().parent.parent / "example-mods"
        if not examples.is_dir():
            pytest.skip("no example-mods/ in this checkout")
        assert cli.main(["mod", "list", "--mods-dir", str(examples)]) == 0
        assert "mr-l" in capsys.readouterr().out
