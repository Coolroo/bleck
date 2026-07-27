"""Detecting when two independent mods cannot both be applied.

Conflicts are only possible between mods where **neither depends on the other**.
If B depends on A, B overriding A's files is intentional — that is what
depending on something means.

Checks run finest-granularity-first, so most collisions turn out not to be real:
two mods editing different members of the same archive do not conflict at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from bleck.formats import lz77, u8

from .overlay import Edit, Plan, TargetPath
from .resolver import Chain

TEXT_SUFFIXES = frozenset({".txt", ".json", ".xml", ".ini", ".cfg", ".md"})


class ConflictKind(Enum):
    EXCLUSIVE = "exclusive"
    """A mod claimed the path exclusively; another touched it."""

    OVERLAPPING = "overlapping"
    """Independent edits to the same region."""

    BINARY = "binary"
    """Independent edits to the same binary file; auto-merge not enabled."""


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def is_empty(self) -> bool:
        return self.end <= self.start

    def overlaps(self, other: ByteRange) -> bool:
        if self.is_empty or other.is_empty:
            return False
        return self.start < other.end and other.start < self.end

    def __str__(self) -> str:
        return f"bytes 0x{self.start:x}-0x{self.end:x}"


@dataclass(frozen=True)
class Conflict:
    """One reason a build cannot proceed."""

    path: str
    kind: ConflictKind
    mods: list[str]
    detail: str = ""

    def describe(self) -> str:
        lines = [f"  {self.path}"]
        if self.detail:
            lines.append(f"    {self.detail}")
        return "\n".join(lines)


@dataclass
class MergeOutcome:
    """The result of attempting a three-way merge."""

    data: bytes = b""
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.conflicts


def changed_range(base: bytes, edited: bytes) -> ByteRange:
    """The minimal span containing every difference.

    Bounded by the common prefix and suffix — O(n) and conservative. A tighter
    hunk analysis would report less overlap, but over-reporting a conflict is
    the safe direction.
    """
    if base == edited:
        return ByteRange(0, 0)

    limit = min(len(base), len(edited))
    start = 0
    while start < limit and base[start] == edited[start]:
        start += 1

    tail = 0
    while (
        tail < limit - start
        and base[len(base) - 1 - tail] == edited[len(edited) - 1 - tail]
    ):
        tail += 1

    return ByteRange(start, max(len(base), len(edited)) - tail)


def is_text(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_SUFFIXES


def merge_three_way(
    path: str, base: bytes, edits: list[Edit], allow_binary: bool
) -> MergeOutcome:
    """Combine independent edits to one file, using the base as ancestor."""
    if len(edits) == 1:
        return MergeOutcome(edits[0].source.read_bytes())

    versions = [edit.source.read_bytes() for edit in edits]
    names = [edit.mod_name for edit in edits]

    # Identical edits are not a disagreement.
    if all(version == versions[0] for version in versions):
        return MergeOutcome(versions[0])

    ranges = [changed_range(base, version) for version in versions]
    for i, left in enumerate(ranges):
        for j in range(i + 1, len(ranges)):
            if left.overlaps(ranges[j]):
                return MergeOutcome(
                    conflicts=[
                        Conflict(
                            path,
                            ConflictKind.OVERLAPPING,
                            [names[i], names[j]],
                            f"{names[i]} {left}, {names[j]} {ranges[j]} — overlapping",
                        )
                    ]
                )

    if not is_text(path) and not allow_binary:
        detail = ", ".join(f"{n} {r}" for n, r in zip(names, ranges, strict=True))
        return MergeOutcome(
            conflicts=[
                Conflict(
                    path,
                    ConflictKind.BINARY,
                    names,
                    f"{detail} — disjoint, but binary merge is opt-in "
                    "(--merge-binary); disjoint bytes can still be "
                    "semantically incompatible",
                )
            ]
        )

    return MergeOutcome(_apply_disjoint(base, versions, ranges))


def _apply_disjoint(base: bytes, versions: list[bytes], ranges: list[ByteRange]) -> bytes:
    """Splice non-overlapping edits onto the base, left to right."""
    ordered = sorted(
        (r, v) for r, v in zip(ranges, versions, strict=True) if not r.is_empty
    )
    out = bytearray()
    cursor = 0
    for span, version in ordered:
        out += base[cursor : span.start]
        # The edited region, measured from the same prefix in the new version.
        tail = len(base) - span.end
        out += version[span.start : len(version) - tail]
        cursor = span.end
    out += base[cursor:]
    return bytes(out)


def detect(chain: Chain, plan: Plan, base: Path, allow_binary: bool) -> list[Conflict]:
    """Every conflict in a chain, collected so one run reports all of them."""
    found: list[Conflict] = []
    found += _exclusive_conflicts(chain, plan)

    for file_plan in plan.files:
        for edits in [file_plan.whole_file, *file_plan.members.values()]:
            independent = effective_edits(chain, edits)
            if len(independent) < 2:
                continue
            target = independent[0].target
            ancestor = _ancestor_bytes(base, target)
            outcome = merge_three_way(str(target), ancestor, independent, allow_binary)
            found += outcome.conflicts

    return found


def effective_edits(chain: Chain, edits: list[Edit]) -> list[Edit]:
    """Drop edits that a later mod deliberately supersedes via dependency.

    If B depends on A (directly or transitively), B's edit wins and A's is
    neither a conflict nor applied. Only mutually independent edits remain.

    Both conflict detection and the builder must use this, or they disagree
    about what is in play — detection reports clean while the build hits a
    phantom conflict.
    """
    keep: list[Edit] = []
    for edit in edits:
        superseded = any(
            other is not edit and _depends_on(chain, other.mod_name, edit.mod_name)
            for other in edits
        )
        if not superseded:
            keep.append(edit)
    return keep


def _depends_on(chain: Chain, dependent: str, dependency: str) -> bool:
    """Whether `dependent` requires `dependency`, transitively."""
    mod = next((m for m in chain.mods if m.name == dependent), None)
    if mod is None:
        return False
    pending = [req.name for req in mod.manifest.dependencies]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name == dependency:
            return True
        if name in seen:
            continue
        seen.add(name)
        nested = next((m for m in chain.mods if m.name == name), None)
        if nested is not None:
            pending += [req.name for req in nested.manifest.dependencies]
    return False


def _exclusive_conflicts(chain: Chain, plan: Plan) -> list[Conflict]:
    found: list[Conflict] = []
    for mod in chain.mods:
        for claimed in mod.manifest.exclusive:
            file_plan = plan.for_path(claimed)
            if file_plan is None:
                continue
            others = [n for n in file_plan.contributors() if n != mod.name]
            if others:
                found.append(
                    Conflict(
                        claimed,
                        ConflictKind.EXCLUSIVE,
                        [mod.name, *others],
                        f"claimed exclusively by {mod.name}; "
                        f"also modified by {', '.join(others)}",
                    )
                )
    return found


def _ancestor_bytes(base: Path, target: TargetPath) -> bytes:
    """The base version of a target, for use as the merge ancestor."""
    disc_file = base / target.disc_path
    if not disc_file.exists():
        return b""
    data = disc_file.read_bytes()
    if not target.is_member:
        return data

    if lz77.is_lz77(data):
        data = lz77.decompress(data)
    if not u8.is_u8(data):
        return b""
    entry = next((e for e in u8.read(data) if e.path == target.member), None)
    return u8.extract(data, entry) if entry else b""
