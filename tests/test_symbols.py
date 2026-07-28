"""Symbol tables, and the disagreements between the two sources.

The consequential test here is `compare`: the lst and the decomp are maintained
separately, and where they disagree one of them sends a call to the wrong
address. Two such cases exist in eu0 and neither was known before (D60).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bleck.backends import symbols

DECOMP = """\
memcpy = .init:0x80004000; // type:function size:0x50 scope:global
gTable = .init:0x80004188; // type:label scope:global
mapDataPtr = .text:0x800294E0; // type:function size:0xC8
lbl_80123456 = .data:0x80123456; // type:object size:0x4
func_80123460 = .text:0x80123460; // type:function size:0x20
@etb_800064E8 = extab:0x800064E8; // type:object size:0x8 scope:local hidden
"""

LST = """\
/* OS Globals */

80004000:memcpy
800294e0:mapDataPtr
80999999:onlyInTheLst
"""


@pytest.fixture(name="decomp")
def _decomp():
    return symbols.parse_decomp(DECOMP, Path("symbols.txt"))


@pytest.fixture(name="lst")
def _lst():
    return symbols.parse_lst(LST, Path("spm.eu0.lst"))


class TestParsing:
    def test_exception_tables_are_excluded(self, decomp):
        """`@etb_*` entries are compiler bookkeeping -- ~9,600 of them in the
        real file, and useless to a mod."""
        assert all(not s.name.startswith("@") for s in decomp.symbols)
        assert len(decomp.symbols) == 5

    def test_types_and_sizes_survive(self, decomp):
        found = decomp.find("mapDataPtr")
        assert found.is_function
        assert found.size == 0xC8
        assert found.section == "text"

    def test_generated_names_are_recognised(self, decomp):
        assert decomp.find("lbl_80123456").is_generated
        assert decomp.find("func_80123460").is_generated
        assert not decomp.find("mapDataPtr").is_generated

    def test_named_excludes_the_generated_ones(self, decomp):
        assert {s.name for s in decomp.named} == {"memcpy", "gTable", "mapDataPtr"}

    def test_the_lst_carries_only_names_and_addresses(self, lst):
        assert lst.find("mapDataPtr").address == 0x800294E0
        assert lst.find("mapDataPtr").kind == ""
        # Comments and blank lines must not become symbols.
        assert len(lst.symbols) == 3


class TestDisagreements:
    def test_matching_addresses_are_not_reported(self, lst, decomp):
        assert symbols.compare(lst, decomp) == []

    def test_a_differing_address_is_reported(self, decomp):
        moved = symbols.parse_lst("80000001:mapDataPtr\n", Path("x.lst"))
        found = symbols.compare(moved, decomp)
        assert len(found) == 1
        assert found[0].name == "mapDataPtr"
        assert found[0].lst_address == 0x80000001
        assert found[0].decomp_address == 0x800294E0

    def test_a_name_only_one_side_knows_is_not_a_disagreement(self, lst, decomp):
        assert not any(d.name == "onlyInTheLst" for d in symbols.compare(lst, decomp))


class TestMerging:
    def test_the_decomp_wins_a_disagreement(self, decomp):
        """Every real disagreement so far had the lst pointing at the
        *neighbouring* function, which the decomp also names (D60)."""
        stale = symbols.parse_lst("80000001:mapDataPtr\n", Path("x.lst"))
        merged = symbols.merge(stale, decomp)
        assert merged.find("mapDataPtr").address == 0x800294E0

    def test_names_only_the_lst_has_are_kept(self, lst, decomp):
        assert symbols.merge(lst, decomp).find("onlyInTheLst") is not None

    def test_merging_keeps_the_types(self, lst, decomp):
        # The lst format cannot carry a type, so a shared name must not lose it.
        assert symbols.merge(lst, decomp).find("mapDataPtr").is_function

    def test_generated_names_do_not_pollute_the_merge(self, lst, decomp):
        assert symbols.merge(lst, decomp).find("lbl_80123456") is None


class TestExport:
    def test_the_written_file_reads_back(self, tmp_path, lst, decomp):
        out = tmp_path / "merged.lst"
        merged = symbols.merge(lst, decomp)
        count = symbols.write_lst(merged, out, note="test")
        assert count == len(merged.symbols)

        again = symbols.read(out)
        assert {s.name for s in again.symbols} == {s.name for s in merged.symbols}
        assert again.find("mapDataPtr").address == 0x800294E0

    def test_the_format_is_what_elf2rel_reads(self, tmp_path, lst, decomp):
        out = tmp_path / "merged.lst"
        symbols.write_lst(symbols.merge(lst, decomp), out)
        body = out.read_text(encoding="utf-8")
        assert "800294e0:mapDataPtr" in body

    def test_a_missing_table_says_so(self, tmp_path):
        with pytest.raises(symbols.SymbolError, match="no symbol table"):
            symbols.read(tmp_path / "absent.lst")
