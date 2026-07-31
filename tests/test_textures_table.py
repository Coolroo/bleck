"""Texture edits declared in a table, and applied against the user's own disc.

⛔ **The load-bearing test is `TestNothingGameDerivedIsPacked`.** The entire
point of declaring a texture edit is that a `.bleck` carries no Nintendo bytes.
The generated texture lands in the overlay like any other build output, and if
`pack` does not recognise it as generated it classifies it as an *asset* and
ships it — which is what happened the first time this was wired up.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from bleck.formats import tpl
from bleck.formats.tables import textures as table
from bleck.mods import pack, registry, resolver
from bleck.mods.build import textures as build


def a_tpl(blocks: int = 2) -> bytes:
    """A one-image CMPR TPL, big enough to have endpoints worth changing."""
    import struct  # pylint: disable=import-outside-toplevel

    header_at, header_size = 20, 36
    data_at = header_at + header_size
    out = bytearray(struct.pack(">III", tpl.TPL_MAGIC, 1, 12))
    out += struct.pack(">II", header_at, 0)
    head = bytearray(header_size)
    struct.pack_into(">HHI", head, 0, 4, blocks * 4, int(tpl.Format.CMPR))
    struct.pack_into(">I", head, 8, data_at)
    out += head
    for index in range(blocks):
        out += struct.pack(">HH", 0xF800 + index, 0x001F) + b"\x1b\x1b\x1b\x1b"
    return bytes(out)


def a_mod(root: Path, rows: str, name: str = "paint") -> registry.Mod:
    where = root / name
    (where / "tables").mkdir(parents=True)
    (where / "mod.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "name": name,
                "version": "0.1.0",
                "description": name,
                "base": "eu0",
                "tables": {"textures": "tables/textures.csv"},
            }
        ),
        encoding="utf-8",
    )
    (where / "tables" / "textures.csv").write_text(
        "file,member,image,op,arg\n" + rows, encoding="utf-8"
    )
    return registry.load(root).require(name)


def a_base(root: Path) -> Path:
    base = root / "base" / "eu0"
    (base / "files").mkdir(parents=True)
    (base / "files" / "art.tpl").write_bytes(a_tpl())
    return base


class TestParsing:
    def test_a_row_becomes_an_edit(self):
        parsed = table.parse("file,op\nfiles/a.tpl,invert\n", "t.csv")
        assert len(parsed.edits) == 1
        assert parsed.edits[0].disc_path == "files/a.tpl"

    def test_an_empty_image_means_every_image(self):
        parsed = table.parse("file,image,op\nfiles/a.tpl,,invert\n", "t.csv")
        assert parsed.edits[0].image is None

    def test_an_operation_needing_an_argument_is_refused(self):
        """⛔ Never defaulted. A `tint` with no colour that became a no-op is a
        declared edit that does nothing and reports success (D126)."""
        with pytest.raises(table.TableError, match="needs a colour"):
            table.parse("file,op,arg\nfiles/a.tpl,tint,\n", "t.csv")

    def test_an_operation_taking_none_and_given_one_is_refused(self):
        with pytest.raises(table.TableError, match="takes no argument"):
            table.parse("file,op,arg\nfiles/a.tpl,invert,blue\n", "t.csv")

    def test_an_unknown_operation_lists_the_known_ones(self):
        with pytest.raises(table.TableError, match="brightness, greyscale"):
            table.parse("file,op\nfiles/a.tpl,wobble\n", "t.csv")

    def test_a_colour_parses_with_or_without_the_hash(self):
        for spelling in ("#8800ff", "8800ff"):
            parsed = table.parse(f"file,op,arg\nfiles/a.tpl,tint,{spelling}\n", "t.csv")
            assert "8800ff" in parsed.edits[0].operation.name


class TestApplying:
    def test_the_texture_is_written_into_the_overlay(self, tmp_path: Path):
        base = a_base(tmp_path)
        mod = a_mod(tmp_path / "mods", "files/art.tpl,,,invert,\n")
        built = build.apply_one(mod, base, build.edits_for(mod)[0])
        assert built.output.is_file()
        assert built.output == mod.overlay / "files/art.tpl"

    def test_the_pixels_actually_change(self, tmp_path: Path):
        base = a_base(tmp_path)
        mod = a_mod(tmp_path / "mods", "files/art.tpl,,,invert,\n")
        built = build.apply_one(mod, base, build.edits_for(mod)[0])
        assert built.output.read_bytes() != (base / "files" / "art.tpl").read_bytes()
        assert built.blocks == 2

    def test_identity_leaves_it_byte_for_byte(self, tmp_path: Path):
        """The acceptance property of the whole endpoint approach (D187)."""
        base = a_base(tmp_path)
        mod = a_mod(tmp_path / "mods", "files/art.tpl,,,brightness,1.0\n")
        built = build.apply_one(mod, base, build.edits_for(mod)[0])
        assert built.output.read_bytes() == (base / "files" / "art.tpl").read_bytes()

    def test_a_missing_file_names_itself(self, tmp_path: Path):
        base = a_base(tmp_path)
        mod = a_mod(tmp_path / "mods", "files/nope.tpl,,,invert,\n")
        with pytest.raises(build.TextureBuildError, match=r"files/nope\.tpl"):
            build.apply_one(mod, base, build.edits_for(mod)[0])

    def test_an_image_index_past_the_end_is_refused(self, tmp_path: Path):
        base = a_base(tmp_path)
        mod = a_mod(tmp_path / "mods", "files/art.tpl,,7,invert,\n")
        with pytest.raises(build.TextureBuildError, match="no image 7"):
            build.apply_one(mod, base, build.edits_for(mod)[0])

    def test_a_non_cmpr_image_warns_rather_than_failing_silently(self, tmp_path: Path):
        """⚠️ Neither applied nor ignored: the author is told which image and
        why, because a row that quietly does nothing is D126."""
        import struct  # pylint: disable=import-outside-toplevel

        base = a_base(tmp_path)
        raw = bytearray((base / "files" / "art.tpl").read_bytes())
        struct.pack_into(">I", raw, 20 + 4, int(tpl.Format.RGB5A3))
        (base / "files" / "art.tpl").write_bytes(bytes(raw))

        mod = a_mod(tmp_path / "mods", "files/art.tpl,,,invert,\n")
        built = build.apply_one(mod, base, build.edits_for(mod)[0])
        assert built.blocks == 0
        assert len(built.warnings) == 1
        assert "RGB5A3" in built.warnings[0]


class TestNothingGameDerivedIsPacked:
    """⛔ The reason the table exists at all."""

    def _packed(self, tmp_path: Path) -> pack.PackPlan:
        base = a_base(tmp_path)
        mod = a_mod(tmp_path / "mods", "files/art.tpl,,,invert,\n")
        build.apply_one(mod, base, build.edits_for(mod)[0])
        return pack.plan(registry.load(tmp_path / "mods").require("paint"))

    def test_the_generated_texture_counts_as_generated(self, tmp_path: Path):
        """⛔ It shipped as an *asset* the first time this was wired up."""
        plan = self._packed(tmp_path)
        assert "overlay/files/art.tpl" in plan.generated
        assert "overlay/files/art.tpl" not in plan.assets

    def test_the_mod_needs_no_consent_to_share(self, tmp_path: Path):
        assert not self._packed(tmp_path).needs_consent

    def test_the_archive_carries_the_table_and_no_texture(self, tmp_path: Path):
        base = a_base(tmp_path)
        mod = a_mod(tmp_path / "mods", "files/art.tpl,,,invert,\n")
        build.apply_one(mod, base, build.edits_for(mod)[0])
        mod = registry.load(tmp_path / "mods").require("paint")

        out = tmp_path / "paint.bleck"
        pack.write(mod, pack.plan(mod), out)
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
        assert "tables/textures.csv" in names
        assert not any(name.endswith(".tpl") for name in names)


class TestTheChain:
    def test_every_mod_in_the_chain_is_applied(self, tmp_path: Path):
        base = a_base(tmp_path)
        mods = tmp_path / "mods"
        a_mod(mods, "files/art.tpl,,,invert,\n", name="one")
        a_mod(mods, "files/art.tpl,,,greyscale,\n", name="two")
        chain = resolver.resolve(registry.load(mods), "two")
        assert len(build.apply_chain(chain, base)) == 1
