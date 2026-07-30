"""The generated reference pages must be valid Markdown, not just present.

⚠️ Both bugs pinned here shipped, and neither was visible from the generator's
source:

- A `<small>` tag landed **inside** a code span, where Markdown renders its
  contents literally. 280 rows carried a visible `<small>(not documented)`.
- The table header said four columns while every row wrote five, because a
  `str.replace` adding the header silently matched nothing. The generator ran
  clean and the page was malformed.

`--check` compares the file to the generator's output, so it catches *drift*.
It cannot catch either of these: it would have compared wrong output to wrong
output and passed.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

PAGES = [
    REPO / "docs-site" / "scripting" / "builtins.md",
    REPO / "docs-site" / "scripting" / "storage.md",
]

#: The generated-by banner is the one tag allowed, and it is a comment.
ALLOWED_HTML = ("<!--",)


@dataclass(frozen=True)
class Row:
    """One line of a Markdown table."""

    number: int
    text: str

    @property
    def columns(self) -> int:
        return self.text.count("|") - 1


@dataclass(frozen=True)
class Table:
    """A header, its separator, and the rows beneath it."""

    header: Row
    separator: Row
    rows: list[Row] = field(default_factory=list)


def _is_separator(line: str) -> bool:
    stripped = line.replace("|", "").replace(" ", "")
    return line.startswith("|") and bool(stripped) and set(stripped) <= {"-", ":"}


def tables(text: str) -> list[Table]:  # pylint: disable=container-return
    """Every table, found by structure rather than by guessing.

    ⛔ **Not "a new table starts wherever the width changes".** That was the
    first version, and it swallowed the exact bug this file exists to catch:
    a header one column narrower than its rows read as two adjacent tables.
    A table is a header line, a separator line, then rows -- nothing else
    starts one.
    """
    lines = text.splitlines()
    found: list[Table] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("|") or index + 1 >= len(lines):
            index += 1
            continue
        if not _is_separator(lines[index + 1]):
            index += 1
            continue

        rows: list[Row] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].startswith("|"):
            rows.append(Row(cursor + 1, lines[cursor]))
            cursor += 1
        found.append(
            Table(
                header=Row(index + 1, line),
                separator=Row(index + 2, lines[index + 1]),
                rows=rows,
            )
        )
        index = cursor
    return found


@dataclass(frozen=True)
class Page:
    """One generated page and its text."""

    path: Path
    text: str

    @property
    def name(self) -> str:
        return self.path.name


@pytest.fixture(name="pages", scope="module")
def _pages() -> list[Page]:
    missing = [p for p in PAGES if not p.is_file()]
    if missing:
        pytest.skip(f"not generated: {missing}")
    return [Page(path, path.read_text(encoding="utf-8")) for path in PAGES]


class TestNoRawHtml:
    def test_no_html_tags_survive_into_the_page(self, pages):
        """⛔ Markdown, not HTML. A tag inside backticks renders as text."""
        for page in pages:
            for number, line in enumerate(page.text.splitlines(), start=1):
                if line.startswith(ALLOWED_HTML):
                    continue
                found = re.search(r"</?[a-zA-Z][^>]*>", line)
                assert not found, f"{page.name}:{number} has HTML: {found.group(0)}"

    def test_nothing_is_tagged_inside_a_code_span(self, pages):
        """The specific shape that shipped: `code <small>text</small>`."""
        for page in pages:
            for number, line in enumerate(page.text.splitlines(), start=1):
                for span in re.findall(r"`([^`]*)`", line):
                    assert "<" not in span, f"{page.name}:{number}: `{span}`"


class TestTablesAreWellFormed:
    def test_the_pages_contain_tables_at_all(self, pages):
        """⚠️ Guards the guard: a parser that finds nothing passes everything."""
        for page in pages:
            assert tables(page.text), (
                f"{page.name}: no tables found, so nothing below ran"
            )

    def test_every_separator_matches_its_header(self, pages):
        for page in pages:
            for table in tables(page.text):
                assert table.separator.columns == table.header.columns, (
                    f"{page.name}:{table.separator.number}: separator has "
                    f"{table.separator.columns} columns, header at line "
                    f"{table.header.number} has {table.header.columns}"
                )

    def test_every_row_matches_its_header(self, pages):
        """⛔ A row wider than its header loses cells when rendered.

        This shipped: the header said four columns and every row wrote five,
        because a `str.replace` adding the header silently matched nothing.
        """
        for page in pages:
            for table in tables(page.text):
                for row in table.rows:
                    assert row.columns == table.header.columns, (
                        f"{page.name}:{row.number}: row has {row.columns} "
                        f"columns, header at line {table.header.number} has "
                        f"{table.header.columns}"
                    )


class TestTheGeneratorStaysHonest:
    def test_the_page_is_up_to_date(self):
        """The same check CI runs, so a stale page fails here too."""
        import dump_builtins  # pylint: disable=import-outside-toplevel,import-error

        assert dump_builtins.main(["--check"]) == 0

    def test_every_module_has_a_description(self):
        """⚠️ A module added upstream must not appear with no prose."""
        import dump_builtins  # pylint: disable=import-outside-toplevel,import-error
        import module_notes  # pylint: disable=import-outside-toplevel,import-error

        modules = {entry.module for entry in dump_builtins.load()}
        missing = sorted(modules - set(module_notes.NOTES))
        assert not missing, f"no description for: {missing}"

    def test_measured_entries_all_name_a_real_builtin(self):
        """A typo in `measured.json` would silently document nothing."""
        import dump_builtins  # pylint: disable=import-outside-toplevel,import-error

        known = {entry.name for entry in dump_builtins.load()}
        unknown = sorted(set(dump_builtins.load_measured()) - known)
        assert not unknown, f"measured.json names unknown builtins: {unknown}"
