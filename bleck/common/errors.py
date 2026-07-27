"""Error types shared across the toolkit."""

from __future__ import annotations


class BleckError(Exception):
    """Base for every error the CLI reports without a traceback."""


class UserError(BleckError):
    """Something the user can fix — a bad path, a missing flag, a clobber."""
