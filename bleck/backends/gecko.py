"""Embedding the loader code into the game's own executable.

A code mod is inert on its own: the REL sits on the disc and nothing loads it.
Something has to run the Gecko loader code, and the usual answer is to paste it
into the emulator's cheat configuration — which fails silently in two separate
ways (listed under one section instead of two, or with cheats switched off) and
does not help on real hardware at all.

`wstrt patch --add-sect` avoids the whole problem by putting the code handler
*and* the codes into a new TEXT section of `main.dol` at `0x80001800`, and
redirecting the game's VBI hook into it. The loader then travels inside the
disc, so a built image boots with the mod active on a stock emulator with no
configuration, and on console with no Riivolution.

⚠️ `wstrt` supplies its own copy of the code handler. That matters for more than
convenience: it means `bleck` never ships, vendors, or even reads any part of
the GPLv3 Gecko handler. The only thing we supply is the per-version loader
codelist, and that is user-supplied too — see `codelist`.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bleck import platforms
from bleck.backends.disc import DiscError, find_tool
from bleck.common import env

WSTRT = platforms.WSTRT

#: A GCT is a trivial container: two magic words, the code words, a terminator.
GCT_HEADER = bytes.fromhex("00D0C0DE00D0C0DE")
GCT_TERMINATOR = bytes.fromhex("F000000000000000")


class GeckoError(DiscError):
    """The loader code is missing, malformed, or could not be embedded."""


@dataclass(frozen=True)
class Embedding:
    """A DOL that had loader code embedded into it."""

    dol: Path
    source: Path
    code_words: int
    grew_by: int

    def describe(self) -> str:
        return (
            f"embedded {self.code_words} code words from {self.source.name} "
            f"into {self.dol.name} (+{self.grew_by} bytes)"
        )


def build_gct(text: str, source: str = "codelist") -> bytes:
    """Assemble a Gecko codelist into a GCT.

    The input is the plain two-columns-of-hex format every SPM loader ships in.
    Parsing it here rather than shelling out keeps the one format `bleck` has to
    understand in Python, and gives a useful error instead of `wstrt`'s
    "Invalid WCH header" when the file is not what the user thought.
    """
    words: list[int] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*")):
            continue
        parts = stripped.split()
        if not all(len(part) == 8 for part in parts):
            raise GeckoError(
                f"{source}:{number}: expected 8-digit hex words, got {stripped!r}"
            )
        try:
            words += [int(part, 16) for part in parts]
        except ValueError as exc:
            raise GeckoError(f"{source}:{number}: not hexadecimal: {stripped!r}") from exc

    if not words:
        raise GeckoError(f"{source}: no code words found")
    if len(words) % 2:
        # Gecko codes are pairs; an odd count means a truncated file.
        raise GeckoError(
            f"{source}: {len(words)} code words is odd; Gecko codes come in pairs"
        )

    body = b"".join(word.to_bytes(4, "big") for word in words)
    return GCT_HEADER + body + GCT_TERMINATOR


def codelist(target: str, directory: Path | None = None) -> Path:
    """Locate the loader codelist for a game version.

    Not shipped with `bleck`. The SPM loader code is GPLv3, and keeping it
    user-supplied is what lets this toolkit stay unlicensed for now without
    the question becoming urgent -- the same reasoning as the symbol lists.
    """
    root = directory or env.path(env.GECKO_DIR) or Path("gecko")
    candidate = root / f"loader.{target}.txt"
    if candidate.exists():
        return candidate
    raise GeckoError(
        f"no loader codelist for {target!r} at {candidate}\n"
        f"  Pre-assembled loaders ship with "
        f"https://github.com/SeekyCt/spm-rel-loader (loader/).\n"
        f"  Put one at {candidate}, or set {env.GECKO_DIR.name} to its directory.\n"
        f"  That code is GPLv3, which is why bleck does not bundle it."
    )


def embed(dol: Path, gct: bytes, workdir: Path) -> Embedding:
    """Patch `dol` in place so it carries the loader.

    ⚠️ The DOL is detached first. A staged file is a hardlink to the pristine
    base, and `wstrt` rewrites in place, so patching without detaching would
    edit `extracted/<build>/sys/main.dol` — silently corrupting the one thing
    the whole build design exists to protect.
    """
    if not dol.exists():
        raise GeckoError(f"no DOL to patch at {dol}")

    workdir.mkdir(parents=True, exist_ok=True)
    gct_path = workdir / "loader.gct"
    gct_path.write_bytes(gct)

    before = dol.stat().st_size
    detached = workdir / "main.dol"
    shutil.copyfile(dol, detached)
    dol.unlink()
    shutil.copyfile(detached, dol)

    tool = find_tool(WSTRT)
    result = subprocess.run(
        [tool, "patch", str(dol), "--add-sect", str(gct_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GeckoError(f"wstrt could not patch the DOL:\n{detail}")

    after = dol.stat().st_size
    if after == before:
        # wstrt reports a dropped section as a warning and still exits 0.
        raise GeckoError(
            "wstrt left the DOL unchanged; the section was probably dropped "
            "for a size or address collision. Re-run wstrt with -vv to see why."
        )

    words = (len(gct) - len(GCT_HEADER) - len(GCT_TERMINATOR)) // 4
    return Embedding(dol=dol, source=gct_path, code_words=words, grew_by=after - before)


def embed_loader(staged: Path, target: str, workdir: Path) -> Embedding:
    """Embed the loader for `target` into a staged build's DOL."""
    text = codelist(target).read_text(encoding="utf-8")
    return embed(staged / "sys" / "main.dol", build_gct(text, target), workdir)
