# Plan — merging several mods into one REL

Status: **proposed**, not built. Written 2026-07-27.

⬅️ **This is the next piece of work.** `plan-config.md` is done (D77), so
this is what follows. Step 1 -- parameterising the emitter prefix -- is
landable on its own and invisible to existing behaviour.

One thing changed since this was written: `emit.MAX_COMBOS` already refuses
more than 32 button combinations with a clear error. **Map hooks still do
not**, and that is the latent `1 << i` overflow described below.

Today `bleck` refuses a chain containing more than one code mod
(`bleck/mods/code.py:131`). This plan removes that limit.

---

## The insight that makes it tractable

**The Gecko loader opens exactly one `/mod/mod.rel`. It does not care how many
mods went into it.**

D39 recorded multi-mod loading as an unsolved problem in this scene and noted
that `chainrel` is a three-commit stub with its loader body wrapped in `#if 0`.
That is true — *of loading several RELs at runtime*. Merging at **compile time**
sidesteps the whole thing: one REL is produced, the loader's constraint is
satisfied exactly as it is today, and no runtime chaining exists to go wrong.

This is why the problem is worth attacking now: the hard part everyone else hit
is not on this path.

---

## What actually collides

Every generated identifier is global under one prefix, `_PREFIX = "bleck_"`
(`emit.py:60`):

| Identifier | Collides because |
|---|---|
| `bleck_script_<name>` | two mods may each declare `main` |
| `bleck_string_<n>` | indices are per-program |
| `bleck_map_name_<i>`, map tables | per-program |
| `mod_prolog` | each mod's C may define it |
| `bleck_boot_*`, `bleck_banner_*` | one-per-**disc** concepts, not per-mod |

## Design: compile separately, emit with a per-mod prefix

Compile each mod's program on its own, so names inside a mod resolve exactly as
they do today, then apply a per-mod prefix when emitting C identifiers. **No
mod's `.evt` source changes** — only generated symbols.

- `_PREFIX` becomes a parameter: `bleck_<slug>_`, slug being the mod name
  sanitised to `[a-z0-9_]`.
- Two mods sanitising to the same slug is an error naming both.
- `GeneratedSource` carries its prefix so the shared footer can reference the
  right symbols.

This is the user's "hash their names" idea with a readable prefix instead of a
hash, so a build log and a disassembly still say which mod a script came from.

## Per-disc vs per-mod

The merged module is *N per-mod blocks plus one shared runtime block*. These are
one-per-disc and must not be emitted N times:

| Concern | Resolution |
|---|---|
| Sequence hook install | Once, in `_prolog`. Already a single loop. |
| Entry scripts | Start **every** mod's `main`, each with its own re-arm flag |
| Map hooks | **Union** the tables across mods, in chain order |
| Banner | Chain target's name, `+N` when others are present |
| Boot map | One per disc; CLI beats manifest, last manifest wins |

## ⚠️ The 32-hook cap becomes reachable

`bleck_map_pending` is a `u32` bitmask, one bit per hook (`emit.py:149`). With
one mod, 32 map hooks is unreachable in practice. **Merging makes it plausible**,
and today exceeding it would silently corrupt neighbouring bits rather than
fail — a shifted `1 << i` past 31 is undefined behaviour.

This must be fixed as part of the work: either widen to an array of words, or
refuse loudly at build time. **Refuse loudly first** — it is one comparison, and
nobody has yet wanted even ten.

## `mod_prolog` needs a decision

Each mod's own C may define it (`emit.py:MOD_HOOK`). Merged, two strong
definitions collide at link time with a message about a symbol nobody wrote by
hand.

Rejected: rewriting each mod's C to rename it (source rewriting), or renaming
the convention (breaks existing mods).

✅ **Done: detect and refuse, naming both mods.**

```
2 mods define `mod_prolog` (hard-mode, extra-enemies), and only one can.
  It is the hand-off `bleck` calls when the module loads, so a merged disc
  has exactly one.
  Move the extra work into a sequence hook, or combine those mods.
```

⚠️ Comments are stripped before looking, and a *declaration* does not count.
`docs-site` tells authors to "define `mod_prolog`" and several existing mods
quote that line above the function, so matching the prose would report a
collision between a mod that defines it and one that merely mentions it.

## Native sources

`code.sources` from several mods compile into the merged link. Symbol
collisions there are ordinary C collisions and the linker's message is decent.
Acceptable for v1; no special handling.

## Ordering

Chain order — dependencies first, target last, matching how overlays already
resolve. Deterministic, and a later mod's hooks run later.

## What gets removed

- the `len(coded) > 1` error in `code.py:131`
- the implicit exclusivity of `files/mod/mod.rel` in `conflicts.py`

## Risks

- **The 32-hook cap**, above. Must be handled, not deferred.
- **REL size.** The loader allocates from `HEAP_MAIN`. D39's gotcha about
  allocating from the tail concerns a *second* REL, not a larger one, so this
  is probably fine — but build output should report the size so growth is
  visible rather than discovered.
- **Debuggability.** One `mod.c` from several mods. Keep per-mod sections
  clearly delimited by comment banners, and move intermediates from
  `<build>/.code/<mod>/` to `<build>/.code/merged/` with a per-mod header.

## Testing

| What | How |
|---|---|
| slug sanitisation, collisions | unit |
| two mods both declaring `main` produce distinct symbols | unit, generator |
| map hooks union in chain order | unit |
| more than 32 hooks refused | unit |
| **two mods' scripts both actually run** | **in-game** — two probe slots, one per mod |
| **map hooks from different mods both fire** | **in-game** |

The last two are the ones that matter and neither can be faked. D51 installed
perfectly by every mechanical check and still froze.

## Rollout

1. ✅ **Parameterise `_PREFIX`.** Done. `Scaffolding.prefix` defaults to
   `bleck_`; `prefix_for("hard-mode")` gives `bleck_hard_mode_`. Single-mod
   output verified byte-identical on four representative programs, and a
   real mod still builds to the same size. `tests/test_prefix.py`.
2. ✅ **Compile per mod, merge into one translation unit.** Done --
   `emit.generate_merged` and `code.build_merged`. Two mods both declaring
   `script main` compile to one 1716-byte module through devkitPPC.
3. ✅ **Shared runtime block.** Done -- one `_prolog`, one set of sequence
   hooks, and `bleck_entries[]` starting every mod's `main`.
4. ✅ **Lifted the >1 error**; banner, boot map, map hooks and combos are
   unioned. Two boot maps are refused naming both -- a disc starts in one
   place.
5. ✅ **The 32-hook cap.** Done -- `MAX_MAP_HOOKS` refuses the 33rd with an
   error saying *why*, so nobody just raises the number.
6. ⬅️ **Verify in game with two real mods.** NOT DONE, and the only step
   that matters now. `mods/merge-a` and `mods/merge-b` both loop and write
   different `gw` slots, so a run can tell "both ran" from "one ran".
   No unit test can show that, and D51 installed perfectly by every
   mechanical check and still froze.
7. ✅ `docs-site` + decision-log entries (D77, D78).

Step 1 is worth landing on its own: it is invisible, it is covered by existing
tests, and it is the only part that touches every emitted identifier.
