# Documentation site

User-facing docs for `bleck`, built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
and published to GitHub Pages.

The `docs/` directory at the repo root is different and stays put: it holds the
living design record — decision log, roadmap, handoff notes — written for
maintainers, not users.

## The two trees have different jobs (D82)

`docs/` records **why, and what is true**: journal tone, decision citations,
confidence markers (✅ 🔶 ⛔), retractions kept in place.

`docs-site/` is an **overview of how to install and use `bleck`**. Present tense,
describing what the tool does. It carries **none** of the above:

- ⛔ Never "verified", "proven", "works today", "confirmed in game".
- ⛔ Never a decision-log citation, a run transcript, or a date.
- ⛔ Never project history — no "used to", no "was wrong", no retractions.

⚠️ That is not licence to overstate. Where a capability is real but thinly
exercised, say so plainly and without the vocabulary above — *"an item's use
script runs only when a player uses that item, which no automated test here can
do"* rather than *"🔶 unproven (D92)"*. A user-visible behaviour change should
update both trees, in each one's own voice.

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
