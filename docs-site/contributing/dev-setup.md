---
title: Development setup
description: Working on bleck itself
---

## Set up

  === "Linux"

      ```bash
      curl -LsSf https://astral.sh/uv/install.sh | sh
      sudo apt install -y wit dolphin-emu

      git clone git@github.com:Coolroo/bleck.git
      cd bleck
      uv sync --extra dev
      ```
  === "macOS"

      ```bash
      brew install uv
      brew install --cask dolphin

      git clone git@github.com:Coolroo/bleck.git
      cd bleck
      uv sync --extra dev
      ```
  === "Windows"

      ```powershell
      winget install --id=astral-sh.uv -e

      git clone git@github.com:Coolroo/bleck.git
      cd bleck
      uv sync --extra dev
      ```

Dependency versions are pinned in `uv.lock`, which is **committed** — everyone
resolves the same versions.

## The loop

```bash
uv run pytest                          # the fast test suite
uv run python scripts/lint.py --fix    # ruff + pylint
```

  === "Any platform"

      ```bash
      uv run python scripts/lint.py --fix
      ```
  === "Linux / macOS"

      ```bash
      ./scripts/lint.sh --fix
      ```
  === "Windows"

      ```powershell
      powershell scripts\lint.ps1 -fix
      ```

The shell scripts are thin wrappers; the logic lives in `scripts/lint.py` so no
shell is required.

## Tests

The suite is fast by design and runs without game data — tests needing a disc
skip cleanly, so a fresh clone is green.

```bash
uv run pytest              # fast tests only
uv run pytest -m slow      # opt into the slow ones
```

!!! warning

    The LZ77 compressor runs at roughly **12 s/MB**. Tests only compress small
    synthetic inputs; anything touching real game data is marked `slow` and
    deselected by default. Keep it that way.

## Project layout

```
bleck/
  formats/      lz77, u8, detect          file formats
  common/       errors, fsio, env, manifest
  backends/     disc                      wraps wit / dolphin-tool
                emulator                  wraps the Dolphin emulator
  platforms/    linux, macos, windows     per-OS differences as data
  mods/         manifest, registry, resolver, overlay, conflicts, builder
  cli/
    app.py                                parser assembly and dispatch
    commands/   inspect, archive, mods, disc, emulate, stream
lint_plugins/   custom pylint rules
docs/           living design docs and decision log
docs-site/      this documentation
```

Adding a CLI command means adding a module under `cli/commands/` and listing it
in `MODULES` — nothing in the CLI core changes.

## Working on these docs

The site is [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/),
published to GitHub Pages. It needs **no Node toolchain** — it installs with the
same `uv` you already have:

```bash
uv sync --extra docs
uv run mkdocs serve      # preview on http://127.0.0.1:8000
```

Configuration and navigation live in `mkdocs.yml` at the repository root.

Before committing a docs change:

```bash
uv run mkdocs build --strict
```

!!! note

    `--strict` turns broken internal links into a build failure. CI runs the
    same command on every pull request, so a bad link fails review rather than
    reaching the published site.

!!! warning

    `mkdocs.yml` sets `docs_dir: docs-site` deliberately. MkDocs defaults to
    `docs/`, which in this repository is the internal design record — decision
    log, roadmap, handoff notes. Publishing that would be a mistake nobody
    would notice until it was indexed.

## Where the reasoning lives

<div class="grid cards" markdown>

-   **docs/decision-log.md**

    Why choices were made, chronologically, including rejected alternatives and
    corrections. Read it before proposing an approach.

-   **docs/roadmap.md**

    What to build next and what blocks what.

-   **docs/disc-layout.md**

    Observed facts about the game disc.

-   **docs/coding-standards.md**

    The enforced rules, in detail.

</div>


!!! note

    Those docs are **living** — anyone doing substantive work is expected to update
    them as they go, not afterwards. Reasoning that exists only in a conversation is
    lost.
