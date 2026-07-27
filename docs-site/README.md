# Documentation site

Mintlify docs for `bleck`. Source of truth for **how to use** the toolkit.

The `docs/` directory at the repo root is different and stays put: it holds the
living design record — decision log, disc findings, roadmap — written for
maintainers rather than users.

| | Audience | Contents |
|---|---|---|
| `docs-site/` | Users | Install, usage, guides, reference |
| `docs/` | Maintainers | Why things are the way they are |

## Preview locally

Uses [bun](https://bun.sh/).

```bash
cd docs-site
bun install
bun run dev       # http://localhost:3000
bun run check     # broken-link check, no server
```

`bun.lock` is committed so everyone gets the same Mintlify version.

## Structure

```
docs.json          navigation and theme
index.mdx          landing
quickstart.mdx     clone -> modified disc
install/           per-OS setup
concepts/          formats, mods, dependencies, disc formats
guides/            first mod, testing, code mods
reference/         CLI, mod.json, environment
contributing/      dev setup, coding standards
```

## Keeping it honest

Pages carry explicit status where something is unverified — macOS is implemented
but never run there, and code mods are not integrated. Windows and Linux are both
verified end to end, including booting a built disc. **Do not quietly drop those
callouts**; update them when the status actually changes.
