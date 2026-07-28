"""Turning declared edits into the files a build ships.

A mod says "slot 3 is template 42 at (100, 0, 0)" and this derives the bytes
(`docs/vision.md`).

⚠️ **Both copies of a setup file are written** — which one drives spawning is
unestablished (D53, D59), so writing both is correct either way.

⚠️ Runs before the overlay is planned: the plan comes from walking `overlay/`,
so a generated file must exist by then.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck.common.errors import BleckError
from bleck.formats import lz77, setup, u8
from bleck.mods.registry import Mod
from bleck.mods.resolver import Chain


class EditError(BleckError):
    """A declared edit could not be applied."""


#: Where a map keeps its setup file, inside its own archive. Stored as
#: `./dvd/...`; the overlay drops the `./`, which `u8.member_key` reconciles
#: (D57).
MEMBER = "dvd/setup/{map_name}.dat"
ARCHIVE = "files/map/{map_name}.bin"

#: The other copy. Written too -- see the note in `_apply_map`.
STANDALONE = "files/setup/{map_name}.dat"


@dataclass(frozen=True)
class PlacementBuild:
    """One map's generated setup file, and what went into it."""

    mod: str
    map_name: str
    output: Path
    also_wrote: Path
    applied: int
    used_before: int
    used_after: int

    def describe(self) -> str:
        return (
            f"{self.mod}: {self.map_name} setup, {self.applied} edit(s) "
            f"-> {self.used_before} enemies becomes {self.used_after}"
        )


def mods_with_placements(chain: Chain) -> list[Mod]:
    return [mod for mod in chain.mods if mod.manifest.has_placements]


def apply_chain(chain: Chain, base: Path) -> list[PlacementBuild]:
    """Generate every declared setup file in the chain, newest last."""
    built = []
    for mod in mods_with_placements(chain):
        for placement in mod.manifest.setup:
            built.append(_apply_map(mod, placement, base))
    return built


def _archive_member(base: Path, map_name: str) -> bytes:
    """The map's own setup file, read out of its archive.

    Taken from the archive rather than `files/setup/`: the two are
    byte-identical on the disc, and this copy travels with its map.
    """
    archive = base / ARCHIVE.format(map_name=map_name)
    if not archive.is_file():
        raise EditError(f"no map archive at {archive}")

    raw = archive.read_bytes()
    payload = lz77.decompress(raw) if lz77.is_lz77(raw) else raw
    if not u8.is_u8(payload):
        raise EditError(f"{archive} is not an archive")

    wanted = u8.member_key(MEMBER.format(map_name=map_name))
    for item in u8.read_all(payload):
        if u8.member_key(item.path) == wanted and item.data is not None:
            return item.data
    raise EditError(
        f"{map_name} has no setup file inside its archive, so it places nothing to edit"
    )


def _apply_map(mod: Mod, placement, base: Path) -> PlacementBuild:
    data = setup.parse(
        _archive_member(base, placement.map_name),
        origin=f"{placement.map_name}.dat",
    )
    before = len(data.used)

    slots = list(data.enemies)
    for edit in placement.edits:
        slots[edit.slot] = _apply_edit(slots[edit.slot], edit, mod.name)

    updated = setup.SetupFile(
        version=data.version,
        enemies=slots,
        items=data.items,
        item_version=data.item_version,
        has_item_section=data.has_item_section,
    )
    _refuse_orphans(mod, placement, updated)

    # ⚠️ BOTH copies: which one drives spawning is unestablished (D53, D59),
    # so writing both is correct either way and leaves no stale copy.
    payload = updated.to_bytes()
    outputs = [
        mod.overlay
        / ARCHIVE.format(map_name=placement.map_name)
        / MEMBER.format(map_name=placement.map_name),
        mod.overlay / STANDALONE.format(map_name=placement.map_name),
    ]
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)

    return PlacementBuild(
        mod=mod.name,
        map_name=placement.map_name,
        output=outputs[0],
        also_wrote=outputs[1],
        applied=len(placement.edits),
        used_before=before,
        used_after=len(updated.used),
    )


def _refuse_orphans(mod: Mod, placement, updated: setup.SetupFile) -> None:
    """Refuse an edit that leaves a gap with used slots after it.

    ⚠️ **The game stops reading setup entries at the first empty one** (D79), so
    a cleared middle slot silently discards everything past it.

    Refused rather than compacted: renumbering would change what `{"slot": 2}`
    means in another mod's manifest.
    """
    empty = [i for i, enemy in enumerate(updated.enemies) if enemy.is_empty]
    if not empty:
        return
    first_gap = empty[0]
    orphaned = [
        index
        for index, enemy in enumerate(updated.enemies)
        if index > first_gap and not enemy.is_empty
    ]
    if not orphaned:
        return

    listed = ", ".join(str(index) for index in orphaned)
    raise EditError(
        f"{mod.name}: clearing slot {first_gap} of {placement.map_name} would "
        f"orphan slot(s) {listed}.\n"
        f"  The game stops reading setup entries at the first empty one, so "
        f"anything after a gap never spawns -- silently.\n"
        f"  Clear the last used slot instead, or move the later enemies down."
    )


def _apply_edit(enemy: setup.Enemy, edit, mod_name: str) -> setup.Enemy:
    try:
        if edit.clear:
            return enemy.cleared()
        if edit.template is not None:
            enemy = enemy.with_template(edit.template)
        if edit.position is not None:
            enemy = enemy.with_position(edit.position)
        return enemy
    except setup.SetupError as exc:
        raise EditError(f"{mod_name}: {edit.describe()}\n  {exc}") from exc
