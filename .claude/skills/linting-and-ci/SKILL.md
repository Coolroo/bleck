---
name: linting-and-ci
description: Use before finishing any change to Python in this repo, and when a pylint C9001/C9002/C9003 fires and you need to know what it wants. Covers scripts/lint.py (--fix vs --full and why the default is not enough), the four project-specific rules, and what each CI workflow actually runs.
---

# Linting and CI

```bash
./scripts/lint.sh --fix          # this branch's changed files only -- fast
./scripts/lint.sh --full         # every file; what CI runs
```

`scripts/lint.py` is the real implementation; `lint.sh` and `lint.ps1` are thin
wrappers (`python scripts\lint.py --full` works directly on Windows). Every
check runs even when an earlier one fails, so one pass shows every problem.

## ⚠️ The default is the diff, so a clean run is not a clean tree

Without `--full` it checks only what this branch touched — the merge base
against `origin/main` (then `main`, then `HEAD`), plus staged, unstaged and
**untracked** files. A brand-new module appears in no diff and is exactly the
one most worth checking, which is why untracked files are included.

⚠️ **Run `--full` before concluding the repo passes.** A per-file check cannot
see an import cycle between two files when only one of them changed, which is
precisely what `--full` caught when `code.replace` landed.

Targets are `bleck/`, `tests/`, `lint_plugins/`. ⛔ **`scripts/` is not linted**
— it is not in `TARGETS`, so a research script's style is not enforced.

Capture the output: `./scripts/lint.sh --full > "$CLAUDE_JOB_DIR/tmp/lint.txt" 2>&1`,
then read slices. Re-read the file when a filter was too narrow; never re-run.

## The four project rules

| code | rule |
|---|---|
| **C9001** `container-return` | **Never return `dict` or `tuple`** — including nested, like `list[tuple[str, int]]`. Define a small frozen dataclass so every value has a name. Escape hatch `# pylint: disable=container-return`, for genuine library boundaries only |
| **C9002** `direct-env-access` | `os.environ`, `os.environb`, `os.getenv`, `os.putenv`, `os.unsetenv` are rejected everywhere except **`bleck.common.env`**. Declare an `EnvVar`, add it to `DECLARED`, read with `env.text` / `env.flag` / `env.path` |
| **C9003** `comment-too-long` | A run of `#` comment lines may be at most **3**. `#:` attribute docs and tool directives (`# pylint: disable`) are exempt. Escape hatch `# pylint: disable=comment-too-long`, for a measured memory layout or a table whose columns need naming |
| `too-many-lines` (C0302) | pylint's stock **1000-line module ceiling**, inherited rather than configured. A module past it must be split |

The plugins live in `lint_plugins/{container_returns,comment_length,env_access}.py`
and are loaded from the repo root via `init-hook`. Full prose:
[`docs/coding-standards.md`](../../../docs/coding-standards.md).

⚠️ **`jobs = 1` in `[tool.pylint.main]` must stay 1.** With more, pylint loads
custom plugins once per worker and reports every plugin message twice (verified
on pylint 4.0.6).

Also enforced: ruff `E W F I UP B SIM C4 RET PTH ARG TID RUF`, line length
**90**, target `py313`; pylint `max-args 6`, `max-locals 18`, `max-returns 8`,
`max-attributes 12`.

## Tests

```bash
uv run pytest -q > "$CLAUDE_JOB_DIR/tmp/tests.txt" 2>&1
```

`addopts = "-m 'not slow'"` — the `slow` marker covers real-game-data
compression that takes minutes on a Pi. Opt in with `-m slow`. `pythonpath = ["."]`
is set so `uv run pytest` and a bare `pytest` behave like `python -m pytest`.

## What CI runs

**`.github/workflows/build.yml`**
- matrix `linux-x86_64` / `windows-x86_64` / `macos-arm64`: PyInstaller
  (`bleck.spec`), then **`scripts/smoke_binary.py dist/bleck`** against the
  artifact it just built.
- a separate job: `uv run pytest -q` and **`uv run python scripts/lint.py --full`**.

**`.github/workflows/docs.yml`** — `scripts/dump_builtins.py --check`, then
`mkdocs build --strict`.

**`.github/workflows/dimentio.yml`** — `cargo fmt --check`, `cargo clippy
--all-targets -- -D warnings`, `cargo test`, `cargo build --release`.

## `scripts/smoke_binary.py` — the release gate

```bash
uv run python scripts/smoke_binary.py work/dist/bleck
```

A PyInstaller build that *builds* proves almost nothing; the failures that
matter are all at runtime — a data file bundled to the wrong path, a command
module nothing references by name, a compiled dependency missing its native
half.

⚠️ **Nothing here names a row of a catalog.** Every expectation is read out of
**that catalog's own first row** — first, not chosen, because choosing is what
produced the last landmine: a check asked for item `fire_burst` and its English
name, D194 stopped shipping the game's own words, and Linux, Windows and macOS
all failed one assertion about a fact that no longer existed.

⚠️ **A catalog check asserts on a *field*, not a substring.** Ids and
`ITEM_ID_*` constants come from generated *modules* (D119), so they print from a
binary carrying no catalog at all — and `ITEM_ID_NULL` contains `NULL`.
`Check.fields` compares whitespace-separated columns for that reason, and the
map check and the item check deliberately assert on **opposite columns** (the id
for maps, the name for items) because a different half survives in each case.

⚠️ **Every check must be able to fail where it runs.** These need no extracted
disc, so they work on a CI machine that has never seen the game; the first
version's map check quietly required one and passed only where it could not
fail. `BLECK_BASE_DIR` is always *set*, never inherited — unrelated checks point
at an empty directory so every machine agrees.

`FLOORS` puts a floor under each catalog's size (300/300/200/400) so an emptied
or truncated catalog fails loudly. ⛔ `npccatalog.json` is bundled and
deliberately **not** checked — its only reader, `bleck setup show`, needs a real
setup file. D242 records `doorcatalog.json` having shipped in no binary at all.

## `scripts/container_verify.py` — the cross-compiler gate

```bash
uv run python scripts/container_verify.py
uv run python scripts/container_verify.py nop cxx-switch --out /tmp/v.txt
```

Rebuilds `nop`, `mr-l`, `goto-map`, `cxx-switch` from `example-mods/` with
whatever cross-compiler is installed and compares each `mod.rel` with the one in
that mod's overlay. Flags: `--mods-dir`, `--symbols`, `--out` (default
`work/build/container-verify.txt`).

- It **runs a control first** — a three-function module — so a page of
  `pyelf2rel` failures is never misread as "there is no compiler".
- ⚠️ **The reference is never overwritten**: each mod is copied to scratch and
  built there, because `example-mods/*/overlay/` is git-ignored and a clobbered
  reference could not be restored.
- ⚠️ **A missing reference is not an error** — a fresh checkout has no overlays;
  those mods report `BUILT`.
- A byte difference falls through to a structural comparison rather than
  stopping, because two ABIs legitimately differ.
- The default four need no extracted disc: a `code.hooks` guard word is read out
  of the base `main.dol` at build time, so a mod declaring one cannot build
  without `work/extracted/`.

See `arm64-container` for what it measured there.

## Related

- `bleck-cli-workflows` — the commands the smoke test exercises
- `verify-the-emitted-artifact` — writing a test that can actually fail
- `arm64-container` — `container_verify.py`'s home ground
