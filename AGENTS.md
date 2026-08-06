# Codex, in this repository

Codex reads this file automatically. It is a **router**, not a second rulebook.

## RULE: read `CLAUDE.md` first, and treat it as the rules

`CLAUDE.md` is tracked and is the single statement of what is enforced here —
the orientation table, the licence constraint, the four pylint rules, the
output-capture rule, the living-docs rule, and the CLI's real command list.

⛔ **This file does not restate any of it.** Two copies of a rule drift, and one
of them then ships a claim the other already withdrew — which is the failure
this repository logs more than any other (D217/D252, D280/D282, D283/D285).
If a rule belongs to the project, it goes in `CLAUDE.md` and this file links to
it.

## ⚠️ The one structural difference: there is no skill tool here

Claude Code loads a method on demand through a tool call. Codex has no
equivalent, so **the methods are files you must open yourself**. They are plain
Markdown with a YAML header, and nothing about them is Claude-specific.

**Open the matching file before you start that kind of work**, not after it goes
wrong. Each one exists because the same mistake was made at least twice.

### Methods — how to reach a true answer

| read | before you |
|---|---|
| [`decode-by-disassembly`](.claude/skills/decode-by-disassembly/SKILL.md) | attack a binary format, struct field or file layout. Disassemble the code that reads it instead of pattern-matching the bytes. `dolscan.py`, the ⛔ `xref`-cannot-find-callers trap, `r2`/`r13` loads |
| [`control-every-statistic`](.claude/skills/control-every-statistic/SKILL.md) | report or believe any percentage, score or "N of M agree". Also: produce a positive result before you trust a negative one |
| [`verify-the-emitted-artifact`](.claude/skills/verify-the-emitted-artifact/SKILL.md) | write or trust a test over anything this project exports. An export with zero materials passed 1,508 tests |
| [`render-to-look`](.claude/skills/render-to-look/SKILL.md) | need eyes on a model, effect, texture or animation with no screen. `dimentio shot` and `dimentio reel`, and their blind spots |
| [`ground-truth-from-reference-rips`](.claude/skills/ground-truth-from-reference-rips/SKILL.md) | need an external answer key for a decoded asset. ⚠️ `work/reference/` is git-ignored and exists only where it was supplied |
| [`slow-command-discipline`](.claude/skills/slow-command-discipline/SKILL.md) | run anything that costs minutes. The price list, and where each transcript already lives |

### Tools and workflows — which command, and what it lies about

| read | before you |
|---|---|
| [`bleck-cli-workflows`](.claude/skills/bleck-cli-workflows/SKILL.md) | run the CLI at all. `--mods-dir example-mods`, `build` vs `mod build`, `--align-files`, and one advertised command that does not exist |
| [`ingame-testing`](.claude/skills/ingame-testing/SKILL.md) | confirm or doubt anything inside the running game. `scripts/ingame.py`, the probe block, and the ways a run lies |
| [`hunting-a-hang`](.claude/skills/hunting-a-hang/SKILL.md) | bisect a freeze. Hook `__assert2` first — it names its own cause in one run |
| [`reading-the-game-live`](.claude/skills/reading-the-game-live/SKILL.md) | pull a value out of a running function. `code.hooks`, the detour, and the six things a trace cannot see |
| [`reading-undecoded-data`](.claude/skills/reading-undecoded-data/SKILL.md) | open an unknown binary on the disc, or one of the game's own `evt` scripts |
| [`catalog-dumps`](.claude/skills/catalog-dumps/SKILL.md) | regenerate a committed catalog, or wonder where a name in `bleck`'s output came from |
| [`linting-and-ci`](.claude/skills/linting-and-ci/SKILL.md) | finish any Python change, or when `C9001`/`C9002`/`C9003` fires |
| [`arm64-container`](.claude/skills/arm64-container/SKILL.md) | work on Apple Silicon, or when a devkitPro package looks unavailable for arm64 |

⚠️ **These are guidance, not enforcement.** `scripts/lint.py` is where a rule
becomes a rule, and it is what CI runs.

## Where to start on the work itself

`CLAUDE.md` carries the full map. The short version:

| | |
|---|---|
| [`docs/handoff.md`](docs/handoff.md) | **start here.** What works, what a *person* has confirmed versus what only tests believe, the open threads, the standing traps |
| [`docs/decision-log.md`](docs/decision-log.md) | why every choice was made. Chronological, append-only. Read it before you propose an approach — it records paths already ruled out |
| [`docs/roadmap.md`](docs/roadmap.md) | what to build next, and what blocks what |
| [`docs/coding-standards.md`](docs/coding-standards.md) | the enforced rules, in full |

## ⚠️ Keep this file and `CLAUDE.md` in step

They are read by different agents and neither sees the other's. When the skill
set changes, or a doc in the table above is renamed, **both files change in the
same commit.**

The division that keeps them from drifting:

- **`CLAUDE.md`** — every rule, every constraint, the command list, the working
  notes. It is the source.
- **`AGENTS.md`** — routing only: read `CLAUDE.md`, and here is the method index
  with the reason to open each one.

⛔ **Do not move a rule into this file.** If you find one here that is not in
`CLAUDE.md`, that is the bug.
