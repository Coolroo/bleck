"""The only place that reads the environment.

Every variable the toolkit understands is declared here, so `DECLARED` is the
complete list — no hunting through the codebase to find what can be configured.
A lint rule (`lint_plugins/env_access.py`) enforces that `os.environ` and
`os.getenv` appear nowhere else.

To add a variable: declare an `EnvVar`, add it to `DECLARED`, and expose a
reader beside the others.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

TRUTHY = frozenset({"1", "true", "yes", "on"})
FALSEY = frozenset({"0", "false", "no", "off", ""})


@dataclass(frozen=True)
class EnvVar:
    """A single environment variable the toolkit understands."""

    name: str
    default: str = ""
    description: str = ""


@dataclass(frozen=True)
class EnvSetting:
    """A variable's current state, for diagnostics."""

    variable: EnvVar
    value: str
    is_set: bool

    @property
    def is_default(self) -> bool:
        return not self.is_set


# --- declarations ---------------------------------------------------------

#: Everything the toolkit generates or is handed lives under one directory.
#: These are large (a disc image is ~424 MB, an extract ~400 MB), all
#: gitignored, and none of them are source — grouping them keeps the repository
#: root readable and makes "what can I safely delete?" a single answer.
#:
#: `mods/` is deliberately NOT here: manifests and scripts are committed.
WORK_DIR = "work"


WIT = EnvVar(
    "BLECK_WIT",
    description="Path to the wit binary, if it is not on PATH",
)
DOLPHIN_TOOL = EnvVar(
    "BLECK_DOLPHIN_TOOL",
    description="Path to dolphin-tool, if it is not on PATH",
)
DOLPHIN = EnvVar(
    "BLECK_DOLPHIN",
    description="Path to the Dolphin emulator itself, used by `bleck launch`",
)
PPC_GCC = EnvVar(
    "BLECK_PPC_GCC",
    description="Path to the PowerPC cross-compiler used to build code mods",
)
WSTRT = EnvVar(
    "BLECK_WSTRT",
    description="Path to wstrt, used to embed the Gecko loader into the DOL",
)
GECKO_DIR = EnvVar(
    "BLECK_GECKO_DIR",
    default="work/gecko",
    description="Directory of per-version loader codelists, e.g. loader.eu0.txt",
)
HEADERS_DIR = EnvVar(
    "BLECK_HEADERS_DIR",
    default="work/headers",
    description="Include directory for native code mods, e.g. spm-headers/include",
)
SYMBOLS_DIR = EnvVar(
    "BLECK_SYMBOLS_DIR",
    default="work/symbols",
    description="Directory of per-version symbol lists, e.g. spm.eu0.lst",
)
EXTRACT_ROOT = EnvVar(
    "BLECK_EXTRACT_ROOT",
    default="work/extracted",
    description="Where `bleck extract` puts output when no destination is given",
)
NO_COLOR = EnvVar(
    "NO_COLOR",
    description="Set to any value to disable coloured output (no-color.org)",
)
MODS_DIR = EnvVar(
    "BLECK_MODS_DIR",
    default="mods",
    description="Where mods live; dependencies resolve against this directory",
)
BASE_DIR = EnvVar(
    "BLECK_BASE_DIR",
    default="work/extracted/eu0",
    description="The pristine extracted base game. Never written to",
)
BUILD_DIR = EnvVar(
    "BLECK_BUILD_DIR",
    default="work/build",
    description="Where mod staging and output ISOs go",
)

DECLARED: list[EnvVar] = [
    WIT,
    DOLPHIN_TOOL,
    DOLPHIN,
    PPC_GCC,
    WSTRT,
    GECKO_DIR,
    HEADERS_DIR,
    SYMBOLS_DIR,
    EXTRACT_ROOT,
    NO_COLOR,
    MODS_DIR,
    BASE_DIR,
    BUILD_DIR,
]


# --- readers --------------------------------------------------------------


def text(variable: EnvVar) -> str:
    """The variable's value, or its declared default."""
    return os.environ.get(variable.name) or variable.default


def flag(variable: EnvVar) -> bool:
    """Interpret the variable as a boolean.

    Unrecognised values count as true: a user who sets a flag to anything
    meant to turn it on.
    """
    raw = os.environ.get(variable.name)
    if raw is None:
        return False
    normalised = raw.strip().lower()
    if normalised in FALSEY:
        return False
    return normalised in TRUTHY or True


def path(variable: EnvVar) -> Path | None:
    """The variable as a filesystem path, or None if unset and undefaulted."""
    value = text(variable)
    return Path(value) if value else None


def is_set(variable: EnvVar) -> bool:
    return variable.name in os.environ


def describe_all() -> list[EnvSetting]:
    """Current state of every declared variable, for `--debug`-style output."""
    return [
        EnvSetting(variable, text(variable), is_set(variable)) for variable in DECLARED
    ]
