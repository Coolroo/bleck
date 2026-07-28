"""Riivolution patch output: the diff, the XML, and the output-kind table."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from bleck.backends import riivolution
from bleck.mods.build import outputs

GAME_ID = b"R8PP01"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """A minimal extracted build: a header, an executable, two asset files."""
    root = tmp_path / "base"
    _write(root / "sys" / "boot.bin", GAME_ID + b"\0" * 26)
    _write(root / "sys" / "main.dol", b"DOL" * 100)
    _write(root / "files" / "map" / "aa1_01.bin", b"map data")
    _write(root / "files" / "setup" / "aa1_01.dat", b"setup data")
    return root


@pytest.fixture
def staged(base: Path, tmp_path: Path) -> Path:
    """A copy of the base with one file changed and one added."""
    root = tmp_path / "staged"
    for source in base.rglob("*"):
        if source.is_file():
            _write(root / source.relative_to(base), source.read_bytes())
    _write(root / "files" / "map" / "aa1_01.bin", b"MAP DATA, EDITED")
    _write(root / "files" / "mod" / "mod.rel", b"\0\0\0\2rel")
    return root


class TestPlan:
    def test_only_changed_files(self, base: Path, staged: Path):
        patch = riivolution.plan("demo", base, staged)
        assert [r.staged_path for r in patch.replacements] == [
            "files/map/aa1_01.bin",
            "files/mod/mod.rel",
        ]

    def test_identical_trees_produce_nothing(self, base: Path, tmp_path: Path):
        same = tmp_path / "same"
        for source in base.rglob("*"):
            if source.is_file():
                _write(same / source.relative_to(base), source.read_bytes())
        patch = riivolution.plan("demo", base, same)
        assert patch.is_empty
        assert not patch.unsupported

    def test_new_file_asks_riivolution_to_create_it(self, base: Path, staged: Path):
        patch = riivolution.plan("demo", base, staged)
        added = next(r for r in patch.replacements if r.staged_path.endswith("mod.rel"))
        edited = next(
            r for r in patch.replacements if r.staged_path.endswith("aa1_01.bin")
        )
        assert added.create
        assert not edited.create

    def test_fst_paths_are_rooted_at_the_disc(self, base: Path, staged: Path):
        patch = riivolution.plan("demo", base, staged)
        assert {r.disc_path for r in patch.replacements} == {
            "/map/aa1_01.bin",
            "/mod/mod.rel",
        }

    def test_dol_disc_path_has_no_leading_slash(self, base: Path, staged: Path):
        """⚠️ `/main.dol` is looked up in the FST, where there is no such node."""
        _write(staged / "sys" / "main.dol", b"PATCHED DOL")
        patch = riivolution.plan("demo", base, staged)
        dol = next(r for r in patch.replacements if r.staged_path == "sys/main.dol")
        assert dol.disc_path == "main.dol"

    def test_unpatchable_change_is_reported_not_dropped(self, base: Path, staged: Path):
        _write(staged / "sys" / "boot.bin", b"R8PP01" + b"\xff" * 26)
        patch = riivolution.plan("demo", base, staged)
        assert not any(r.staged_path == "sys/boot.bin" for r in patch.replacements)
        assert any("sys/boot.bin" in line for line in patch.unsupported)

    def test_removals_are_reported(self, base: Path, staged: Path):
        (staged / "files" / "setup" / "aa1_01.dat").unlink()
        patch = riivolution.plan("demo", base, staged)
        assert any("files/setup/aa1_01.dat" in line for line in patch.unsupported)

    def test_game_id_comes_from_the_disc_header(self, base: Path, staged: Path):
        patch = riivolution.plan("demo", base, staged)
        assert patch.game.full == "R8PP01"
        assert patch.game.prefix == "R8P"
        assert patch.game.region == "P"

    def test_a_mod_with_no_code_still_plans(self, base: Path, tmp_path: Path):
        assets_only = tmp_path / "assets"
        for source in base.rglob("*"):
            if source.is_file():
                _write(assets_only / source.relative_to(base), source.read_bytes())
        _write(assets_only / "files" / "map" / "aa1_01.bin", b"different")
        patch = riivolution.plan("tex", base, assets_only)
        assert [r.disc_path for r in patch.replacements] == ["/map/aa1_01.bin"]
        assert not patch.unsupported


class TestXml:
    def test_is_well_formed(self, base: Path, staged: Path):
        patch = riivolution.plan("demo", base, staged)
        root = ElementTree.fromstring(riivolution.render_xml(patch))
        assert root.tag == "wiidisc"
        assert root.attrib["version"] == "1"

    def test_names_the_game_and_region(self, base: Path, staged: Path):
        patch = riivolution.plan("demo", base, staged)
        root = ElementTree.fromstring(riivolution.render_xml(patch))
        assert root.find("id").attrib["game"] == "R8P"
        assert root.find("id/region").attrib["type"] == "P"

    def test_the_option_defaults_to_on(self, base: Path, staged: Path):
        """default="0" means "off", and an off option patches nothing at all."""
        patch = riivolution.plan("demo", base, staged)
        root = ElementTree.fromstring(riivolution.render_xml(patch))
        option = root.find("options/section/option")
        assert option.attrib["default"] == "1"
        assert root.find("options/section/option/choice/patch").attrib["id"] == "demo"

    def test_every_replacement_becomes_a_file_element(self, base: Path, staged: Path):
        patch = riivolution.plan("demo", base, staged)
        root = ElementTree.fromstring(riivolution.render_xml(patch))
        files = root.findall("patch/file")
        assert [f.attrib["disc"] for f in files] == ["/map/aa1_01.bin", "/mod/mod.rel"]
        assert [f.attrib["external"] for f in files] == [
            "/demo/files/map/aa1_01.bin",
            "/demo/files/mod/mod.rel",
        ]

    def test_new_files_carry_create(self, base: Path, staged: Path):
        patch = riivolution.plan("demo", base, staged)
        root = ElementTree.fromstring(riivolution.render_xml(patch))
        by_disc = {f.attrib["disc"]: f.attrib for f in root.findall("patch/file")}
        assert by_disc["/mod/mod.rel"]["create"] == "true"
        assert "create" not in by_disc["/map/aa1_01.bin"]

    def test_paths_are_posix_on_every_host(self, base: Path, staged: Path):
        """Manifests and patch XMLs have to survive a Windows<->Linux trip."""
        patch = riivolution.plan("demo", base, staged)
        document = riivolution.render_xml(patch)
        assert "\\" not in document

    def test_a_patch_with_no_changes_is_still_valid_xml(self):
        empty = riivolution.PatchSet(name="nothing", game=riivolution.GameId("R8PP01"))
        root = ElementTree.fromstring(riivolution.render_xml(empty))
        assert root.findall("patch/file") == []


class TestEmit:
    def test_writes_the_layout_an_sd_card_expects(
        self, base: Path, staged: Path, tmp_path: Path
    ):
        patch = riivolution.plan("demo", base, staged)
        out = tmp_path / "out"
        emitted = riivolution.emit(patch, out, base)

        assert emitted.xml == out / "riivolution" / "demo.xml"
        assert (out / "demo" / "files" / "mod" / "mod.rel").read_bytes() == b"\0\0\0\2rel"
        assert emitted.files == 2

    def test_copies_only_the_changed_files(
        self, base: Path, staged: Path, tmp_path: Path
    ):
        out = tmp_path / "out"
        riivolution.emit(riivolution.plan("demo", base, staged), out, base)
        copied = sorted(
            p.relative_to(out).as_posix()
            for p in (out / "demo").rglob("*")
            if p.is_file()
        )
        assert copied == ["demo/files/map/aa1_01.bin", "demo/files/mod/mod.rel"]

    def test_stale_files_from_a_previous_build_are_dropped(
        self, base: Path, staged: Path, tmp_path: Path
    ):
        out = tmp_path / "out"
        _write(out / "demo" / "files" / "gone.bin", b"stale")
        riivolution.emit(riivolution.plan("demo", base, staged), out, base)
        assert not (out / "demo" / "files" / "gone.bin").exists()

    def test_descriptor_boots_the_base_build(
        self, base: Path, staged: Path, tmp_path: Path
    ):
        out = tmp_path / "out"
        emitted = riivolution.emit(riivolution.plan("demo", base, staged), out, base)
        body = json.loads(emitted.descriptor.read_text(encoding="utf-8"))

        assert body["type"] == "dolphin-game-mod-descriptor"
        assert body["version"] == 1
        assert body["base-file"].endswith("/sys/main.dol")
        patch_entry = body["riivolution"]["patches"][0]
        assert patch_entry["xml"] == "riivolution/demo.xml"
        assert patch_entry["root"] == "."
        # ⚠️ Belt and braces with the XML's default="1": Dolphin reads the
        # descriptor's choice, and 0 would silently apply nothing.
        assert patch_entry["options"][0]["choice"] == 1

    def test_descriptor_paths_are_posix(self, base: Path, staged: Path, tmp_path: Path):
        out = tmp_path / "out"
        emitted = riivolution.emit(riivolution.plan("demo", base, staged), out, base)
        assert "\\" not in emitted.descriptor.read_text(encoding="utf-8")


class TestOutputKinds:
    def test_every_kind_is_reachable_by_name(self):
        for name in outputs.names():
            assert outputs.find(name).name == name

    def test_unknown_kind_is_rejected(self):
        with pytest.raises(KeyError):
            outputs.find("floppy")

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("out.iso", "iso"),
            ("out.rvz", "rvz"),
            ("out.wbfs", "wbfs"),
            ("out.WBFS", "wbfs"),
            ("out", "iso"),
            ("out.unknown", "iso"),
        ],
    )
    def test_inferred_from_extension(self, filename: str, expected: str):
        assert outputs.for_path(Path(filename)).name == expected

    def test_default_destinations(self, tmp_path: Path):
        assert outputs.WBFS.default_out(tmp_path, "demo") == tmp_path / "demo.wbfs"
        assert (
            outputs.RIIVOLUTION.default_out(tmp_path, "demo")
            == tmp_path / "demo-riivolution"
        )

    def test_none_writes_nothing_and_boots_nothing(self, tmp_path: Path):
        request = outputs.OutputRequest(
            name="demo", base=tmp_path, staged=tmp_path, out=tmp_path / "unused"
        )
        result = outputs.NONE.write(request)
        assert result.bootable is None
        assert not (tmp_path / "unused").exists()

    def test_riivolution_reports_what_it_could_not_patch(
        self, base: Path, staged: Path, tmp_path: Path
    ):
        _write(staged / "sys" / "boot.bin", b"R8PP01" + b"\xee" * 26)
        result = outputs.RIIVOLUTION.write(
            outputs.OutputRequest(
                name="demo", base=base, staged=staged, out=tmp_path / "out"
            )
        )
        assert any("sys/boot.bin" in line for line in result.warnings)
        assert result.bootable == tmp_path / "out" / "demo.json"

    def test_a_base_image_overrides_the_extracted_build(
        self, base: Path, staged: Path, tmp_path: Path
    ):
        image = tmp_path / "retail.wbfs"
        image.write_bytes(b"disc")
        result = outputs.RIIVOLUTION.write(
            outputs.OutputRequest(
                name="demo",
                base=base,
                staged=staged,
                out=tmp_path / "out",
                base_image=image,
            )
        )
        body = json.loads((result.path / "demo.json").read_text(encoding="utf-8"))
        assert body["base-file"].endswith("retail.wbfs")
