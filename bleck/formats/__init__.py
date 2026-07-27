"""File formats used by Super Paper Mario.

`lz77` and `u8` are the container layers; `detect` identifies a blob by
unwrapping them as far as they go.
"""

from . import detect, lz77, u8

__all__ = ["detect", "lz77", "u8"]
