"""Mods: overlays on an immutable extracted base.

A mod holds only what differs from the base game, plus a manifest declaring its
identity and dependencies. Chains of mods linearise into one install order and
merge onto the base at build time; the base is never written to.
"""

from . import builder, conflicts, manifest, overlay, registry, resolver

__all__ = ["builder", "conflicts", "manifest", "overlay", "registry", "resolver"]
