"""Errors raised while reading a mod's declarations.

⚠️ One class, in one place: `manifest.py`, `codespec.py` and `placements.py`
all raise it, so a per-module error class would break existing `except` sites.
"""

from __future__ import annotations

from bleck.common.errors import BleckError


class ManifestError(BleckError):
    """A manifest is missing, malformed, or self-inconsistent."""
