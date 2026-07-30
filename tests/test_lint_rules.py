"""The project's own lint rules, and the linter's file scoping.

⚠️ These exist because a checker that stops firing fails **silently** — it reports
zero problems, which is indistinguishable from a clean tree. That happened while
`comment_length` was being written: the plugin could not be imported, pylint said
nothing, and "0 violations" looked like success until a file with a known
5-line comment was run through it deliberately.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import lint  # pylint: disable=import-error,wrong-import-position

from lint_plugins.comment_length import (  # pylint: disable=wrong-import-position
    DIRECTIVE_PREFIXES,
    MAX_COMMENT_LINES,
    _comment_runs,
)


def runs(source: str) -> list[tuple[int, int]]:
    # pylint: disable=container-return  # mirrors the checker's own return
    return _comment_runs(source.encode("utf-8"))


def longest(source: str) -> int:
    found = runs(source)
    return max((length for _, length in found), default=0)


class TestCommentRuns:
    def test_a_run_of_four_is_measured_as_four(self):
        assert longest("# a\n# b\n# c\n# d\nx = 1\n") == 4

    def test_the_limit_is_three(self):
        """The rule as configured, so a change to the default is deliberate."""
        assert MAX_COMMENT_LINES == 3

    def test_code_between_comments_splits_the_run(self):
        assert longest("# a\n# b\nx = 1\n# c\n# d\n") == 2

    def test_a_blank_line_splits_the_run(self):
        """Two short blocks are two blocks, not one wall."""
        assert longest("# a\n# b\n\n# c\n# d\nx = 1\n") == 2

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        """⚠️ Why this uses `tokenize` rather than matching lines starting `#`."""
        assert longest('x = "# a"\ny = "# b"\nz = "# c"\nw = "# d"\n') == 0

    def test_a_trailing_comment_after_code_still_counts(self):
        assert longest("x = 1  # a\n# b\n# c\n# d\n") == 4


class TestExemptions:
    def test_attribute_docs_are_exempt(self):
        """`#:` is how this codebase documents a module constant."""
        assert not runs("#: a\n#: b\n#: c\n#: d\n#: e\nVALUE = 1\n")

    @pytest.mark.parametrize("directive", DIRECTIVE_PREFIXES)
    def test_a_directive_is_not_counted_as_prose(self, directive: str):
        """A `# pylint: disable` inside a block is not what makes it unreadable."""
        source = f"# a\n# b\n{directive} something\n# c\nx = 1\n"
        assert longest(source) == 3

    def test_an_unparseable_file_reports_nothing(self):
        """Broken syntax is pylint's error to raise, not this checker's."""
        assert not runs("def (\n# a\n")


class TestTheRepositoryPasses:
    """The rule is only meaningful if the tree actually satisfies it."""

    def test_no_source_file_has_a_long_comment_block(self):
        repo = Path(__file__).resolve().parent.parent
        offenders = []
        for target in lint.TARGETS:
            for path in (repo / target).rglob("*.py"):
                found = longest(path.read_text(encoding="utf-8"))
                if found > MAX_COMMENT_LINES:
                    offenders.append(f"{path.relative_to(repo)} ({found} lines)")
        assert not offenders, "comment blocks over the limit: " + ", ".join(offenders)


class TestChangedFileScoping:
    """`lint.py` defaults to the branch's diff; `--full` checks everything."""

    def test_it_only_returns_python_files_under_the_targets(self):
        for name in lint.changed_targets():
            assert name.endswith(".py")
            assert name.split("/")[0] in lint.TARGETS

    def test_every_returned_path_exists(self):
        """A deleted file must not be handed to ruff, which would error."""
        repo = Path(__file__).resolve().parent.parent
        for name in lint.changed_targets():
            assert (repo / name).exists(), name

    def test_full_mode_checks_the_target_roots(self):
        checks = lint.build_checks(sys.executable, fix=False, targets=lint.TARGETS)
        assert checks, "no checks built"
        for check in checks:
            assert lint.TARGETS[0] in check.args

    def test_a_missing_git_degrades_to_no_changes(self, monkeypatch):
        """No git, no diff -- and `main` must not crash because of it."""
        monkeypatch.setattr(lint, "_git", lambda *_: "")
        assert not lint.changed_targets()
