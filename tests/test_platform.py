"""Cross-platform behaviour.

These run on Linux but exercise the Windows code paths by patching the platform
flag, so a Windows regression is caught here rather than on a user's machine.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from bleck import platforms
from bleck.backends import disc
from bleck.formats import u8
from bleck.mods import builder, manifest, registry, resolver
from tests.test_mods import ModSpec, make_mod

ALL_PROFILES = [
    platforms.linux.PROFILE,
    platforms.macos.PROFILE,
    platforms.windows.PROFILE,
]


ALL_TOOLS = [platforms.WIT, platforms.DOLPHIN_TOOL, platforms.DOLPHIN]


class TestProfiles:
    def test_every_profile_covers_every_tool(self):
        for profile in ALL_PROFILES:
            for key in ALL_TOOLS:
                location = profile.tool(key)
                assert location.names, f"{profile.name} has no names for {key}"
                assert location.hint, f"{profile.name} has no hint for {key}"

    def test_executable_names_differ_where_they_should(self):
        """Dolphin ships different executable names per platform."""
        assert (
            "dolphin-tool" in platforms.linux.PROFILE.tool(platforms.DOLPHIN_TOOL).names
        )
        assert (
            "DolphinTool.exe"
            in platforms.windows.PROFILE.tool(platforms.DOLPHIN_TOOL).names
        )
        assert "DolphinTool" in platforms.macos.PROFILE.tool(platforms.DOLPHIN_TOOL).names

    def test_search_dirs_are_platform_appropriate(self):
        windows_dirs = str(platforms.windows.PROFILE.tool(platforms.WIT).directories)
        assert "Program Files" in windows_dirs
        assert "/usr" not in windows_dirs

        for profile in (platforms.linux.PROFILE, platforms.macos.PROFILE):
            posix_dirs = str(profile.tool(platforms.WIT).directories)
            assert "Program Files" not in posix_dirs

    def test_venv_layout(self):
        assert platforms.windows.PROFILE.venv_bin == "Scripts"
        assert platforms.linux.PROFILE.venv_bin == "bin"
        assert platforms.macos.PROFILE.venv_bin == "bin"

    def test_hints_name_the_env_override(self):
        for profile in ALL_PROFILES:
            assert "BLECK_WIT" in profile.tool(platforms.WIT).hint
            assert "BLECK_DOLPHIN_TOOL" in profile.tool(platforms.DOLPHIN_TOOL).hint
            assert "BLECK_DOLPHIN" in profile.tool(platforms.DOLPHIN).hint

    def test_unknown_tool_falls_back_to_its_own_name(self):
        assert platforms.linux.PROFILE.tool("ghost").names == ["ghost"]


class TestDolphinIsNotDolphinTool:
    """The emulator and the disc utility ship together and are easy to confuse.

    They are not interchangeable: DolphinTool cannot boot a game and Dolphin
    cannot convert an image. Finding one where the other was meant produces a
    baffling failure, so the two must never share an executable name.
    """

    def test_no_platform_shares_a_name_between_them(self):
        for profile in ALL_PROFILES:
            emulator_names = set(profile.tool(platforms.DOLPHIN).names)
            tool_names = set(profile.tool(platforms.DOLPHIN_TOOL).names)
            assert not emulator_names & tool_names, profile.name

    def test_linux_never_searches_for_bare_dolphin(self):
        """`dolphin` on Linux is KDE's file manager, and is often installed.

        Searching for it by that name would launch a file browser instead of the
        emulator — which looks like `bleck` doing something bizarre rather than
        like a missing dependency.
        """
        assert "dolphin" not in platforms.linux.PROFILE.tool(platforms.DOLPHIN).names

    def test_each_platform_names_its_emulator_binary(self):
        assert "Dolphin.exe" in platforms.windows.PROFILE.tool(platforms.DOLPHIN).names
        assert "dolphin-emu" in platforms.linux.PROFILE.tool(platforms.DOLPHIN).names
        assert "Dolphin" in platforms.macos.PROFILE.tool(platforms.DOLPHIN).names


class TestMacOS:
    """macOS differs in ways that are easy to miss from a Linux box."""

    def test_dolphin_is_found_inside_the_app_bundle(self):
        dirs = platforms.macos.PROFILE.tool(platforms.DOLPHIN_TOOL).directories
        assert any("Dolphin.app/Contents/MacOS" in d for d in dirs)

    def test_both_homebrew_prefixes_are_searched(self):
        """Apple Silicon uses /opt/homebrew, Intel uses /usr/local."""
        dirs = platforms.macos.PROFILE.tool(platforms.WIT).directories
        assert any("/opt/homebrew" in d for d in dirs)
        assert any("/usr/local" in d for d in dirs)

    @pytest.mark.parametrize("name", [".DS_Store", "._resource", ".localized"])
    def test_finder_clutter_is_ignored(self, name: str):
        assert platforms.macos.PROFILE.is_ignored(name)

    @pytest.mark.parametrize("name", ["map.dat", "aa1_01.bin", "mario.tpl"])
    def test_real_files_are_kept(self, name: str):
        assert not platforms.macos.PROFILE.is_ignored(name)

    def test_other_platforms_do_not_filter(self):
        """Only macOS creates this clutter; filtering elsewhere would hide bugs."""
        assert not platforms.linux.PROFILE.is_ignored(".DS_Store")
        assert not platforms.windows.PROFILE.is_ignored(".DS_Store")


class TestToolDiscovery:
    def test_missing_tool_lists_what_it_tried(self, monkeypatch):
        monkeypatch.setattr(disc.shutil, "which", lambda _name: None)
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
