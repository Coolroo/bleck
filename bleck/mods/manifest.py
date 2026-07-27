"""Mod manifests: `mod.json`.

A manifest declares identity, which base build it targets, what it depends on,
and which paths it claims exclusively.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bleck.common.errors import BleckError

MANIFEST_NAME = "mod.json"
# Named `overlay`, not `files`: the disc's own data partition is `files/`,
# so `overlay/files/...` reads correctly where `files/files/...` would not.
OVERLAY_DIR = "overlay"
SCHEMA_VERSION = 1

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_REQUIREMENT_RE = re.compile(r"^(>=|<=|==)?\s*(\d+\.\d+\.\d+)$")


class ManifestError(BleckError):
    """A manifest is missing, malformed, or self-inconsistent."""


@dataclass(frozen=True, order=True)
class Version:
    """A semantic version. Ordered, so requirements compare directly."""

    major: int = 0
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, text: str) -> Version:
        match = _VERSION_RE.match(text.strip())
        if not match:
            raise ManifestError(f"bad version {text!r}, expected MAJOR.MINOR.PATCH")
        return cls(int(match[1]), int(match[2]), int(match[3]))


@dataclass(frozen=True)
class Requirement:
    """A dependency on another mod, optionally version-constrained."""

    name: str
    operator: str = ""
    version: Version | None = None

    def __str__(self) -> str:
        if self.version is None:
            return self.name
        return f"{self.name} {self.operator}{self.version}"

    def is_satisfied_by(self, candidate: Version) -> bool:
        if self.version is None:
            return True
        if self.operator == ">=":
            return candidate >= self.version
        if self.operator == "<=":
            return candidate <= self.version
        return candidate == self.version

    @classmethod
    def parse(cls, name: str, spec: str) -> Requirement:
        if not spec:
            return cls(name)
        match = _REQUIREMENT_RE.match(spec.strip())
        if not match:
            raise ManifestError(
                f"bad version requirement {spec!r} for {name!r}; "
                "expected e.g. '>=1.2.0', '==1.0.0'"
            )
        return cls(name, match[1] or "==", Version.parse(match[2]))


@dataclass(frozen=True)
class Manifest:
    """A mod's declared identity and relationships."""

    name: str
    version: Version = field(default_factory=Version)
    description: str = ""
    author: str = ""
    base: str = ""
    created: str = ""
    dependencies: list[Requirement] = field(default_factory=list)
    exclusive: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        body = {
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "version": str(self.version),
            "description": self.description,
            "author": self.author,
            "base": self.base,
            "created": self.created,
            "dependencies": [
                {"name": r.name, "version": f"{r.operator}{r.version}"}
                if r.version
                else {"name": r.name}
                for r in self.dependencies
            ],
            "exclusive": self.exclusive,
            "remove": self.remove,
        }
        return json.dumps(body, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str, source: str = MANIFEST_NAME) -> Manifest:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{source}: invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ManifestError(f"{source}: expected a JSON object")

        schema = raw.get("schema", SCHEMA_VERSION)
        if schema != SCHEMA_VERSION:
            raise ManifestError(
                f"{source}: unsupported schema {schema!r} "
                f"(this build understands {SCHEMA_VERSION})"
            )

        name = raw.get("name", "")
        if not name:
            raise ManifestError(f"{source}: 'name' is required")

        return cls(
            name=name,
            version=Version.parse(raw.get("version", "0.0.0")),
            description=raw.get("description", ""),
            author=raw.get("author", ""),
            base=raw.get("base", ""),
            created=raw.get("created", ""),
            dependencies=_parse_dependencies(raw.get("dependencies", []), source),
            exclusive=list(raw.get("exclusive", [])),
            remove=list(raw.get("remove", [])),
        )


def _parse_dependencies(raw: object, source: str) -> list[Requirement]:
    if not isinstance(raw, list):
        raise ManifestError(f"{source}: 'dependencies' must be a list")
    out: list[Requirement] = []
    for item in raw:
        if isinstance(item, str):
            out.append(Requirement(item))
            continue
        if not isinstance(item, dict) or "name" not in item:
            raise ManifestError(
                f"{source}: each dependency needs a 'name' (got {item!r})"
            )
        out.append(Requirement.parse(item["name"], item.get("version", "")))
    return out


def read(directory: Path) -> Manifest:
    path = directory / MANIFEST_NAME
    if not path.exists():
        raise ManifestError(f"no {MANIFEST_NAME} in {directory}")
    return Manifest.from_json(path.read_text(), source=str(path))


def write(directory: Path, manifest: Manifest) -> None:
    (directory / MANIFEST_NAME).write_text(manifest.to_json())
