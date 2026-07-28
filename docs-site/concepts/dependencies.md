---
title: Dependencies and conflicts
description: Layering mods, and what happens when they collide
---

A mod can depend on other mods. Layers apply in order, each overriding what came
before:

```
base game  ←  dependencies (transitively)  ←  this mod
```

```json
{
  "name": "hard-mode-plus",
  "dependencies": [
    { "name": "hard-mode", "version": ">=2.0.0" },
    { "name": "shared-textures" }
  ]
}
```

## Resolution

Dependencies form a graph, and the same mod can be reached by several paths.
`bleck` flattens it into one order where each mod appears **exactly once**:

> Depth-first post-order, in declaration order, keeping the first occurrence.

Post-order means a mod applies only *after* everything it depends on, so later
layers can override earlier ones.

??? note "Worked example: the diamond"

    `M` depends on `[A, B]`; both `A` and `B` depend on `C`.

    ```
        M
       / \
      A   B
       \ /
        C
    ```

    Resolves to **`C, A, B, M`** — `C` once, before both dependents.

See the resolved order any time:

```bash
bleck mod chain hard-mode-plus
```

```
1. shared-textures  0.3.0   (required by hard-mode-plus)
2. hard-mode        2.1.0   (required by hard-mode-plus)
3. hard-mode-plus   0.1.0   (target)
```

Cycles, missing dependencies and version mismatches are errors that name who
required what.

## Conflicts

Conflicts arise only between mods where **neither depends on the other**.

!!! info

    If B depends on A, B overriding A's files is not a conflict — that is what
    depending on something means.

Checks run finest-granularity-first, so an apparent collision is often not one.

1.  **Archive members**

    Two mods editing `title.bin.uk` only conflict if they edit the **same
    member**. Different textures merge cleanly.

1.  **Three-way merge**

    Same file, two independent mods: `bleck` merges using the base game as the
    common ancestor — which always exists, because the base is immutable.
    Non-overlapping changes combine; overlapping ones conflict.

1.  **Exclusive claims**

    A mod can claim a path outright. Any other mod touching it is an error, no
    merge attempted.

    ```json
    "exclusive": ["files/rel/rel.bin"]
    ```
{ .steps }


## Binary merging is opt-in

!!! warning

    Two mods can edit **different bytes** of the same binary file and still produce
    something broken — two mods each appending to a table merge cleanly byte-wise
    and corrupt the result. Byte ranges cannot tell that apart from a safe edit.

    So independent edits to the same binary file are reported as a conflict by
    default. `--merge-binary` opts in.

Check without building anything:

```bash
bleck mod check my-mod
```
