# Plan — a `bleck` config file, and named button combos

Status: ✅ **BUILT** and confirmed in game (D77). Written 2026-07-27.

What shipped, and where it differs from this plan:

- `bleck/common/config.py` reads `bleck.yml`; `bleck.yml.example` documents it
- `code.combos` binds a combination name to a script, mirroring `code.maps`
- PyYAML was taken as the first runtime dependency, as recommended below
- 🔶 The built-in `{"goto": "map"}` shorthand was **not** built. A script
  calling `evt_seq_mapchange` covers it, and nothing has wanted the sugar yet
- ✅ The masks are no longer hypotheses for `a`, `b`, `1`, `2` (D68). The rest
  of the table is still unverified
- ⚠️ The plan said to verify the masks *before* shipping. That was done, and
  it was right: the published values turned out correct, but the same session
  produced D65 and D76 by trusting inferences of exactly that shape

The first user of this file is button combos, but the file is the point: a
place for values that are chosen once and injected into every build, so nothing
is hardcoded in `emit.py` and nothing has to be repeated per mod.

---

## Why combos are possible at all

⚠️ **D48 says input cannot be injected. That is about faking input into Dolphin
from outside, for unattended runs, and it does not apply here.** The game reads
its own controller every frame, and a mod can read the same state. These were
conflated for several sessions and it cost the whole "button-triggered" design
space.

What makes it work, all verified against `work/upstream/spm-headers`:

| Piece | Where | Value |
|---|---|---|
| `wpadGetWork()` | `spm.eu0.lst` | `0x8023697c` — links today |
| `WpadWork.statuses[4][16]` | `spm/wpadmgr.h` | offset `0x006C`; major index controller, minor index age, latest is 0 |
| `KPADStatus` | `wii/kpad.h` | `0x84` bytes |
| `KPADStatus.buttonsHeld` | `wii/kpad.h` | offset `0x0`; `buttonsPressed` `0x4`, `buttonsReleased` `0x8` |

So `wpadGetWork()->statuses[0][0].buttonsHeld` is a `u32` of live button state,
reachable from the sequence hook that already runs every frame.

### 🔶 The one unknown: the masks

**spm-headers defines no button constants.** The Revolution SDK values are
widely published, but D65 is a fresh reminder of what inference costs — a
verified signature and a well-understood subsystem still hung the game.

**Settle it empirically before shipping.** One run: a diagnostic writes
`buttonsHeld` into the probe block, a human presses each button in turn, the rig
reads the bits back. That is a question the rig genuinely can answer, unlike
D65's.

Nunchuk buttons (`c`, `z`) live in `KPADStatus.extension`, a different field —
out of scope for v1.

---

## The file

`bleck.yml`, found by walking up from the working directory, exactly as
`env.py` already does for `.env` (`bleck/common/env.py:67-75`).

```yaml
version: 1

combos:
  start_map: [1, 2]
  reload:    [minus, plus]

constants:
  test_map: he1_01
```

### ⚠️ Decision needed: the format costs a dependency

`pyproject.toml` says, deliberately:

```toml
dependencies = []
# bleck itself has no runtime dependencies. Keep it that way where practical —
# it is a toolkit people install to use, not a library.
```

PyYAML would be the first. Options considered:

| Option | Verdict |
|---|---|
| **PyYAML** | What was asked for. Ubiquitous, comments, readable. Breaks the zero-dep line. |
| `bleck.json` | Zero deps, consistent with `mod.json` — but no comments, and a config file people hand-edit wants comments. |
| TOML via `tomllib` | Stdlib, but **3.11+ only**; `requires-python = ">=3.10"`. Would force a floor bump. |
| Hand-rolled YAML subset | ⛔ Rejected. `.env` was hand-parsed safely because its grammar is one line long. YAML is not that. |

**Recommendation: PyYAML.** The zero-dep line has already moved — `pyelf2rel`
is listed as "becomes a runtime dependency when code mods land", and code mods
have landed. Spending one more well-known dependency on a file the user asked
for is a better trade than a worse format or a Python floor bump.

---

## How a mod uses a combo

Mirror `code.maps`, which is the proven shape — combo name to script name:

```json
"code": {
  "combos": { "start_map": "warp_home" }
}
```

The script must exist in the mod's source, validated with the same
list-and-suggest error as `_check_map_hooks` (`emit.py:611`).

For the common case, a built-in so no script is needed:

```json
"combos": { "start_map": { "goto": "he1_01" } }
```

which generates the same `evt_seq_mapchange` script `code.boot` already
generates.

### Precedence

`--map`-style CLI flag → `mod.json` → `bleck.yml`. Documented, and tested.

---

## Generated C

A `_COMBO_BLOCK` shaped like `_MAP_BLOCK`: a mask table, a script table, and a
watcher called from the existing per-frame sequence hook.

```c
extern void *wpadGetWork(void);

#define BLECK_WPAD_STATUSES 0x6C
#define BLECK_KPAD_STRIDE   0x84

static u32 bleck_buttons_held(void)
{
    u8 *work = (u8 *) wpadGetWork();
    if (work == 0)
        return 0;
    return *(u32 *) (work + BLECK_WPAD_STATUSES);   /* [0][0].buttonsHeld */
}
```

Design points, each with a reason:

- **Edge-triggered.** Fire when the combo becomes fully held, not while held,
  or it repeats 60 times a second.
- **`SEQ_GAME` only for v1.** `evtEntry` needs evt alive. Watching during
  `SEQ_LOGO` is tempting and is exactly what hung in D65 — do not, until the
  hang is understood.
- **Trigger the proven path.** The script runs via `evtEntry` and calls
  `evt_seq_mapchange`, unchanged from D64. Only the trigger is new. Calling
  `seqSetSeq` directly is not yet known to be safe.
- **`static u32 bleck_combo_was_down = 1;`** — non-zero so it lands in `.data`;
  the loader's bss zeroing is undocumented.
- **Require two or more buttons** unless overridden, so a combo cannot fire
  during ordinary play.

---

## Code shape

`bleck/common/config.py`, mirroring `env.py`. Frozen dataclasses throughout —
`Config`, `Combo`, `Constant` — because C9001 forbids returning `dict`.

## Failure modes worth designing for

- Combo named in `mod.json` but not in `bleck.yml` → error naming the file,
  listing what is defined, with a did-you-mean.
- Unknown button name → error listing valid names.
- No config file at all → combos simply unavailable; a mod referencing one says
  so clearly rather than compiling to nothing.

## Rollout

1. `config.py` + discovery + precedence, with tests. No game needed.
2. Button-name table, every entry marked 🔶.
3. **Verify the masks in-game.** One run, one human.
4. `_COMBO_BLOCK`, `code.combos`, manifest parsing, generator tests.
5. Verify firing in-game.
6. `docs-site` reference + guide; decision-log entry.

Steps 1-2 and 4 are testable without the game. Steps 3 and 5 need a person
holding a controller — which is the entire point of the feature, so there is no
way around it and no reason to want one.
