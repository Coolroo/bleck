# Documentation site

User-facing docs for `bleck`, built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
and published to GitHub Pages.

The `docs/` directory at the repo root is different and stays put: it holds the
living design record — decision log, roadmap, handoff notes — written for
maintainers, not users.

## Working on it

```bash
uv sync --extra docs
uv run mkdocs serve      # http://127.0.0.1:8000
```

Configuration lives in `mkdocs.yml` at the repo root, including the navigation.

> ⚠️ `mkdocs.yml` sets `docs_dir: docs-site` deliberately. MkDocs defaults to
> `docs/`, which here is the internal design record — publishing it would be a
> mistake nobody would notice until it was indexed.

Before pushing:

```bash
uv run mkdocs build --strict
```

`--strict` turns broken internal links into build failures. CI runs the same
command, so a bad link fails the pull request rather than shipping a 404.
