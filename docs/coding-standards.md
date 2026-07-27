# Coding Standards

Enforced automatically. Run everything with:

```bash
./scripts/lint.sh          # check
./scripts/lint.sh --fix    # apply what can be applied, then check
```

The script runs all checks even when an early one fails, so one pass shows every
problem instead of making you re-run after each fix. It prefers `.venv/bin/python`
and falls back to `python3`.

Install the toolchain with `uv sync --extra dev` (or `pip install -e ".[dev]"`).

Dependency versions are pinned in **`uv.lock`, which is committed** — the point
is that everyone resolves the same versions. This matters here: pylint 4.0.6 has
a behaviour our config works around (`jobs` must stay 1), and silent version
drift would resurface it.

---

## Rule 1 — Return named types, never `dict` or `tuple`

**Enforced by** `lint_plugins/container_returns.py` (pylint `C9001`).

A signature should say what comes back. `tuple[int, int]` says nothing about
which value is which, and `dict[str, str]` hides the key set from readers and
type checkers alike.

```python
# rejected
def find_match(...) -> tuple[int, int]: ...
def read_header(...) -> dict[str, str]: ...
def list_entries(...) -> list[tuple[str, bytes]]: ...   # nested counts too

# correct
@dataclass(frozen=True)
class Match:
    length: int
    displacement: int

def find_match(...) -> Match: ...
```

**Nesting is checked.** `list[tuple[str, int]]` fails — use `list[Item]`.
Unions and `typing.Tuple[...]` are checked too, as are string annotations under
`from __future__ import annotations`.

Containers of *named* things are fine: `list[U8Entry]` is clear and passes.

Escape hatch for genuine library boundaries — rare, and worth a comment:

```python
def as_kwargs(self) -> dict[str, str]:  # pylint: disable=container-return
```

## Rule 2 — Environment access lives in one module

**Enforced by** `lint_plugins/env_access.py` (pylint `C9002`).

`os.environ`, `os.getenv`, `os.putenv`, `os.unsetenv`, and
`from os import environ` are rejected everywhere except
[`bleck/common/env.py`](../bleck/common/env.py).

Scattered environment reads are invisible: there is no list of what can be
configured, and a typo'd name fails silently as an empty default.

To add a variable, declare it and add it to `DECLARED`:

```python
MY_SETTING = EnvVar(
    "BLECK_MY_SETTING",
    default="something",
    description="What this controls",
)
DECLARED: list[EnvVar] = [..., MY_SETTING]
```

Then read it with `env.text(...)`, `env.flag(...)`, or `env.path(...)`.
`env.describe_all()` returns the current state of every declared variable.

Currently declared: `BLECK_WIT`, `BLECK_DOLPHIN_TOOL`, `BLECK_EXTRACT_ROOT`,
`NO_COLOR`.

---

## Running the linters

```bash
uv run python scripts/lint.py --fix   # anywhere, no activation needed
./scripts/lint.sh --fix               # POSIX
powershell scripts\lint.ps1 -fix       # Windows
```

The shell wrappers are thin; the logic lives in `scripts/lint.py` so Windows is
a first-class target rather than an afterthought.

## Ruff

Formatter plus lint rules: pycodestyle, pyflakes, import sorting, pyupgrade,
bugbear, simplify, comprehensions, return clarity, pathlib preference, unused
arguments, and Ruff's own checks. Line length 90.

`E501` is off because the formatter owns line length. `RET504` is off because a
named variable before `return` often documents intent.

**Imports are absolute** (`from bleck.formats import lz77`), not parent-relative.
You can see where something comes from without counting dots.

## Pylint

Carries the two project-specific plugins above, plus its own analysis.

Disabled: the three `missing-*-docstring` checks (worth reviewing, not worth
failing a build over), `too-few-public-methods` (small dataclasses are the point
here), `duplicate-code` (noisy across parallel command modules), and
`redefined-outer-name` (requesting a pytest fixture shadows its name by design —
it fired on every fixture-using test and flagged nothing real).

⚠️ **`jobs` must stay 1.** With `jobs > 1`, pylint loads custom plugins once per
worker and reports every plugin message **twice**. Verified on pylint 4.0.6.
The parallelism isn't worth duplicated output.

---

## Tests

```bash
.venv/bin/python -m pytest          # 73 tests, ~2s
.venv/bin/python -m pytest -m slow  # opt into the slow ones
```

Two constraints, both from the hardware (Raspberry Pi 4, 4×1.8 GHz):

- The LZ77 compressor runs **~12 s/MB**, so tests compress only small synthetic
  inputs. Anything compressing real game data is marked `slow` and deselected by
  default.
- Game data is not in the repo, so tests needing it skip cleanly. A fresh clone
  runs green.
