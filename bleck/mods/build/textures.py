"""Applying declared texture edits, against the user's own disc.

⛔ **Nothing here ships game data.** A mod declares an operation; the pixels
come from the recipient's copy at build time, exactly as placements already
work. That is the whole point — `tex-koopa` used to carry a modified Nintendo
texture, which is why it could not be shared and why on a fresh clone it did
nothing at all (its overlay is git-ignored).

⚠️ **The edit is applied in the CMPR endpoint domain** (D187), so it never
decodes or re-compresses and a rebuild costs no quality. Decoding lives in
`formats/texdecode.py` and is for *looking* only.

⚠️ Output goes to the mod's overlay, where the ordinary archive-merging
machinery picks it up. Nothing downstream knows the file was generated —
except the ledger, which records it so the next build can take it back (D182).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bleck.common.errors import BleckError
from bleck.formats import lz77, tpl, u8
from bleck.formats.tables import textures as texture_table
from bleck.mods.manifest import TableKind
from bleck.mods.registry import Mod
from bleck.mods.resolver import Chain


class TextureBuildError(BleckError):
    """A declared texture edit could not be applied."""


@dataclass(frozen=True)
class TextureBuild:
    """One texture rewritten, and what it took."""

    mod: str
    disc_path: str
    member: str
    output: Path
    images: int
    blocks: int
    reordered: int
    """CMPR blocks whose endpoints were swapped back to keep their kind."""

    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        inside = f"/{self.member}" if self.member else ""
        kept = f", {self.reordered} block(s) reordered" if self.reordered else ""
        return (
            f"{self.mod}: {self.disc_path}{inside} -> {self.images} image(s), "
            f"{self.blocks} block(s){kept}"
        )


def edits_for(mod: Mod) -> list[texture_table.TextureEdit]:
    # pylint: disable=container-return
    """Every texture edit this mod declares, across all its tables."""
    found: list[texture_table.TextureEdit] = []
    for ref in mod.manifest.tables_of(TableKind.TEXTURES):
        path = mod.root / ref.path
        found += texture_table.read(path, ref.path).edits
    return found


def _source_bytes(base: Path, edit: texture_table.TextureEdit) -> bytes:
    """The TPL as it exists on the user's disc, out of its archive if need be."""
    path = base / edit.disc_path
    if not path.is_file():
        raise TextureBuildError(
            f"{edit.source}: no file {edit.disc_path} in the base disc.\n"
            f"  `bleck maps` and `bleck archive list` will show what is there."
        )
    raw = path.read_bytes()
    if not edit.member:
        return raw

    payload = lz77.decompress(raw) if lz77.is_lz77(raw) else raw
    if not u8.is_u8(payload):
        raise TextureBuildError(
            f"{edit.source}: {edit.disc_path} is not an archive, but the row "
            f"names a member ({edit.member})."
        )
    wanted = u8.member_key(edit.member)
    for item in u8.read_all(payload):
        if item.data is not None and u8.member_key(item.path) == wanted:
            return item.data
    raise TextureBuildError(
        f"{edit.source}: no member {edit.member!r} in {edit.disc_path}."
    )


def apply_one(mod: Mod, base: Path, edit: texture_table.TextureEdit) -> TextureBuild:
    """Read one texture from the disc, map its colours, write it to the overlay."""
    data = _source_bytes(base, edit)
    if not tpl.is_tpl(data):
        raise TextureBuildError(
            f"{edit.source}: {edit.disc_path} is not a TPL texture container."
        )

    images = tpl.read(data)
    chosen = _chosen(images, edit)

    warnings: list[str] = []
    blocks = reordered = 0
    for image in chosen:
        if image.format is not tpl.Format.CMPR:
            # ⚠️ Reported, never skipped in silence. A declared edit that did
            # nothing and said nothing is D126's exact failure.
            warnings.append(
                f"{edit.source}: image {image.index} is {image.format.name}, "
                f"not CMPR, so '{edit.operation.name}' was not applied to it. "
                f"Only CMPR is editable without an encoder (D187)."
            )
            continue
        result = tpl.map_cmpr(data, image, edit.operation)
        data = result.data
        blocks += result.blocks
        reordered += result.reordered

    output = mod.overlay / edit.disc_path
    if edit.member:
        output = output / edit.member
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)

    return TextureBuild(
        mod=mod.name,
        disc_path=edit.disc_path,
        member=edit.member,
        output=output,
        images=len(chosen),
        blocks=blocks,
        reordered=reordered,
        warnings=warnings,
    )


def _chosen(images: list[tpl.Image], edit: texture_table.TextureEdit):
    # pylint: disable=container-return
    if edit.image is None:
        return images
    for image in images:
        if image.index == edit.image:
            return [image]
    raise TextureBuildError(
        f"{edit.source}: {edit.disc_path} has {len(images)} image(s), so there "
        f"is no image {edit.image}."
    )


def apply_chain(chain: Chain, base: Path) -> list[TextureBuild]:
    # pylint: disable=container-return
    """Every mod's declared texture edits, applied against `base`."""
    built: list[TextureBuild] = []
    for mod in chain.mods:
        for edit in edits_for(mod):
            built.append(apply_one(mod, base, edit))
    return built
