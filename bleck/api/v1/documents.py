"""The base every top-level API document shares.

⚠️ **Versioned in two places, on purpose.**

`api_version` travels *inside* the payload, so a document that has been written
to disk, pasted into a bug report, or sat in another tool's database still says
what it is. A schema is not always at hand when a document is read.

The module path (`bleck.api.v1`) versions the *code*, so a v2 can be added
beside v1 rather than replacing it, and both can be served at once while
integrations move across.

Nested models -- a position, one edit -- deliberately carry no version. They are
never exchanged alone, and stamping every object would make a document mostly
version fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: This package's contract version. Bump it when a change would make an older
#: reader misunderstand a newer document -- a removed field, a changed meaning.
#: Adding an optional field does not need a bump; that is what `extra="forbid"`
#: on *input* and tolerant readers on output are for.
API_VERSION = 1


class Document(BaseModel):
    """A top-level document: something a program sends or receives whole."""

    model_config = ConfigDict(extra="forbid")

    api_version: int = Field(
        default=API_VERSION,
        description=(
            "Contract version this document was written against. Omitted on "
            "input means the current version."
        ),
    )

    @field_validator("api_version")
    @classmethod
    def _known_version(cls, value: int) -> int:
        if value != API_VERSION:
            raise ValueError(
                f"api_version {value} is not supported by this bleck, which "
                f"speaks version {API_VERSION}. "
                f"Upgrade bleck, or ask the sender for a v{API_VERSION} document."
            )
        return value
