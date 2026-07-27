"""Flattening a dependency graph into one concrete install order.

Dependencies form a DAG and the same mod can be reached by several paths, so the
resolver produces a list where each mod appears exactly once:

    depth-first post-order, in declaration order, keeping first occurrence

Post-order is what guarantees the invariant that matters — a mod is emitted only
after everything it depends on, so later layers can override earlier ones.
Declaration order makes it deterministic, so a build reproduces.
"""

from __future__ import annotations

from dataclasses import dataclass

from bleck.common.errors import BleckError

from .manifest import Requirement
from .registry import Mod, Registry


class ResolutionError(BleckError):
    pass


@dataclass(frozen=True)
class ChainEntry:
    """One mod in the resolved install order."""

    mod: Mod
    required_by: str
    """Who pulled this in; empty for the target itself."""

    @property
    def is_target(self) -> bool:
        return not self.required_by


@dataclass(frozen=True)
class Chain:
    """The full install order, dependencies first, target last."""

    entries: list[ChainEntry]

    @property
    def target(self) -> Mod:
        return self.entries[-1].mod

    @property
    def mods(self) -> list[Mod]:
        return [entry.mod for entry in self.entries]

    def position_of(self, name: str) -> int:
        """Index in the install order; -1 if absent. Later wins."""
        return next(
            (i for i, entry in enumerate(self.entries) if entry.mod.name == name), -1
        )

    def applies_before(self, earlier: str, later: str) -> bool:
        first, second = self.position_of(earlier), self.position_of(later)
        return 0 <= first < second


def resolve(registry: Registry, name: str) -> Chain:
    """Linearise `name` and its transitive dependencies."""
    target = registry.require(name)

    entries: list[ChainEntry] = []
    seen: set[str] = set()
    # Names on the current descent path, for cycle reporting.
    visiting: list[str] = []

    def descend(mod: Mod, required_by: str) -> None:
        if mod.name in seen:
            return
        if mod.name in visiting:
            cycle = " → ".join([*visiting[visiting.index(mod.name) :], mod.name])
            raise ResolutionError(f"dependency cycle: {cycle}")

        visiting.append(mod.name)
        for requirement in mod.manifest.dependencies:
            descend(_lookup(registry, requirement, mod.name), mod.name)
        visiting.pop()

        seen.add(mod.name)
        entries.append(ChainEntry(mod, required_by))

    descend(target, "")
    return Chain(entries)


def _lookup(registry: Registry, requirement: Requirement, required_by: str) -> Mod:
    found = registry.find(requirement.name)
    if found is None:
        raise ResolutionError(
            f"{required_by} requires {requirement}, which is not installed "
            f"in {registry.root}"
        )
    if not requirement.is_satisfied_by(found.manifest.version):
        raise ResolutionError(
            f"{required_by} requires {requirement}, "
            f"but {found.name} {found.manifest.version} is installed"
        )
    return found


def check_bases(chain: Chain, base: str) -> list[str]:
    """Mods in the chain that target a different base build.

    Returns human-readable complaints; empty means every mod agrees. A mod built
    against eu0 cannot be trusted on us0 — the file lists differ.
    """
    return [
        f"{entry.mod.name} targets base {entry.mod.manifest.base!r}, not {base!r}"
        for entry in chain.entries
        if entry.mod.manifest.base and entry.mod.manifest.base != base
    ]
