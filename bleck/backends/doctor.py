"""Whether every external tool `bleck` shells out to is there and usable.

Two questions, and the second is the one that bites. **Presence on disk is not
usability**: Apple Silicon refuses to run an unsigned arm64 binary and reports
it as an immediate `SIGKILL` with no output at all, so a tool this module can
see, name and describe may still be dead. Each located tool is therefore
executed with a cheap argument (`ToolKey.probe`) and judged on what happened.

⚠️ **Absent is not broken.** Somebody doing asset work with no PowerPC
cross-compiler is correctly set up for what they do, and saying otherwise turns
a report into noise. Only `ToolState.is_misconfiguration` states counted.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from bleck import platforms
from bleck.backends.disc import ToolSearch, killed_advice, locate
from bleck.platforms import ToolKey

#: A version banner is instant everywhere. Anything slower than this is not
#: answering, which is itself the finding.
PROBE_TIMEOUT = 20.0


class ToolState(StrEnum):
    """What a tool turned out to be. Values are what the report prints."""

    WORKING = "ok"
    """Found, executed, and answered as expected."""

    ABSENT = "absent"
    """Not found anywhere. Informational -- see the module docstring."""

    BAD_OVERRIDE = "misconfigured"
    """An override variable names a path that does not exist."""

    KILLED = "killed"
    """The OS terminated it on a signal. The Apple Silicon signing trap."""

    UNRUNNABLE = "will not run"
    """Present, but the process could not be started or never answered."""

    ERRORED = "errors"
    """It ran and failed, so it is installed but not in working order."""

    @property
    def is_misconfiguration(self) -> bool:
        """Whether this state is somebody's mistake rather than a free choice.

        ⚠️ The exit code turns on exactly this. `ABSENT` is deliberately not
        here: a tool nobody installed gates only the commands that use it.
        """
        return self is not ToolState.WORKING and self is not ToolState.ABSENT


@dataclass(frozen=True)
class ToolStatus:
    """One external tool, as found on this machine."""

    key: ToolKey
    state: ToolState

    path: str = ""
    where: str = ""
    """How it was reached: an override variable, `PATH`, or a directory."""

    detail: str = ""
    """What went wrong, in the tool's own words where it had any."""

    remedy: str = ""
    """What to do about it, when there is something to do."""

    @property
    def is_working(self) -> bool:
        return self.state is ToolState.WORKING

    @property
    def is_problem(self) -> bool:
        return self.state.is_misconfiguration


@dataclass(frozen=True)
class Diagnosis:
    """Every tool, on this platform, right now."""

    platform: str
    tools: list[ToolStatus]

    @property
    def problems(self) -> list[ToolStatus]:
        return [tool for tool in self.tools if tool.is_problem]

    @property
    def working(self) -> list[ToolStatus]:
        return [tool for tool in self.tools if tool.is_working]

    @property
    def absent(self) -> list[ToolStatus]:
        return [tool for tool in self.tools if tool.state is ToolState.ABSENT]

    @property
    def is_misconfigured(self) -> bool:
        return bool(self.problems)


def check(key: ToolKey, run: bool = True) -> ToolStatus:
    """Find one tool and, unless told not to, prove it executes."""
    search = locate(key)
    if not search.found:
        return _not_found(search)
    if not run:
        return ToolStatus(key, ToolState.WORKING, search.path, search.where)
    return _probe(search)


def check_all(run: bool = True) -> Diagnosis:
    """Every tool this platform describes, in the order `ToolKey` declares."""
    return Diagnosis(
        platform=platforms.current().name,
        tools=[check(key, run=run) for key in ToolKey],
    )


def _not_found(search: ToolSearch) -> ToolStatus:
    state = ToolState.BAD_OVERRIDE if search.override_is_broken else ToolState.ABSENT
    return ToolStatus(search.key, state, detail=search.problem)


def _probe(search: ToolSearch) -> ToolStatus:
    """Run the located binary and read the outcome.

    ⚠️ `expect_success=False` covers a tool with no version flag at all, where
    a usage message and a failure status still prove the thing executed. The
    question asked is "can this run", not "did it like its arguments".
    """
    probe = search.key.probe
    try:
        result = subprocess.run(
            [search.path, *probe.args],
            capture_output=True,
            text=True,
            check=False,
            timeout=PROBE_TIMEOUT,
        )
    except OSError as exc:
        return _failed(search, ToolState.UNRUNNABLE, f"could not be started: {exc}")
    except subprocess.TimeoutExpired:
        return _failed(
            search,
            ToolState.UNRUNNABLE,
            f"did not answer within {PROBE_TIMEOUT:.0f}s",
        )

    if result.returncode < 0:
        return _failed(
            search,
            ToolState.KILLED,
            f"was killed on signal {-result.returncode}, printing nothing",
        )
    if probe.expect_success and result.returncode != 0:
        said = (result.stderr or result.stdout).strip().splitlines()
        detail = said[0] if said else "and said nothing"
        return _failed(
            search,
            ToolState.ERRORED,
            f"exited {result.returncode} from "
            f"`{Path(search.path).name} {' '.join(probe.args)}`: {detail}",
        )
    return ToolStatus(search.key, ToolState.WORKING, search.path, search.where)


def _failed(search: ToolSearch, state: ToolState, detail: str) -> ToolStatus:
    remedy = killed_advice(search.path) if state is ToolState.KILLED else ""
    return ToolStatus(
        search.key, state, search.path, search.where, detail=detail, remedy=remedy
    )
