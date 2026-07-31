"""Exports go into directories that mirror the disc, not one flat folder.

A full export is ~22,800 files. They used to land side by side in one
directory; each kind now gets a subtree and the disc's own layout is mirrored
inside it.

⚠️ **The manifest's `file` field is the contract.** Dimentio joins it onto the
export root (`data/catalog.rs`, `mesh.rs`, `sounds.rs` all do
`root.join(&entry.path)`), so every test here checks the *resolved* file
exists, not just that a path was written down.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from bleck.cli.commands import model as model_command
from bleck.cli.commands import sound as sound_command
from bleck.cli.commands import texture as texture_command
from bleck.common import exportlayout
from bleck.formats import brstm, model, tpl


class TestEscapingOneComponent:
    def test_an_ordinary_disc_name_is_left_alone(self):
        assert exportlayout.escape("p_wii_mario") == "p_wii_mario"
        assert exportlayout.escape("effdata.tpl") == "effdata.tpl"

    @pytest.mark.parametrize("char", '<>:"|?*\\/')
    def test_every_character_windows_forbids_is_escaped(self, char: str):
        out = exportlayout.escape(f"a{char}b")
        assert char not in out, f"{char!r} survived as {out!r}"
        assert out == f"a%{ord(char):02X}b"

    def test_walking_upwards_cannot_survive(self):
        """⛔ `..` as a real component would write outside the export root."""
        assert exportlayout.escape("..") == ".%2E"
        assert exportlayout.escape(".") == "%2E"

    def test_a_trailing_dot_or_space_is_escaped(self):
        """Windows silently trims both, which would merge two names into one."""
        assert exportlayout.escape("name.") == "name%2E"
        assert exportlayout.escape("name ") == "name%20"

    def test_a_reserved_device_name_cannot_be_produced(self):
        assert exportlayout.escape("nul.png") == "%6Eul.png"
        assert exportlayout.escape("COM1") == "%43OM1"
        assert exportlayout.escape("nully.png") == "nully.png"

    def test_control_characters_are_escaped(self):
        assert exportlayout.escape("a\nb") == "a%0Ab"

    def test_the_escape_is_injective_so_two_names_cannot_collide(self):
        """`%` is escaped first, which is what makes the mapping reversible."""
        awkward = ["a/b", "a%2Fb", "a%b", "..", ".%2E", "nul", "%6Eul", "x.", "x%2E"]
        assert len({exportlayout.escape(name) for name in awkward}) == len(awkward)


class TestPlacing:
    def test_a_plain_disc_path_keeps_its_directories(self):
        assert (
            exportlayout.place("sounds", "files/sound", "title.wav")
            == "sounds/files/sound/title.wav"
        )

    def test_an_archive_member_becomes_more_directories(self):
        assert (
            exportlayout.place("textures", "files/map/aa1_01.bin/aa1_01/tex.tpl", "0.png")
            == "textures/files/map/aa1_01.bin/aa1_01/tex.tpl/0.png"
        )

    def test_a_component_that_tries_to_escape_the_root_cannot(self):
        placed = exportlayout.place("textures", "files/../../etc", "0.png")
        assert placed == "textures/files/.%2E/.%2E/etc/0.png"
        assert ".." not in Path(placed).parts

    def test_empty_and_dot_components_are_dropped(self):
        """A file at the disc root has `.` for a parent, and a caller may join
        an empty archive member on unconditionally."""
        assert exportlayout.place("models", ".", "a.glb") == "models/a.glb"
        assert exportlayout.place("models", "", "a.glb") == "models/a.glb"
        assert exportlayout.place("models", "files//a", "b.glb") == "models/files/a/b.glb"

    def test_the_result_is_always_posix_and_relative(self):
        placed = exportlayout.place("textures", "files/eff/effdata.tpl", "0.png")
        assert "\\" not in placed
        assert not Path(placed).is_absolute()


class TestTheTree:
    def test_it_writes_through_nested_directories(self, tmp_path):
        tree = exportlayout.Tree(tmp_path)
        written = tree.write("textures/files/eff/effdata.tpl/0.png", b"pixels")
        assert written.read_bytes() == b"pixels"
        assert (
            written == tmp_path / "textures" / "files" / "eff" / "effdata.tpl" / "0.png"
        )

    def test_the_directory_cost_does_not_grow_with_the_file_count(
        self, tmp_path, monkeypatch
    ):
        """⚠️ 22,800 files is enough for a `mkdir` per file to be measurable.

        Counted rather than timed: pathlib retries `mkdir(parents=True)` after
        creating the parents, so the absolute number is an implementation
        detail. What must hold is that it is the same for 4 files as for 40.
        """
        made: list[Path] = []
        real = Path.mkdir

        def counted(self, *args, **kwargs):
            made.append(self)
            real(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", counted)

        def calls_for(files: int, where: str) -> int:
            made.clear()
            tree = exportlayout.Tree(tmp_path / where)
            for index in range(files):
                tree.write(f"textures/files/eff/effdata.tpl/{index}.png", b"x")
            return len(made)

        assert calls_for(4, "few") == calls_for(40, "many")


def _texture_entry(disc_path: str, member: str, index: int) -> texture_command.Found:
    image = tpl.Image(index=index, width=1, height=1, format=tpl.Format.RGBA32, offset=64)
    return texture_command.Found(disc_path, member, image, b"")


class _Pixels:
    """What `texdecode.decode` hands back, without needing a real TPL."""

    width = 1
    height = 1
    rgba = bytes(4)


class TestTextureExport:
    def test_pngs_land_under_the_disc_path_they_came_from(self, tmp_path, monkeypatch):
        found = [
            _texture_entry("files/eff/effdata.tpl", "", 0),
            _texture_entry("files/eff/effdata.tpl", "", 1),
            _texture_entry("files/map/aa1_01.bin", "aa1_01/tex/wall.tpl", 0),
        ]
        monkeypatch.setattr(texture_command, "_base", lambda: tmp_path)
        monkeypatch.setattr(texture_command, "_walk", lambda *_: found)
        monkeypatch.setattr(texture_command.texdecode, "decode", lambda *_: _Pixels())

        args = argparse.Namespace(out=str(tmp_path), search=None)
        assert texture_command.cmd_export(args) == 0

        files = _manifest_files(tmp_path, texture_command.MANIFEST, "textures")
        assert files == [
            "textures/files/eff/effdata.tpl/0.png",
            "textures/files/eff/effdata.tpl/1.png",
            "textures/files/map/aa1_01.bin/aa1_01/tex/wall.tpl/0.png",
        ]

    def test_a_name_windows_refuses_still_produces_a_file(self, tmp_path, monkeypatch):
        """⚠️ Escaped, never dropped — a missing PNG would read as a missing
        texture rather than as a renamed one."""
        found = [_texture_entry("files/odd/nul.tpl", 'a<b>c:d"e|f?g*h', 0)]
        monkeypatch.setattr(texture_command, "_base", lambda: tmp_path)
        monkeypatch.setattr(texture_command, "_walk", lambda *_: found)
        monkeypatch.setattr(texture_command.texdecode, "decode", lambda *_: _Pixels())

        args = argparse.Namespace(out=str(tmp_path), search=None)
        assert texture_command.cmd_export(args) == 0
        files = _manifest_files(tmp_path, texture_command.MANIFEST, "textures")
        assert files == [
            "textures/files/odd/%6Eul.tpl/a%3Cb%3Ec%3Ad%22e%7Cf%3Fg%2Ah/0.png"
        ]


class TestSoundExport:
    def test_wavs_land_under_their_disc_directory(self, tmp_path, monkeypatch):
        stream = brstm.Stream(
            rate=32000, channels=1, samples=4, loop_start=0, loops=False, pcm=[[0] * 4]
        )
        found = [
            sound_command.Found("files/sound/sys_title1_44k_lp.brstm", stream),
            sound_command.Found("files/sound/b_happy_flower_44k_lp.brstm", stream),
        ]
        monkeypatch.setattr(sound_command, "_base", lambda: tmp_path)
        monkeypatch.setattr(sound_command, "_walk", lambda *_: found)

        args = argparse.Namespace(out=str(tmp_path), search=None, seconds=0.0)
        assert sound_command.cmd_export(args) == 0

        files = _manifest_files(tmp_path, sound_command.MANIFEST, "sounds")
        assert files == [
            "sounds/files/sound/sys_title1_44k_lp.wav",
            "sounds/files/sound/b_happy_flower_44k_lp.wav",
        ]


class TestModelExport:
    def test_glbs_land_under_their_disc_directory(self, tmp_path, monkeypatch):
        base = tmp_path / "base"
        (base / "files" / "a").mkdir(parents=True)
        (base / "files" / "a" / "p_wii_mario").write_bytes(b"\x00" * 16)
        mesh = model.Mesh(
            name="squareShape",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
            faces=[model.Face(first=0, corners=3)],
            corner_positions=[0, 1, 2],
        )
        found = [model_command.Found("files/a/p_wii_mario", mesh)]
        monkeypatch.setattr(model_command, "_base", lambda: base)
        monkeypatch.setattr(model_command, "_walk", lambda *_: found)

        out = tmp_path / "export"
        args = argparse.Namespace(
            out=str(out),
            search=None,
            no_textures=True,
            no_animation=True,
            min_coverage=0.0,
            dense_morphs=False,
        )
        assert model_command.cmd_export(args) == 0

        files = _manifest_files(out, model_command.MANIFEST, "models")
        assert files == ["models/files/a/p_wii_mario.glb"]
        assert (out / files[0]).read_bytes()[:4] == b"glTF"


def _manifest_files(root: Path, manifest: str, key: str) -> list[str]:
    """Every `file` a manifest names, checked to resolve and to stay inside.

    ⚠️ This is the assertion that matters. A `file` that escapes the root is a
    write outside the directory the user asked for, and one that does not
    resolve is a manifest entry Dimentio reports as a missing asset.
    """
    document = json.loads((root / manifest).read_text(encoding="utf-8"))
    files = [entry["file"] for entry in document[key]]
    assert files, f"{manifest} names nothing"
    resolved_root = root.resolve()
    for name in files:
        assert not Path(name).is_absolute(), name
        assert "\\" not in name, f"{name} is not posix"
        assert name.startswith(f"{key}/"), f"{name} is not under {key}/"
        target = (root / name).resolve()
        assert target.is_file(), f"{name} does not resolve to a file"
        assert target.is_relative_to(resolved_root), f"{name} escapes the export root"
        assert target.parent != resolved_root, f"{name} is flat, not in a directory"
    return files


REPO = Path(__file__).resolve().parent.parent
EXTRACTED = REPO / "work" / "extracted" / "eu0"


class TestAgainstTheDisc:
    """The same claim against real disc paths, when a disc is extracted."""

    def test_a_real_texture_export_is_nested(self, tmp_path):
        if not (EXTRACTED / "files" / "eff").is_dir():
            pytest.skip(f"no extracted disc at {EXTRACTED}")
        args = argparse.Namespace(out=str(tmp_path), search="files/eff/effdata.tpl")
        assert texture_command.cmd_export(args) == 0
        files = _manifest_files(tmp_path, texture_command.MANIFEST, "textures")
        assert files[0] == "textures/files/eff/effdata.tpl/0.png"
