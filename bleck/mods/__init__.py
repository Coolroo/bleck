"""Mods: overlays on an immutable extracted base.

A mod holds only what differs from the base, plus a manifest. Chains linearise
into one install order and merge onto the base at build time; the base is never
written to.

`manifest` — what a mod declares · `build` — chain to staged disc · `code` —
compiling the chain's code mods into the one `mod.rel` a disc carries.
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
