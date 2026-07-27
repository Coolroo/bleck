---
title: Coding standards
description: Rules enforced by the linters, not by review
---

Two project-specific rules are enforced by custom pylint plugins. They fail the
build; they are not suggestions.

## Return named types

!!! warning

    **Never return `dict` or `tuple`** — including nested, like
    `list[tuple[str, int]]`. Enforced as pylint `C9001`.

A signature should say what comes back. `tuple[int, int]` tells a reader
nothing about which value is which, and `dict[str, str]` hides the key set from
readers and type checkers alike.

```python
# rejected
def find_match(...) -> tuple[int, int]: ...
def read_header(...) -> dict[str, str]: ...
def list_entries(...) -> list[tuple[str, bytes]]: ...

# correct
@dataclass(frozen=True)
class Match:
    length: int
    displacement: int

def find_match(...) -> Match: ...
```

Containers of *named* things are fine — `list[U8Entry]` is clear and passes.

For genuine library boundaries there is an escape hatch, worth a comment:

```python
def as_kwargs(self) -> dict[str, str]:  # pylint: disable=container-return
```

!!! tip

    This rule has repeatedly improved the code rather than obstructing it.
    `match.is_usable` reads better than comparing an anonymous tuple element, and
    grouping six positional parameters into a `BuildContext` made the call sites
    clearer.

## Environment access in one place

!!! warning

    `os.environ` and `os.getenv` are rejected outside `bleck/common/env.py`.
    Enforced as pylint `C9002`.

Scattered environment reads are invisible — there is no list of what can be
configured, and a typo'd name fails silently as an empty default.

```python
MY_SETTING = EnvVar(
    "BLECK_MY_SETTING",
    default="something",
    description="What this controls",
)
DECLARED: list[EnvVar] = [..., MY_SETTING]
```

Then read with `env.text(...)`, `env.flag(...)` or `env.path(...)`.

## Platform differences are data

Add a field to a `PlatformProfile` in `bleck/platforms/`, never an
`if system == ...` elsewhere.

| | |
|---|---|
| Tool names | `dolphin-tool`, `DolphinTool.exe`, `DolphinTool` |
| Search directories | `/usr/games`, `C:\Program Files\Dolphin`, `Dolphin.app/Contents/MacOS` |
| Filesystem quirks | read-only deletion, `.DS_Store` filtering |

## Ruff and pylint

Ruff handles formatting plus pycodestyle, pyflakes, import sorting, pyupgrade,
bugbear, simplify, comprehensions, return clarity, pathlib preference and
unused arguments. Line length 90.

??? note "Why pylint runs with jobs = 1"

    With `jobs > 1`, pylint loads custom plugins once per worker and reports every
    plugin message **twice**. Verified on pylint 4.0.6. The parallelism is not worth
    duplicated output.

    This is also why `uv.lock` is committed — silent version drift would resurface
    issues like this one.

## Recording expensive results

!!! info

    Some operations are slow: the compressor runs ~12 s/MB, and reference encoders
    take minutes per file. **Measure once, write the number into `docs/`, and cite
    the recorded value.**

    Re-run a benchmark only when the code under test changed — never just to restate
    a number.
