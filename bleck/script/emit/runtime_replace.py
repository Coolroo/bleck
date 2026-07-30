"""The generated C for `code.replace`: the table, the guard, and the swap.

A swap writes one pointer, so the runtime is much smaller than the patch
runtime. It reuses `bleck_door_field` from `runtime_patch` rather than walking
the init script again — see `PATCH_DOOR_FIELD_NEEDED` for how that is arranged
when a module has replacements but no patches.

Status values mirror `code.patches` so a probe can read both the same way.
"""

from __future__ import annotations

#: The table, the statuses and the apply loop.
#:
#: `bleck_replace_original[]` keeps what the field held, so a mod can restore it
#: and a probe can prove the swap happened rather than inferring it from
#: behaviour.
REPLACE_BLOCK = """
#define BLECK_REPLACE_COUNT {count}

#define BLECK_REPLACE_PENDING 1
#define BLECK_REPLACE_APPLIED 2
#define BLECK_REPLACE_REFUSED 3
#define BLECK_REPLACE_NO_SCRIPT 4

typedef struct {{
    const char *map;
    s32 index;
    s32 fieldOffset;
    u32 expect;
    const void *replacement;
}} BleckReplacement;
{decls}
static const BleckReplacement bleck_replacements[BLECK_REPLACE_COUNT] = {{
{rows}}};

/* Readable from a mod's own C, and from a report block. */
u32 bleck_replace_status[BLECK_REPLACE_COUNT] = {{
{pending}}};

/* What each field held before the swap. 0 where nothing was written. */
u32 bleck_replace_original[BLECK_REPLACE_COUNT] = {{
{zeros}}};

static void bleck_apply_replacements(void)
{{
    u32 i;

    for (i = 0; i < BLECK_REPLACE_COUNT; i++)
    {{
        const BleckReplacement *entry = &bleck_replacements[i];
        u32 **field = bleck_door_field(entry->map, entry->index,
                                       entry->fieldOffset);
        u32 *original;

        if (field == 0)
        {{
            bleck_replace_status[i] = BLECK_REPLACE_NO_SCRIPT;
            continue;
        }}

        /* An unset field is not a script. Swapping into it would leave the
           game calling bytecode nothing else knows about. */
        original = *field;
        if (original == 0)
        {{
            bleck_replace_status[i] = BLECK_REPLACE_NO_SCRIPT;
            continue;
        }}

        /* expect == 0 means the author declared no guard. */
        if (entry->expect != 0 && original[0] != entry->expect)
        {{
            bleck_replace_status[i] = BLECK_REPLACE_REFUSED;
            continue;
        }}

        bleck_replace_original[i] = (u32) original;
        *field = (u32 *) entry->replacement;
        bleck_replace_status[i] = BLECK_REPLACE_APPLIED;
    }}
}}
"""

#: One target map name per replacement, so the table holds pointers to literals.
REPLACE_TARGET = "static const char bleck_replace_map_{index}[] = {name};"

#: Called from `_prolog`, after patches and before the mod's own code.
REPLACE_APPLY = "    bleck_apply_replacements();\n"
