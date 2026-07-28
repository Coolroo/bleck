"""The base every top-level API document shares.

`api_version` travels inside the payload so a stored document still says what it
is; the module path versions the code. Nested models carry no version — they are
never exchanged alone.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Contract version. Bump when a change would make an older reader misunderstand
#: a newer document; adding an optional field does not need one.
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
