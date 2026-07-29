---
title: evt_door_set_door_descs takes argc 3, not 2
description: spm-headers declares the wrong parameter count for the door descriptor setter; the game disagrees with the macro and agrees with the comment above it
---

# `evt_door_set_door_descs` takes argc 3 — the header says otherwise

**PAL rev 0 (`R8PP01`, "eu0"). `evt_door_set_door_descs` is `0x800E2610`.**

✅ In the game's own bytecode, every call to `evt_door_set_door_descs` has the
`USER_FUNC` header word **`0x0003005C`** — argc 3: the function pointer plus
two arguments, `(DoorDesc *descs, s32 count)`.

⛔ [`spm-headers`](https://github.com/SeekyCt/spm-headers)'
`include/spm/evt_door.h` declares one argument, which produces argc 2:

```c
// evt_door_set_door_descs(DoorDesc * descs, s32 count)
EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)     // -> argc 2
```

**The comment is right and the macro is wrong.** The two sibling setters in the
same file, with identically shaped comments, are declared `2`:

```c
// evt_door_set_dokan_descs(DokanDesc * descs, s32 count)
EVT_DECLARE_USER_FUNC(evt_door_set_dokan_descs, 2)

// evt_door_set_map_door_descs(MapDoorDesc * descs, s32 count)
EVT_DECLARE_USER_FUNC(evt_door_set_map_door_descs, 2)
```

## The evidence

A module walked every loaded map init script looking for `USER_FUNC` call sites
by **function pointer**, at whatever argument count the script declared, and
reported the header word it found. One 75-second run:

| call site | header word | map | arg0 | arg1 |
|---|---|---|---|---|
| `evt_door_set_door_descs` | **`0x0003005C`** | `he1_01` | `0x80D2FBB0` | **1** |
| `evt_door_set_map_door_descs` | **`0x0003005C`** | `he1_01` | `0x80D2F940` | **3** |
| `evt_door_set_dokan_descs` | **`0x0003005C`** | `mac_01` | — | — |
| control: `evt_hitobj_attr_onoff` | `0x0005005C` | — | — | 8 hits |

The control's **header word** is what validates the instrument, not its hit
count: that call had been measured at argc 5 in an earlier, unrelated run, so
`0x0005005C` was known in advance. Reading it back proves headers were being
decoded from the right offset before any door number was believed.

The arguments then check out independently: `0x80D2F940` treated as a
`MapDoorDesc *` yields `destMapName` = **`he1_02`** and `destDoorName` =
**`doa1_l`** as readable strings. A wrong pointer does not spell a map name.

*(Sources: bleck decision log D101, D102.)*

## Why it matters, concretely

With `spm-headers`' `mod/evt_cmd.h` macros, `USER_FUNC` static-asserts the
declared parameter count:

```c
#define USER_FUNC(function, ...) \
    ( \
        expression_assert< \
            function##_parameter_count == -1 \
            || function##_parameter_count == EVT_HELPER_NUM_ARGS(__VA_ARGS__) \
        >(), \
        EVT_HELPER_CMD(1 + EVT_HELPER_NUM_ARGS(__VA_ARGS__), 92) \
    ), \
    reinterpret_cast<s32>(function), \
    ##__VA_ARGS__ ,
```

So writing the correct call in a custom script —

```c
USER_FUNC(evt_door_set_door_descs, PTR(descs), 1)
```

— **fails to compile**, and the only form the header accepts emits an
instruction the game does not use.

It also breaks anyone searching bytecode for the call: a search constrained to
argc 2 finds zero hits in a game full of them. That is exactly what happened
here, and it cost two decision entries and a wrong published-in-our-own-repo
conclusion ("door descriptors are not registered from map init scripts") before
it was caught.

## The fix

One character, in `include/spm/evt_door.h`:

```diff
 // evt_door_set_door_descs(DoorDesc * descs, s32 count)
-EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)
+EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 2)
```

## The general caution

⚠️ `spm-headers` is hand-maintained against a decomp that is ~2.34% matched. It
is a **reference, not ground truth**. This is the first case we have recorded of
one of its declarations being simply incorrect — but where a header's claim is
load-bearing (an argc, an offset, a struct size), reading it is a hypothesis 🔶
until it is measured. Everything else in this section that came from a header is
marked as such.

## See also

- [How an evt instruction is encoded](evt-instruction-format.md) — what `argc`
  counts and why `0x0003005C` means three words follow
- [Door descriptors](door-descriptors.md) — what the setter registers, and what
  the descriptors point at
