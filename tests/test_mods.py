"""Mod manifests, dependency resolution, conflicts, and building."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from bleck.formats import lz77, u8
from bleck.mods import builder, conflicts, manifest, overlay, registry, resolver


@dataclass(frozen=True)
class ModSpec:
    """What a test mod should contain. Grouped so the helper stays narrow."""

    version: str = "1.0.0"
    deps: list[str] = field(default_factory=list)
    base: str = "eu0"
    exclusive: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)


def make_mod(root: Path, name: str, spec: ModSpec | None = None) -> Path:
    """Write a mod to disk. Returns its directory."""
    spec = spec or ModSpec()
    directory = root / name
    (directory / manifest.OVERLAY_DIR).mkdir(parents=True, exist_ok=True)
    manifest.write(
        directory,
        manifest.Manifest(
            name=name,
            version=manifest.Version.parse(spec.version),
            base=spec.base,
            dependencies=[manifest.Requirement(d) for d in spec.deps],
            exclusive=list(spec.exclusive),
            remove=list(spec.remove),
        ),
    )
    for relative, data in spec.files.items():
        target = directory / manifest.OVERLAY_DIR / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return directory


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """A miniature extracted base, including one real LZ77+U8 archive."""
    root = tmp_path / "base" / "eu0"
    (root / "files" / "map").mkdir(parents=True)
    (root / "files" / "setup").mkdir(parents=True)

    (root / "files" / "notes.txt").write_bytes(b"line one\nline two\nline three\n")
    (root / "files" / "setup" / "aa1_01.dat").write_bytes(b"S" * 64)

    archive = u8.write(
        [
            u8.U8Item("arc", None),
            u8.U8Item("arc/a.tpl", b"AAAA" * 16),
            u8.U8Item("arc/b.tpl", b"BBBB" * 16),
        ]
    )
    (root / "files" / "map" / "aa1_01.bin").write_bytes(lz77.compress_literals(archive))
    return root


@pytest.fixture
def mods_root(tmp_path: Path) -> Path:
    root = tmp_path / "mods"
    root.mkdir()
    return root


class TestManifest:
    def test_round_trips(self):
        original = manifest.Manifest(
            name="demo",
            version=manifest.Version(1, 2, 3),
            base="eu0",
            dependencies=[manifest.Requirement("other", ">=", manifest.Version(1, 0, 0))],
            exclusive=["files/rel/rel.bin"],
        )
        assert manifest.Manifest.from_json(original.to_json()) == original

    def test_requires_a_name(self):
        with pytest.raises(manifest.ManifestError, match="'name' is required"):
            manifest.Manifest.from_json('{"schema": 1}')

    def test_rejects_future_schema(self):
        with pytest.raises(manifest.ManifestError, match="unsupported schema"):
            manifest.Manifest.from_json('{"schema": 99, "name": "x"}')

    def test_rejects_bad_version(self):
        with pytest.raises(manifest.ManifestError, match="bad version"):
            manifest.Version.parse("1.2")

    @pytest.mark.parametrize(
        ("spec", "candidate", "expected"),
        [
            (">=1.0.0", "1.0.0", True),
            (">=1.0.0", "0.9.0", False),
            ("<=2.0.0", "1.5.0", True),
            ("==1.0.0", "1.0.1", False),
            ("", "0.0.1", True),
        ],
    )
    def test_version_requirements(self, spec: str, candidate: str, expected: bool):
        requirement = manifest.Requirement.parse("dep", spec)
        assert requirement.is_satisfied_by(manifest.Version.parse(candidate)) is expected


class TestResolver:
    def test_single_mod(self, mods_root: Path):
        make_mod(mods_root, "solo")
        chain = resolver.resolve(registry.load(mods_root), "solo")
        assert [m.name for m in chain.mods] == ["solo"]
        assert chain.entries[-1].is_target

    def test_dependencies_apply_before_dependent(self, mods_root: Path):
        make_mod(mods_root, "lib")
        make_mod(mods_root, "app", ModSpec(deps=["lib"]))
        chain = resolver.resolve(registry.load(mods_root), "app")
        assert [m.name for m in chain.mods] == ["lib", "app"]

    def test_diamond_deduplicates(self, mods_root: Path):
        """M -> [A, B], both -> C. C must appear once, before both."""
        make_mod(mods_root, "c")
        make_mod(mods_root, "a", ModSpec(deps=["c"]))
        make_mod(mods_root, "b", ModSpec(deps=["c"]))
        make_mod(mods_root, "m", ModSpec(deps=["a", "b"]))
        chain = resolver.resolve(registry.load(mods_root), "m")
        assert [mod.name for mod in chain.mods] == ["c", "a", "b", "m"]

    def test_declaration_order_is_respected(self, mods_root: Path):
        make_mod(mods_root, "x")
        make_mod(mods_root, "y")
        make_mod(mods_root, "m", ModSpec(deps=["y", "x"]))
        chain = resolver.resolve(registry.load(mods_root), "m")
        assert [mod.name for mod in chain.mods] == ["y", "x", "m"]

    def test_deep_transitive_chain(self, mods_root: Path):
        make_mod(mods_root, "d")
        make_mod(mods_root, "c", ModSpec(deps=["d"]))
        make_mod(mods_root, "b", ModSpec(deps=["c"]))
        make_mod(mods_root, "a", ModSpec(deps=["b"]))
        chain = resolver.resolve(registry.load(mods_root), "a")
        assert [mod.name for mod in chain.mods] == ["d", "c", "b", "a"]

    def test_cycle_is_reported_with_path(self, mods_root: Path):
        make_mod(mods_root, "a", ModSpec(deps=["b"]))
        make_mod(mods_root, "b", ModSpec(deps=["a"]))
        with pytest.raises(resolver.ResolutionError, match=r"cycle: a → b → a"):
            resolver.resolve(registry.load(mods_root), "a")

    def test_missing_dependency_names_the_requirer(self, mods_root: Path):
        make_mod(mods_root, "app", ModSpec(deps=["absent"]))
        with pytest.raises(resolver.ResolutionError, match="app requires absent"):
            resolver.resolve(registry.load(mods_root), "app")

    def test_version_mismatch_is_an_error(self, mods_root: Path):
        make_mod(mods_root, "lib", ModSpec(version="1.0.0"))
        directory = make_mod(mods_root, "app")
        manifest.write(
            directory,
            manifest.Manifest(
                name="app",
                base="eu0",
                dependencies=[
                    manifest.Requirement("lib", ">=", manifest.Version(2, 0, 0))
                ],
            ),
        )
        with pytest.raises(
            resolver.ResolutionError, match=r"but lib 1\.0\.0 is installed"
        ):
            resolver.resolve(registry.load(mods_root), "app")

    def test_unknown_mod(self, mods_root: Path):
        with pytest.raises(registry.RegistryError, match="no mod named"):
            resolver.resolve(registry.load(mods_root), "ghost")

    def test_base_mismatch_detected(self, mods_root: Path):
        make_mod(mods_root, "us-mod", ModSpec(base="us0"))
        chain = resolver.resolve(registry.load(mods_root), "us-mod")
        assert resolver.check_bases(chain, "eu0")
        assert not resolver.check_bases(chain, "us0")


class TestOverlayPaths:
    def test_whole_file_target(self, base: Path):
        target = overlay.resolve_target(base, "files/notes.txt")
        assert target.disc_path == "files/notes.txt"
        assert not target.is_member

    def test_archive_member_target(self, base: Path):
        target = overlay.resolve_target(base, "files/map/aa1_01.bin/arc/a.tpl")
        assert target.disc_path == "files/map/aa1_01.bin"
        assert target.member == "arc/a.tpl"

    def test_new_file_target(self, base: Path):
        target = overlay.resolve_target(base, "files/brand/new.bin")
        assert target.disc_path == "files/brand/new.bin"
        assert not target.is_member

    def test_bare_path_gets_the_data_prefix(self, base: Path):
        assert overlay.normalize_disc_path(base, "notes.txt") == "files/notes.txt"
        assert (
            overlay.normalize_disc_path(base, "map/aa1_01.bin/arc/a.tpl")
            == "files/map/aa1_01.bin/arc/a.tpl"
        )


class TestConflicts:
    def test_different_members_do_not_conflict(self, base: Path, mods_root: Path):
        make_mod(
            mods_root, "one", ModSpec(files={"files/map/aa1_01.bin/arc/a.tpl": b"X" * 64})
        )
        make_mod(
            mods_root, "two", ModSpec(files={"files/map/aa1_01.bin/arc/b.tpl": b"Y" * 64})
        )
        make_mod(mods_root, "both", ModSpec(deps=["one", "two"]))
        chain = resolver.resolve(registry.load(mods_root), "both")
        report = builder.check(chain, base, allow_binary=False)
        assert report.is_clean

    def test_same_binary_member_conflicts(self, base: Path, mods_root: Path):
        make_mod(
            mods_root, "one", ModSpec(files={"files/map/aa1_01.bin/arc/a.tpl": b"X" * 64})
        )
        make_mod(
            mods_root, "two", ModSpec(files={"files/map/aa1_01.bin/arc/a.tpl": b"Y" * 64})
        )
        make_mod(mods_root, "both", ModSpec(deps=["one", "two"]))
        chain = resolver.resolve(registry.load(mods_root), "both")
        report = builder.check(chain, base, allow_binary=False)
        assert not report.is_clean

    def test_dependency_override_is_not_a_conflict(self, base: Path, mods_root: Path):
        """If B depends on A, B overriding A's file is intentional."""
        make_mod(mods_root, "lib", ModSpec(files={"files/notes.txt": b"from lib\n"}))
        make_mod(
            mods_root,
            "app",
            ModSpec(deps=["lib"], files={"files/notes.txt": b"from app\n"}),
        )
        chain = resolver.resolve(registry.load(mods_root), "app")
        report = builder.check(chain, base, allow_binary=False)
        assert report.is_clean

    def test_exclusive_claim_blocks_others(self, base: Path, mods_root: Path):
        make_mod(
            mods_root,
            "owner",
            ModSpec(
                exclusive=["files/notes.txt"],
                files={"files/notes.txt": b"mine\n"},
            ),
        )
        make_mod(mods_root, "other", ModSpec(files={"files/notes.txt": b"also mine\n"}))
        make_mod(mods_root, "both", ModSpec(deps=["owner", "other"]))
        chain = resolver.resolve(registry.load(mods_root), "both")
        report = builder.check(chain, base, allow_binary=False)
        assert any(c.kind is conflicts.ConflictKind.EXCLUSIVE for c in report.conflicts)

    def test_identical_edits_agree(self, base: Path, mods_root: Path):
        make_mod(mods_root, "one", ModSpec(files={"files/notes.txt": b"same\n"}))
        make_mod(mods_root, "two", ModSpec(files={"files/notes.txt": b"same\n"}))
        make_mod(mods_root, "both", ModSpec(deps=["one", "two"]))
        chain = resolver.resolve(registry.load(mods_root), "both")
        assert builder.check(chain, base, allow_binary=False).is_clean

    def test_setup_duplicate_warning(self, base: Path, mods_root: Path):
        """A setup file exists twice and it is unknown which the game reads.

        Editing one by hand is the silent no-op this warning exists to catch --
        which is exactly what happened when only the archive copy was written
        (D59).
        """
        make_mod(mods_root, "s", ModSpec(files={"files/setup/aa1_01.dat": b"Z" * 64}))
        chain = resolver.resolve(registry.load(mods_root), "s")
        report = builder.check(chain, base, allow_binary=False)
        warning = next(w for w in report.warnings if "aa1_01" in w)
        # D62: the standalone copy is the one the game reads. The warning has to
        # say which, not just that there are two.
        assert "the copy the game reads" in warning
        assert "Edit both" in warning


class TestByteRanges:
    def test_identical_data_has_empty_range(self):
        assert conflicts.changed_range(b"abcdef", b"abcdef").is_empty

    def test_range_covers_the_difference(self):
        span = conflicts.changed_range(b"abcdef", b"abXYef")
        assert span.start == 2
        assert span.end >= 4

    def test_disjoint_ranges_do_not_overlap(self):
        left = conflicts.changed_range(b"abcdefgh", b"XXcdefgh")
        right = conflicts.changed_range(b"abcdefgh", b"abcdefYY")
        assert not left.overlaps(right)

    def test_overlapping_ranges_detected(self):
        left = conflicts.changed_range(b"abcdefgh", b"abXXefgh")
        right = conflicts.changed_range(b"abcdefgh", b"abcXXfgh")
        assert left.overlaps(right)


class TestBuild:
    def test_stage_does_not_modify_base(
        self, base: Path, mods_root: Path, tmp_path: Path
    ):
        original = (base / "files" / "notes.txt").read_bytes()
        make_mod(mods_root, "edit", ModSpec(files={"files/notes.txt": b"changed\n"}))
        chain = resolver.resolve(registry.load(mods_root), "edit")
        builder.build(chain, base, tmp_path / "staged", allow_binary=False)
        assert (base / "files" / "notes.txt").read_bytes() == original

    def test_staged_output_has_the_change(
        self, base: Path, mods_root: Path, tmp_path: Path
    ):
        make_mod(mods_root, "edit", ModSpec(files={"files/notes.txt": b"changed\n"}))
        chain = resolver.resolve(registry.load(mods_root), "edit")
        staged = tmp_path / "staged"
        builder.build(chain, base, staged, allow_binary=False)
        assert (staged / "files" / "notes.txt").read_bytes() == b"changed\n"

    def test_archive_merge_touches_only_named_member(
        self, base: Path, mods_root: Path, tmp_path: Path
    ):
        make_mod(
            mods_root,
            "tex",
            ModSpec(files={"files/map/aa1_01.bin/arc/a.tpl": b"NEW!" * 16}),
        )
        chain = resolver.resolve(registry.load(mods_root), "tex")
        staged = tmp_path / "staged"
        builder.build(chain, base, staged, allow_binary=False)

        rebuilt = lz77.decompress((staged / "files/map/aa1_01.bin").read_bytes())
        members = {i.path: i.data for i in u8.read_all(rebuilt)}
        assert members["arc/a.tpl"] == b"NEW!" * 16
        assert members["arc/b.tpl"] == b"BBBB" * 16  # untouched

    def test_archive_member_order_preserved(
        self, base: Path, mods_root: Path, tmp_path: Path
    ):
        before = [
            i.path
            for i in u8.read_all(
                lz77.decompress((base / "files/map/aa1_01.bin").read_bytes())
            )
        ]
        make_mod(
            mods_root, "tex", ModSpec(files={"files/map/aa1_01.bin/arc/a.tpl": b"Q" * 64})
        )
        chain = resolver.resolve(registry.load(mods_root), "tex")
        staged = tmp_path / "staged"
        builder.build(chain, base, staged, allow_binary=False)
        after = [
            i.path
            for i in u8.read_all(
                lz77.decompress((staged / "files/map/aa1_01.bin").read_bytes())
            )
        ]
        assert before == after

    def test_remove_deletes_a_base_file(
        self, base: Path, mods_root: Path, tmp_path: Path
    ):
        make_mod(mods_root, "cut", ModSpec(remove=["files/notes.txt"]))
        chain = resolver.resolve(registry.load(mods_root), "cut")
        staged = tmp_path / "staged"
        report = builder.build(chain, base, staged, allow_binary=False)
        assert report.files_removed == 1
        assert not (staged / "files" / "notes.txt").exists()
        assert (base / "files" / "notes.txt").exists()

    def test_later_mod_wins_over_its_dependency(
        self, base: Path, mods_root: Path, tmp_path: Path
    ):
        make_mod(mods_root, "lib", ModSpec(files={"files/notes.txt": b"lib\n"}))
        make_mod(
            mods_root, "app", ModSpec(deps=["lib"], files={"files/notes.txt": b"app\n"})
        )
        chain = resolver.resolve(registry.load(mods_root), "app")
        staged = tmp_path / "staged"
        builder.build(chain, base, staged, allow_binary=False)
        assert (staged / "files" / "notes.txt").read_bytes() == b"app\n"

    def test_conflicts_block_staging(self, base: Path, mods_root: Path, tmp_path: Path):
        make_mod(mods_root, "one", ModSpec(files={"files/notes.txt": b"one\n"}))
        make_mod(mods_root, "two", ModSpec(files={"files/notes.txt": b"two\n"}))
        make_mod(mods_root, "both", ModSpec(deps=["one", "two"]))
        chain = resolver.resolve(registry.load(mods_root), "both")
        staged = tmp_path / "staged"
        report = builder.build(chain, base, staged, allow_binary=False)
        assert not report.is_clean
        assert not staged.exists(), "nothing should be written when conflicts exist"


class TestArchiveMemberPaths:
    """SPM's two archive families spell member paths differently.

    `lyt/*.bin.uk` stores `arc/anim/x.brlan`; `map/*.bin` stores
    `./dvd/setup/x.dat`. An overlay directory cannot contain a `.` component, so
    an overlay addressing a map-archive member produces `dvd/setup/x.dat` and
    used to match nothing -- the member was *added* beside the original rather
    than replacing it, leaving two nodes with the same name.
    """

    def test_a_dot_slash_member_is_matched(self):
        assert u8.member_key("./dvd/setup/he1_01.dat") == "dvd/setup/he1_01.dat"

    def test_a_plain_member_is_left_alone(self):
        assert u8.member_key("arc/timg/mario.tpl") == "arc/timg/mario.tpl"

    def test_both_spellings_collide_deliberately(self):
        # They must land on the same key, or the merge cannot see that an
        # overlay entry and an archive node are the same file.
        assert u8.member_key("./a/b.dat") == u8.member_key("a/b.dat")
