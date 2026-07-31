"""Where an exported file lands under the export root.

`texture export`, `model export` and `sound export` used to write every file
into one directory. A full export is ~21,780 PNGs, 864 `.glb` and 135 `.wav`,
so that directory held about 22,800 entries and no file manager or shell would
open it usefully.

Each kind now gets its own subtree, and inside it the disc's own layout is
mirrored from the `source` path the entry already carries:

    textures/files/eff/effdata.tpl/0.png
    textures/files/map/aa1_01.bin/aa1_01/tex/wall.tpl/0.png
    models/files/a/p_wii_mario.glb
    sounds/files/sound/sys_title1_44k_lp.wav

⚠️ **The manifests stay at the export root.** Dimentio reads
`<root>/textures.json` and joins each entry's `file` onto `<root>`, so `file`
has to be a posix path relative to the root and nothing else.

⚠️ **Components are escaped, not stripped.** A texture's name embeds archive
members and an image index, and the disc is not the only source of a component
— a name Windows refuses (`<>:"|?*`, a trailing dot, `NUL`) or one that walks
upwards (`..`) has to become a *different* name rather than a missing file or a
write outside the root. The escaping is percent-hex and covers `%` itself, so
it is reversible: two different disc paths can never land on one file.
"""

from __future__ import annotations

from pathlib import Path

#: Characters no Windows path component may hold. `/` and `\` are separators,
#: so a component carrying one is escaped rather than silently split.
FORBIDDEN = '<>:"|?*\\/'

#: Windows refuses these as the stem of a file name, extension or not, so
#: `nul.png` cannot be created at all.
RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in "123456789"}
    | {f"LPT{digit}" for digit in "123456789"}
)


def _escaped(char: str) -> str:
    if char == "%" or char in FORBIDDEN or ord(char) < 0x20 or ord(char) == 0x7F:
        return f"%{ord(char):02X}"
    return char


def escape(component: str) -> str:
    """One path component, usable as a file name on every supported platform.

    Injective: distinct inputs give distinct outputs, because `%` is escaped
    first, so two disc paths cannot collide on one exported file.
    """
    out = "".join(_escaped(char) for char in component)
    if out.endswith((".", " ")):
        out = f"{out[:-1]}%{ord(out[-1]):02X}"
    if out.split(".", 1)[0].upper() in RESERVED:
        out = f"%{ord(out[0]):02X}{out[1:]}"
    return out


def place(kind: str, directory: str, leaf: str) -> str:
    """`<kind>/<directory>/<leaf>`, escaped, posix-separated, root-relative.

    `directory` is a disc path such as `files/map/aa1_01.bin`, optionally with
    an archive member joined on. Empty components are dropped so a caller can
    append a member unconditionally, and `.` is dropped so a file at the disc
    root -- whose `PurePosixPath.parent` is `.` -- does not gain a directory.
    """
    parts = [kind, *directory.split("/"), leaf]
    return "/".join(escape(part) for part in parts if part not in ("", "."))


class Tree:
    """Files written under one root, creating each directory exactly once.

    ⚠️ A full texture export spans a few thousand directories. `mkdir` per
    written file costs a syscall per level per file and is measurable at 22,800
    files; the set makes it one per directory.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self._made: set[Path] = {root}

    def write(self, relative: str, data: bytes) -> Path:
        """Write `data` at a root-relative posix path, as `place` returns."""
        target = self.root / relative
        if target.parent not in self._made:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._made.add(target.parent)
        target.write_bytes(data)
        return target
