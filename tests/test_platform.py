"""Cross-platform behaviour.

These run on Linux but exercise the Windows code paths by patching the platform
flag, so a Windows regression is caught here rather than on a user's machine.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from bleck.backends import disc
from bleck.formats import u8
from bleck.mods import builder, manifest, registry, resolver
from tests.test_mods import ModSpec, make_mod


class TestToolDiscovery:
    def test_windows_uses_different_executable_names(self, monkeypatch):
        """Dolphin ships `dolphin-tool` on Linux, `DolphinTool.exe` on Windows."""
        spec = disc.TOOLS[disc.DOLPHIN_TOOL]

        monkeypatch.setattr(disc, "IS_WINDOWS", False)
        assert "dolphin-tool" in spec.names

        monkeypatch.setattr(disc, "IS_WINDOWS", True)
        assert "DolphinTool.exe" in spec.names

    def test_windows_search_dirs_are_windows_paths(self, monkeypatch):
        monkeypatch.setattr(disc, "IS_WINDOWS", True)
        for spec in disc.TOOLS.values():
            for directory in spec.search_dirs:
                assert not str(directory).startswith("/usr")

    def test_posix_search_dirs_exclude_program_files(self, monkeypatch):
        monkeypatch.setattr(disc, "IS_WINDOWS", False)
        for spec in disc.TOOLS.values():
            assert all("Program Files" not in str(d) for d in spec.search_dirs)

    def test_hint_names_the_env_override(self, monkeypatch):
        monkeypatch.setattr(disc, "IS_WINDOWS", True)
        assert "BLECK_WIT" in disc.TOOLS[disc.WIT].hint
        assert "BLECK_DOLPHIN_TOOL" in disc.TOOLS[disc.DOLPHIN_TOOL].hint

    def test_missing_tool_lists_what_it_tried(self, monkeypatch):
        monkeypatch.setattr(disc.shutil, "which", lambda _name: None)
        monkeypatch.setattr(
            disc,
            "TOOLS",
            {"ghost": disc.ToolSpec("ghost", ("ghost",), ("ghost.exe",))},
        )
        with pytest.raises(disc.DiscError, match="looked for"):
            disc.find_tool("ghost")

    def test_env_override_wins_over_path(self, monkeypatch, tmp_path: Path):
        fake = tmp_path / "my-wit"
        fake.write_text("")
        monkeypatch.setenv("BLECK_WIT", str(fake))
        assert disc.find_tool(disc.WIT) == str(fake)


class TestPathHandling:
    def test_overlay_paths_are_posix_style(self, tmp_path: Path):
        """Manifest paths must be posix regardless of host, or they break sharing."""
        root = tmp_path / "mods"
        root.mkdir()
        make_mod(
            root,
            "nested",
            ModSpec(files={"files/lyt/title.bin.uk/arc/timg/mario.tpl": b"x"}),
        )
        mod = registry.load(root).require("nested")
        for path in mod.overlay_paths():
            assert "\\" not in path, "backslashes would not survive a Windows->Linux trip"
            assert "/" in path

    def test_disc_paths_never_use_windows_separators(self):
        """U8 member paths are archive-internal and always posix."""
        packed = u8.write([u8.U8Item("dvd", None), u8.U8Item("dvd/map/a.bin", b"data")])
        for entry in u8.read(packed):
            assert "\\" not in entry.path

    def test_windows_style_input_would_be_distinguishable(self):
        """Guard the assumption that we never build paths with PureWindowsPath."""
        assert "\\" in str(PureWindowsPath("a") / "b")


class TestImageFormat:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("out.iso", disc.ImageFormat.ISO),
            ("out.rvz", disc.ImageFormat.RVZ),
            ("out.wbfs", disc.ImageFormat.WBFS),
            ("out.RVZ", disc.ImageFormat.RVZ),
            ("out", disc.ImageFormat.ISO),
            ("out.unknown", disc.ImageFormat.ISO),
        ],
    )
    def test_inferred_from_extension(self, filename: str, expected: disc.ImageFormat):
        assert disc.ImageFormat.for_path(Path(filename)) is expected

    def test_case_insensitive_on_windows_style_names(self):
        assert disc.ImageFormat.for_path(Path("OUT.WBFS")) is disc.ImageFormat.WBFS


class TestStagingRemoval:
    def test_removes_read_only_files(self, tmp_path: Path):
        """Windows refuses to delete read-only files; staging must cope."""
        tree = tmp_path / "staged"
        (tree / "sub").mkdir(parents=True)
        target = tree / "sub" / "locked.bin"
        target.write_bytes(b"data")
        target.chmod(0o444)

        builder.remove_tree(tree)
        assert not tree.exists()

    def test_stage_falls_back_when_linking_fails(self, tmp_path: Path, monkeypatch):
        """Cross-filesystem staging cannot hardlink and must copy instead."""
        base = tmp_path / "base"
        (base / "files").mkdir(parents=True)
        (base / "files" / "a.bin").write_bytes(b"content")

        def refuse(*_args, **_kwargs):
            raise OSError("cross-device link")

        monkeypatch.setattr(builder.os, "link", refuse)
        count = builder.stage(base, tmp_path / "staged")
        assert count == 1
        assert (tmp_path / "staged" / "files" / "a.bin").read_bytes() == b"content"


class TestBuildPortability:
    def test_build_works_without_hardlinks(self, tmp_path: Path, monkeypatch):
        """A full mod build must survive on filesystems with no hardlink support."""
        base = tmp_path / "base" / "eu0"
        (base / "files").mkdir(parents=True)
        (base / "files" / "notes.txt").write_bytes(b"original\n")

        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        make_mod(mods_root, "edit", ModSpec(files={"files/notes.txt": b"changed\n"}))

        def refuse(*_args, **_kwargs):
            raise OSError("no hardlinks here")

        monkeypatch.setattr(builder.os, "link", refuse)

        chain = resolver.resolve(registry.load(mods_root), "edit")
        staged = tmp_path / "staged"
        report = builder.build(chain, base, staged, allow_binary=False)
        assert report.is_clean
        assert (staged / "files" / "notes.txt").read_bytes() == b"changed\n"
        assert (base / "files" / "notes.txt").read_bytes() == b"original\n"


class TestManifestPortability:
    def test_manifest_is_plain_ascii_json(self, tmp_path: Path):
        """Manifests move between machines; keep them encoding-independent."""
        manifest.write(
            tmp_path,
            manifest.Manifest(name="demo", base="eu0", exclusive=["files/rel/rel.bin"]),
        )
        raw = (tmp_path / manifest.MANIFEST_NAME).read_bytes()
        raw.decode("ascii")  # raises if anything non-ascii crept in

    def test_line_endings_do_not_affect_parsing(self):
        """A manifest checked out with CRLF must still load."""
        original = manifest.Manifest(name="demo", base="eu0")
        crlf = original.to_json().replace("\n", "\r\n")
        assert manifest.Manifest.from_json(crlf) == original
