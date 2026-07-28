"""Errors raised while reading a mod's declarations.

⚠️ One class, in one place, deliberately. `manifest.py`, `codespec.py` and
`placements.py` all raise it, and when the split first happened each defined its
own — so `except manifest.ManifestError` silently stopped catching two thirds of
the errors it used to. Nineteen tests caught that; a user would have caught a
traceback.
"""

from __future__ import annotations

from bleck.common.errors import BleckError


class ManifestError(BleckError):
    """A manifest is missing, malformed, or self-inconsistent."""
