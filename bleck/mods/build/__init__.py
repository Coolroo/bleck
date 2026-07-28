"""Turning a resolved chain of mods into a staged disc.

`builder` drives it; `overlay` decides what each file's edit means against the
base; `conflicts` decides when two mods may not both be applied; `edits` turns
declared placement changes into the files they imply.
"""

from bleck.mods.build import builder, conflicts, edits, overlay

__all__ = ["builder", "conflicts", "edits", "overlay"]
