"""The C headers `bleck` puts on every mod's include path.

⚠️ **A header is shipped code that nothing compiles.** `bleck.h` and
`animdrv.h` reach every code mod through `-I`, and a wrong offset in one is a
mod that builds, links, boots and reads the wrong field — which is the failure
these exist to make loud.

`animdrv.h` records what this project measured about the animation driver
(D288 to D292). Its `AnimNode` is asserted field by field against the offsets the
game's own walker uses; the rest of the file is `#define`s precisely because
their padding is *not* established, and a struct would assert one.
"""

from __future__ import annotations

import subprocess

import pytest

from bleck import platforms
from bleck.backends.disc import DiscError, find_tool
from bleck.mods.code.sources import BLECK_INCLUDE

#: Offsets the walker at `0x80048c48` uses, and the stride `mulli r0,r4,88`
#: gives it. ⚠️ Kept here as literals rather than imported from the header, so
#: the test disagrees with the header rather than agreeing with itself.
NODE_FIELDS = (
    ("previousSibling", 0x40),
    ("lastChild", 0x44),
    ("shape", 0x48),
    ("index", 0x4C),
    ("transformWords", 0x50),
    ("flag54", 0x54),
)
NODE_STRIDE = 88


def _compiler():
    """devkitPPC's `gcc`, or a skip. It is the compiler mods really use."""
    try:
        return find_tool(platforms.ToolKey.PPC_GCC)
    except DiscError:
        return None


class TestTheHeadersExist:
    """These are on the include path whether a mod asks for them or not."""

    def test_every_shipped_header_is_a_header(self):
        found = sorted(path.name for path in BLECK_INCLUDE.iterdir())
        assert found == ["animdrv.h", "bleck.h"], found

    def test_the_spec_bundles_every_one_of_them(self):
        """⛔ **`doorcatalog.json` shipped unbundled through three releases**,
        and these have exactly its shape: found through `Path(__file__)`, so a
        frozen build looks for them inside the extraction directory.

        ⚠️ Derived from the directory rather than from a list, so a header added
        later is caught by this test instead of by a user.

        The failure is worse than the catalog's was — an unbundled header does
        not report itself, it makes the *compiler* fail on a mod that is
        correct, which reads as a broken toolchain.
        """
        spec = (BLECK_INCLUDE.parent.parent.parent.parent / "bleck.spec").read_text(
            encoding="utf-8"
        )
        for header in sorted(BLECK_INCLUDE.iterdir()):
            relative = f"bleck/mods/code/include/{header.name}"
            assert relative in spec, (
                f"{header.name} is on every mod's -I path and bleck.spec does "
                f"not bundle it: a frozen build cannot compile a mod using it"
            )

    def test_animdrv_records_where_its_facts_came_from(self):
        """⚠️ An address with no entry behind it cannot be re-checked, and this
        file is nothing but addresses."""
        text = (BLECK_INCLUDE / "animdrv.h").read_text(encoding="utf-8")
        for entry in ("D288", "D289", "D290", "D291", "D292"):
            assert entry in text, f"{entry} is not cited"

    def test_animdrv_says_which_game_version_it_is_for(self):
        text = (BLECK_INCLUDE / "animdrv.h").read_text(encoding="utf-8")
        assert "eu0" in text, "every address here is PAL rev 0 and must say so"

    def test_the_addresses_match_what_was_measured(self):
        """The three entry points, as literals rather than as a re-read."""
        text = (BLECK_INCLUDE / "animdrv.h").read_text(encoding="utf-8")
        for address in ("0x805ADF58", "0x80045288", "0x80048c48", "0x8004158c"):
            assert address in text, f"{address} is missing"


class TestTheNodeStructMatchesTheGame:
    """✅ `AnimNode` is the one struct here, because it is the one whose fields
    are contiguous and individually read by the walker (D292)."""

    @pytest.fixture(name="compiler")
    def _fixture_compiler(self):
        found = _compiler()
        if not found:
            pytest.skip("no devkitPPC on this machine")
        return found

    def test_the_offsets_hold_on_the_target_compiler(self, compiler, tmp_path):
        """⚠️ Compiled for **powerpc-eabi**, not for the host. A struct that
        lays out correctly on x86-64 and wrongly on the Wii would pass a host
        check and ship the bug.
        """
        checks = "\n".join(
            f"CHECK(__builtin_offsetof(AnimNode, {name}) == {at:#x});"
            for name, at in NODE_FIELDS
        )
        source = tmp_path / "check.c"
        source.write_text(
            "#include <animdrv.h>\n"
            "#define CHECK(c) extern char _chk[(c) ? 1 : -1]\n"
            f"CHECK(sizeof(AnimNode) == {NODE_STRIDE});\n"
            f"{checks}\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                str(compiler),
                f"-I{BLECK_INCLUDE}",
                "-c",
                str(source),
                "-o",
                str(tmp_path / "check.o"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_a_wrong_offset_would_actually_fail(self, compiler, tmp_path):
        """🟢 The control. A negative-size array is only a compile error if the
        compiler evaluates it, and a check that cannot fail proves nothing."""
        source = tmp_path / "control.c"
        source.write_text(
            "#include <animdrv.h>\n"
            "#define CHECK(c) extern char _chk[(c) ? 1 : -1]\n"
            "CHECK(__builtin_offsetof(AnimNode, shape) == 0x99);\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                str(compiler),
                f"-I{BLECK_INCLUDE}",
                "-c",
                str(source),
                "-o",
                str(tmp_path / "control.o"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, "a deliberately wrong offset compiled"
