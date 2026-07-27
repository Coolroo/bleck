"""Format detection.

SPM's containers nest — a map file is LZ77 wrapping U8 wrapping TPL — so
detection returns a stack rather than a single answer.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import lz77, u8

TPL_MAGIC = 0x0020AF30
BRSTM_MAGIC = b"RSTM"
BRSAR_MAGIC = b"RSAR"
REL_VERSIONS = {1, 2, 3}


@dataclass
class Layer:
    name: str
    detail: str = ""
    children: list[Layer] = field(default_factory=list)


def identify(data: bytes) -> Layer:
    """Describe a blob, unwrapping containers as far as they go."""
    if lz77.is_lz77(data):
        size = lz77.decompressed_size(data)
        layer = Layer("LZ77", f"type 0x10 -> {size:,} bytes")
        try:
            layer.children.append(identify(lz77.decompress(data)))
        except lz77.Lz77Error as exc:
            layer.children.append(Layer("<corrupt>", str(exc)))
        return layer

    if u8.is_u8(data):
        entries = u8.read(data)
        files = [e for e in entries if not e.is_dir]
        layer = Layer("U8", f"{len(entries)} entries ({len(files)} files)")
        for entry in files:
            child = Layer(entry.path, f"{entry.size:,}")
            inner = _leaf(u8.extract(data, entry))
            if inner:
                child.detail += f"  {inner}"
            layer.children.append(child)
        return layer

    leaf = _leaf(data)
    return Layer(leaf or "unknown", f"{len(data):,} bytes")


def _leaf(data: bytes) -> str:
    """Name a non-container format, or '' if unrecognised."""
    if len(data) < 4:
        return ""
    magic32 = struct.unpack_from(">I", data)[0]
    if magic32 == TPL_MAGIC:
        return "TPL"
    if data[:4] == BRSTM_MAGIC:
        return "BRSTM"
    if data[:4] == BRSAR_MAGIC:
        return "BRSAR"
    if len(data) >= 0x20:
        version = struct.unpack_from(">I", data, 0x1C)[0]
        sections, sec_off = struct.unpack_from(">2I", data, 0x0C)
        if version in REL_VERSIONS and sec_off == 0x4C and 0 < sections < 256:
            return f"REL v{version} ({sections} sections)"
    return ""


def render(layer: Layer, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    head = f"{prefix}{layer.name}"
    if layer.detail:
        head += f"  {layer.detail}"
    lines = [head]
    for child in layer.children:
        lines += render(child, indent + 1)
    return lines
