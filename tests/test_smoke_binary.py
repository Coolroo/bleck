"""`scripts/smoke_binary.py` must assert something that can still fail.

The smoke script only ever runs against a PyInstaller artifact, which CI builds
and nobody builds locally, so an assertion can go stale for a whole release
cycle before anyone sees it. That is what happened: it asked for the item
`fire_burst` and its English name `Fire Burst`, D194 stopped shipping the game's
own words, and all three platforms then failed the same assertion about a fact
that no longer existed.

Two halves, and the second is the one that earns its keep:

1. every check still matches what the CLI prints today
2. every catalog check **stops** matching when its catalog is taken away

Without (2) a check can be satisfied by output that proves nothing: ids and
`ITEM_ID_*` constants come from generated modules (D119) and print from a binary
carrying no item catalog at all, and `ITEM_ID_NULL` contains the internal name
`NULL` as a substring.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from bleck import cli
from bleck.backends import doors, maps
from bleck.cli.commands import inspect, scripts
from bleck.formats import items

REPO = Path(__file__).resolve().parent.parent

#: `Path(__file__).with_name("something.json")` -- how every catalog is found,
#: and the reason `bleck.spec` has to mirror the package layout.
LOADED = re.compile(r'with_name\(\s*"([^"]+\.json)"\s*\)')


def load_script() -> ModuleType:
    """`scripts/` is not a package, so it is imported by path."""
    sys.path.insert(0, str(REPO / "scripts"))
    import smoke_binary  # pylint: disable=import-outside-toplevel,import-error

    return smoke_binary


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    return load_script()


@dataclass(frozen=True)
class Result:
    """What the CLI did with one check's arguments."""

    code: int
    out: str


@pytest.fixture(autouse=True)
def fresh_catalog():
    """⚠️ `items.catalog` is cached and these tests move `BLECK_BASE_DIR`.

    Without clearing it either side, a session leaks: this file would inherit
    the English tier from a developer's extracted disc, and every later test
    would inherit the blank one from here.
    """
    items.catalog.cache_clear()
    yield
    items.catalog.cache_clear()


@pytest.fixture
def disc(tmp_path: Path, smoke: ModuleType) -> Path:
    """The same synthetic one-map base the smoke script builds."""
    sample = smoke.first("bleck/backends/mapcatalog.json", "maps")
    return smoke.synthetic_base(tmp_path / "base", sample.name)


@pytest.fixture
def blank(tmp_path: Path) -> Path:
    """An empty directory, standing in for "this machine has no disc".

    ⚠️ Not an unset variable: `BLECK_BASE_DIR` has a default, so leaving it
    alone would read whatever the developer has extracted and put English item
    names in the output that CI never sees.
    """
    root = tmp_path / "blank"
    root.mkdir()
    return root


def invoke(check, base: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> Result:
    """Run one check's arguments against the in-process CLI."""
    monkeypatch.setenv("BLECK_BASE_DIR", str(base))
    try:
        code = cli.main(check.args)
    except SystemExit as stop:
        # `--help` exits rather than returning; argparse's success is 0.
        code = int(stop.code or 0)
    return Result(code=code, out=capsys.readouterr().out)


def satisfied(smoke: ModuleType, check, out: str) -> bool:
    """Whether output meets a check, by the smoke script's own rules."""
    if any(wanted not in out for wanted in check.expect):
        return False
    if check.fields and not smoke.line_with(out, check.fields):
        return False
    if check.json_out:
        try:
            json.loads(out)
        except json.JSONDecodeError:
            return False
    return True


def named(smoke: ModuleType, name: str):
    """One check by name, so a rename fails loudly instead of silently
    skipping the negative control that matters most."""
    sample = smoke.first("bleck/backends/mapcatalog.json", "maps")
    for check in smoke.checks(sample):
        if check.name == name:
            return check
    raise AssertionError(f"smoke_binary.py has no check named {name!r}")


class TestTheChecksMatchTheCli:
    """Half one: what the smoke script asks for is what the CLI prints."""

    def test_every_check_passes(
        self, smoke: ModuleType, disc: Path, blank: Path, monkeypatch, capsys
    ):
        sample = smoke.first("bleck/backends/mapcatalog.json", "maps")
        for check in smoke.checks(sample):
            base = disc if check.needs_base else blank
            result = invoke(check, base, monkeypatch, capsys)
            assert result.code == 0, f"{check.name}: exited {result.code}"
            assert satisfied(smoke, check, result.out), (
                f"{check.name}: output does not meet the check\n{result.out[:400]}"
            )

    def test_no_check_names_a_catalog_row(self):
        """The rot itself: a literal row name written into the script.

        ⚠️ The module docstring is excluded, because explaining which name went
        stale means naming it. Everything below the docstring must have come
        out of a committed catalog.
        """
        source = (REPO / "scripts" / "smoke_binary.py").read_text(encoding="utf-8")
        code = source.replace(ast.get_docstring(ast.parse(source)) or "", "")
        for gone in ("fire_burst", "Fire Burst", "he1_01", "evt_pouch"):
            assert gone not in code, (
                f"{gone!r} is written into smoke_binary.py; read it from the "
                f"catalog instead, or it will rot the way `fire_burst` did"
            )


class TestTheChecksCanFail:
    """Half two: take a catalog away and its check must notice.

    ⚠️ The repo's own methodology rule -- before trusting that a check works,
    show it failing. Each of these also asserts that the command still *ran*,
    so "it failed because nothing printed" cannot pass for "it failed because
    the catalog was missing".
    """

    def test_the_item_check_needs_the_item_catalog(
        self, smoke: ModuleType, blank: Path, tmp_path: Path, monkeypatch, capsys
    ):
        check = named(smoke, "item catalog is bundled")
        # The JSON, not the loader: a frozen binary missing the data file finds
        # exactly this, and `items.catalog` stays a real cache for the teardown.
        monkeypatch.setattr(items, "ITEM_CATALOG", tmp_path / "absent.json")
        items.catalog.cache_clear()
        result = invoke(check, blank, monkeypatch, capsys)
        assert not satisfied(smoke, check, result.out)
        # The id still prints, so the line was there and the name column was
        # what went missing -- which is the whole point of asserting a column.
        assert check.fields[0] in result.out

    def test_the_map_check_needs_the_map_catalog(
        self, smoke: ModuleType, disc: Path, tmp_path: Path, monkeypatch, capsys
    ):
        check = named(smoke, "map catalog is bundled")
        monkeypatch.setattr(maps, "CATALOG", tmp_path / "absent.json")
        result = invoke(check, disc, monkeypatch, capsys)
        assert not satisfied(smoke, check, result.out)
        assert check.fields[1] in result.out

    def test_the_door_check_needs_the_door_catalog(
        self, smoke: ModuleType, blank: Path, monkeypatch, capsys
    ):
        check = named(smoke, "door catalog is bundled")
        monkeypatch.setattr(inspect.doors, "catalog", doors.DoorCatalog)
        result = invoke(check, blank, monkeypatch, capsys)
        assert result.code != 0
        assert not satisfied(smoke, check, result.out)

    def test_the_builtin_check_needs_the_builtin_catalog(
        self, smoke: ModuleType, blank: Path, monkeypatch, capsys
    ):
        check = named(smoke, "builtin catalog is bundled")
        empty = scripts.builtin_catalog.Catalog(builtins=[])
        monkeypatch.setattr(scripts.builtin_catalog, "load", lambda: empty)
        result = invoke(check, blank, monkeypatch, capsys)
        assert result.code != 0
        assert not satisfied(smoke, check, result.out)


def test_the_spec_bundles_every_catalog_the_code_loads():
    """⚠️ `doorcatalog.json` was loaded by `bleck doors` and bundled by nothing.

    A frozen binary started fine and told the user "no door catalog shipped
    with this build", which reads as a corrupt install rather than a packaging
    bug -- and no smoke check covered it, so three releases carried it.
    """
    spec = (REPO / "bleck.spec").read_text(encoding="utf-8")
    for module in sorted((REPO / "bleck").rglob("*.py")):
        for name in LOADED.findall(module.read_text(encoding="utf-8")):
            relative = f"{module.parent.relative_to(REPO).as_posix()}/{name}"
            assert (REPO / relative).is_file(), f"{module.name} loads a missing {name}"
            assert relative in spec, (
                f"{module.relative_to(REPO)} loads {name}, which bleck.spec does "
                f"not bundle: the frozen binary will report an empty catalog"
            )
