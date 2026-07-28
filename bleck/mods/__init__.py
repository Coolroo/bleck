"""Mods: overlays on an immutable extracted base.

A mod holds only what differs from the base game, plus a manifest declaring its
identity and dependencies. Chains of mods linearise into one install order and
merge onto the base at build time; the base is never written to.

Three subpackages, by what they are about:

- `manifest` — what a mod *declares*: identity, dependencies, its `code` block,
  its enemy placements
- `build` — turning a chain into a staged disc
- `code` — compiling the chain's code mods into the one `mod.rel` a disc carries
"""

from bleck.mods import code, manifest, registry, resolver
from bleck.mods.build import builder, conflicts, edits, overlay

__all__ = [
    "builder",
    "code",
    "conflicts",
    "edits",
    "manifest",
    "overlay",
    "registry",
    "resolver",
]
