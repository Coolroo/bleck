"""The one exception a code build raises.

Its own module because `sources`, `patches`, `hooks` and `parts` all raise it
and none of them may import another — a shared error type in any one of them
would make the import graph a ring.
"""

from __future__ import annotations

from bleck.common.errors import BleckError


class CodeError(BleckError):
    """A mod's script could not be turned into a module."""
