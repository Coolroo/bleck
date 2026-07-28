"""Riivolution output: a patch XML plus only the files that differ from base.

Delivers a mod to real hardware, and to Dolphin's Riivolution support, without
rebuilding a 4.7 GB image. Reasoning and the exact schema notes live in
`docs/hardware.md`.
"""

from __future__ import annotations

import filecmp
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from bleck import platforms
from bleck.common.errors import BleckError
from bleck.common.fsio import remove_tree


class RiivolutionError(BleckError):
    pass


#: ⚠️ No leading slash. A `disc` path starting with `/` is looked up in the FST,
#: where the executable has no node; the bare filename hits the special case
#: that patches the DOL (Dolphin's `ApplyFilePatchToFST`).
DOL_DISC_PATH = "main.dol"

#: The FST root is `files/` in a wit- or Dolphin-extracted build.
FST_PREFIX = "files/"

#: One section for the whole toolkit, so several bleck patches share a page.
SECTION = "bleck"

CHOICE_NAME = "Enabled"

#: Where the disc's 6-character game id sits in `sys/boot.bin`.
GAME_ID_LENGTH = 6


@dataclass(frozen=True)
class GameId:
    """A disc's game id, split the way Riivolution's `<id>` filter reads it."""

    full: str

    @property
    def prefix(self) -> str:
        """The three-character title code, e.g. `R8P`."""
        return self.full[:3]

    @property
    def region(self) -> str:
        """The region letter, e.g. `P` for PAL."""
        return self.full[3:4]


def read_game_id(base: Path) -> GameId:
    """The game id of an extracted build, from its `sys/boot.bin` header."""
    boot = base / "sys" / "boot.bin"
    if not boot.is_file():
        raise RiivolutionError(f"no disc header at {boot}")
    raw = boot.read_bytes()[:GAME_ID_LENGTH]
    text = raw.decode("ascii", "replace")
    if len(text) != GAME_ID_LENGTH or not text.isalnum():
        raise RiivolutionError(f"{boot} does not start with a game id (got {text!r})")
    return GameId(text)


@dataclass(frozen=True)
class Replacement:
    """One `<file>` patch: a staged file that differs from the base."""

    staged_path: str
    """Posix path relative to the staged build, e.g. `files/mod/mod.rel`."""

    disc_path: str
    """The `disc` attribute — what Riivolution replaces."""

    external: str
    """The `external` attribute, absolute from the SD root."""

    source: Path
    """Where to copy the replacement from."""

    create: bool
    """The base has no such file, so Riivolution must add it."""


@dataclass(frozen=True)
class PatchSet:
    """Everything one mod's Riivolution patch needs, as one value."""

    name: str
    game: GameId
    replacements: list[Replacement] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    """Differences Riivolution cannot express, reported rather than dropped."""

    @property
    def is_empty(self) -> bool:
        return not self.replacements


def _disc_path(staged_path: str) -> str:
    """The `disc` attribute for a staged path, or "" if it has none."""
    if staged_path.startswith(FST_PREFIX):
        return "/" + staged_path[len(FST_PREFIX) :]
    if staged_path.lower() == "sys/main.dol":
        return DOL_DISC_PATH
    return ""


def _unchanged(original: Path, staged: Path) -> bool:
    """Byte comparison, size-checked first. Staging hardlinks, so most match."""
    return filecmp.cmp(original, staged, shallow=False)


def plan(name: str, base: Path, staged: Path) -> PatchSet:
    """Diff a staged build against the base into a patch for `name`."""
    if not base.is_dir():
        raise RiivolutionError(f"base not found: {base}")
    if not staged.is_dir():
        raise RiivolutionError(f"nothing staged at {staged}")

    profile = platforms.current()
    replacements: list[Replacement] = []
    unsupported: list[str] = []

    for source in sorted(staged.rglob("*")):
        if not source.is_file() or profile.is_ignored(source.name):
            continue
        relative = source.relative_to(staged).as_posix()
        original = base / relative
        existed = original.is_file()
        if existed and _unchanged(original, source):
            continue
        disc_path = _disc_path(relative)
        if not disc_path:
            unsupported.append(
                f"{relative} differs from the base, but Riivolution can only "
                f"patch files under {FST_PREFIX} and the executable"
            )
            continue
        replacements.append(
            Replacement(
                staged_path=relative,
                disc_path=disc_path,
                external=f"/{name}/{relative}",
                source=source,
                create=not existed,
            )
        )

    unsupported += _removals(base, staged, profile)
    return PatchSet(
        name=name,
        game=read_game_id(base),
        replacements=replacements,
        unsupported=unsupported,
    )


def _removals(base: Path, staged: Path, profile) -> list[str]:
    """Base files the build dropped. Riivolution cannot delete a disc file."""
    missing: list[str] = []
    for original in sorted(base.rglob("*")):
        if not original.is_file() or profile.is_ignored(original.name):
            continue
        relative = original.relative_to(base).as_posix()
        if not (staged / relative).exists():
            missing.append(f"{relative} was removed, which a Riivolution patch cannot do")
    return missing


def render_xml(patch: PatchSet) -> str:
    """The `<wiidisc>` document for a patch set."""
    disc = ElementTree.Element("wiidisc", {"version": "1"})
    identity = ElementTree.SubElement(disc, "id", {"game": patch.game.prefix})
    ElementTree.SubElement(identity, "region", {"type": patch.game.region})

    options = ElementTree.SubElement(disc, "options")
    section = ElementTree.SubElement(options, "section", {"name": SECTION})
    # ⚠️ `default="1"` is load-bearing. The attribute is a 1-based choice index
    # and 0 means "off", so an option without it applies nothing at all.
    option = ElementTree.SubElement(
        section, "option", {"id": patch.name, "name": patch.name, "default": "1"}
    )
    choice = ElementTree.SubElement(option, "choice", {"name": CHOICE_NAME})
    ElementTree.SubElement(choice, "patch", {"id": patch.name})

    body = ElementTree.SubElement(disc, "patch", {"id": patch.name})
    for replacement in patch.replacements:
        attributes = {
            "disc": replacement.disc_path,
            "external": replacement.external,
            "resize": "true",
        }
        if replacement.create:
            attributes["create"] = "true"
        ElementTree.SubElement(body, "file", attributes)

    ElementTree.indent(disc, "  ")
    document = ElementTree.tostring(disc, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{document}\n'


def descriptor_base(base_file: Path) -> Path:
    """What Dolphin should boot: an image, or an extracted build's DOL.

    Dolphin opens `<build>/sys/main.dol` as a whole disc, so a Riivolution run
    needs no image built at all. ⚠️ That route is the less-travelled one — see
    `docs/hardware.md`; an untouched retail image is the safer base if you have
    one.
    """
    if base_file.is_dir():
        return base_file / "sys" / "main.dol"
    return base_file


def render_descriptor(patch: PatchSet, base_file: Path) -> str:
    """Dolphin's game-mod descriptor, so `Dolphin -e <name>.json` boots this.

    Paths inside it resolve relative to the descriptor's own directory.
    """
    body = {
        "type": "dolphin-game-mod-descriptor",
        "version": 1,
        "display-name": patch.name,
        "base-file": descriptor_base(base_file).resolve().as_posix(),
        "riivolution": {
            "patches": [
                {
                    "xml": f"riivolution/{patch.name}.xml",
                    # The SD-card root, which is the output directory itself.
                    "root": ".",
                    "options": [
                        {
                            "section-name": SECTION,
                            "option-id": patch.name,
                            "choice": 1,
                        }
                    ],
                }
            ]
        },
    }
    return json.dumps(body, indent=2) + "\n"


@dataclass(frozen=True)
class Emitted:
    """What `emit` wrote."""

    root: Path
    xml: Path
    descriptor: Path
    files: int
    total_bytes: int

    def describe(self) -> str:
        return (
            f"wrote {self.root}  ({self.files} file(s), "
            f"{self.total_bytes:,} bytes)\n"
            f"  patch:      {self.xml}\n"
            f"  dolphin:    {self.descriptor}"
        )


def emit(patch: PatchSet, out: Path, base_file: Path) -> Emitted:
    """Write the patch XML, the changed files, and Dolphin's descriptor.

    Layout is the one a Wii expects on an SD card, so `out`'s contents copy
    straight to its root:

        riivolution/<mod>.xml
        <mod>/files/...          only what differs from the base
        <mod>.json               Dolphin only; ignored on hardware
    """
    files_root = out / patch.name
    if files_root.exists():
        remove_tree(files_root)

    total = 0
    for replacement in patch.replacements:
        destination = out / patch.name / replacement.staged_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(replacement.source, destination)
        total += destination.stat().st_size

    xml_path = out / "riivolution" / f"{patch.name}.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(render_xml(patch), encoding="utf-8")

    descriptor = out / f"{patch.name}.json"
    descriptor.write_text(render_descriptor(patch, base_file), encoding="utf-8")

    return Emitted(
        root=out,
        xml=xml_path,
        descriptor=descriptor,
        files=len(patch.replacements),
        total_bytes=total,
    )
