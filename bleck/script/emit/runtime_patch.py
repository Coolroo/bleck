"""The generated C for `code.patches`: the table, the guard, and the resolvers.

Split from `runtime_c` when that module crossed pylint's 1000-line limit. The
seam is a real one rather than a convenience: everything here is reachable only
from a mod that declares `code.patches`, and each selector kind contributes an
independent resolver that `blocks.patch_block` emits only when used.

Every template is a `str.format` pattern, so literal braces are doubled, and the
output must be pure ASCII -- `checks.require_ascii` fails the build otherwise,
which is how a stray emoji in a comment gets caught.
"""

from __future__ import annotations

PATCH_BLOCK = """
/*
    evt script patches.

    A vanilla script's instruction is overwritten in place with a `USER_FUNC`
    calling a function in the mod's own sources. The script's *pointer* is left
    alone -- repointing it is what deadlocked the map loader in D51, and is
    still ruled out. Mutating the bytecode it already refers to creates no new
    `EvtEntry`, so that condition never arises (D87, D89).

    SAME SIZE, ANY SIZE. An instruction is a header declaring M argument words,
    then those M words. The replacement is a USER_FUNC header declaring the same
    M, then the function pointer, then the original's words 2..M carried through
    untouched. M is read out of the header the guard just matched, so the
    replacement cannot be a different length -- which is what keeps every label
    where it was, and `jumptable[]` is cached per `EvtEntry` when a script
    starts.

    At M = 1 that is `USER_FUNC f` with no arguments and the original's single
    argument is lost; at M = 4 -- an item script's opening
    `USER_FUNC g, a, b, c` -- it redirects the call and keeps its arguments.

    The hook reads those carried-through arguments from its EvtEntry:
    `pCurData` (spm/evtmgr.h +0x14) points at the instruction's argument words,
    and `curDataLength` (+0x09) says how many there are.

    THE GUARD IS THE POINT. The word at the offset must be the header the
    manifest named, or nothing is written. A wrong offset then costs a status
    of REFUSED rather than an undiagnosable freeze.

    NOTE: No cache flush. This is bytecode read as *data*, unlike patching PowerPC
    instructions, which needs dcbst/sync/icbi.

    NOTE: Applied once, at load. The mutation therefore lasts the whole session,
    including maps entered later; it is not re-applied per arrival.

    A mod reads the outcome with:

        extern unsigned int bleck_patch_status[];
        extern unsigned int bleck_patch_shared[];
*/

/*
    USER_FUNC is opcode 0x5C, and a header's top half is its argument count --
    `EVT_HELPER_CMD(n, 92)` in spm-headers/mod/evt_cmd.h. The count is taken
    from the matched word, so the replacement is the same size by construction.
*/
#define BLECK_USER_FUNC 0x005Cu
#define BLECK_ARGC_MASK 0xFFFF0000u

#define BLECK_PATCH_MAP 0
#define BLECK_PATCH_ITEM 1
#define BLECK_PATCH_DOOR 2
#define BLECK_PATCH_NPC 3

/* bleck_patch_status[] values. */
#define BLECK_PATCH_PENDING 1
#define BLECK_PATCH_APPLIED 2
#define BLECK_PATCH_REFUSED 3
#define BLECK_PATCH_NO_SCRIPT 4
#define BLECK_PATCH_NOT_FOUND 5

/* bleck_patch_shared[] where nothing counted. */
#define BLECK_PATCH_UNCOUNTED 0xFFFFFFFFu

#define BLECK_PATCH_COUNT {count}

typedef struct
{{
    u32 kind;
    const char *target;

    /* What `target` alone does not say: an item id for BLECK_PATCH_ITEM, a
       door index for BLECK_PATCH_DOOR, -1 where the kind needs neither. */
    s32 index;

    /* Byte offset of the script field within its record. -1 where unused:
       a DoorDesc offset for BLECK_PATCH_DOOR, an NPCTemplate offset for
       BLECK_PATCH_NPC. */
    s32 fieldOffset;

    u32 at;
    u32 expect;
    const void *call;
}} BleckPatch;
{decls}
static const BleckPatch bleck_patches[BLECK_PATCH_COUNT] = {{
{rows}}};

/*
    Not static: a mod's own C reads this to answer "did my patch take" without a
    debugger. Initialised to PENDING rather than 0 so it lands in .data -- the
    loader allocates this module's bss but does not document zeroing it.
*/
u32 bleck_patch_status[BLECK_PATCH_COUNT] = {{
{pending}}};

/*
    How many places point at the script each patch hit, or UNCOUNTED where
    nothing counted it.

    WARNING: item use scripts are shared. 22 distinct scripts across the 33
    table entries (D91), so a value above 1 means this patch changed other items
    too. Counted even when the patch is refused, so the number is readable
    either way.
*/
u32 bleck_patch_shared[BLECK_PATCH_COUNT] = {{
{uncounted}}};

const u32 bleck_patch_count = BLECK_PATCH_COUNT;
{resolvers}
static void bleck_apply_patches(void)
{{
    u32 i;
    u32 *script;
    const BleckPatch *patch;

    for (i = 0; i < BLECK_PATCH_COUNT; i++)
    {{
        patch = &bleck_patches[i];
        script = 0;
{resolve}
        if (script == 0)
        {{
            bleck_patch_status[i] = BLECK_PATCH_NO_SCRIPT;
            continue;
        }}
        if (script[patch->at] != patch->expect)
        {{
            bleck_patch_status[i] = BLECK_PATCH_REFUSED;
            continue;
        }}
        /* Header, then the pointer. Words at + 2 .. at + argc are the
           original's own arguments and are deliberately left alone. */
        script[patch->at] = (patch->expect & BLECK_ARGC_MASK) | BLECK_USER_FUNC;
        script[patch->at + 1] = (u32) patch->call;
        bleck_patch_status[i] = BLECK_PATCH_APPLIED;
    }}
}}
"""

#: Replacing a game function outright with one of the mod's own. ✅ The
#: mechanism is measured (D94): a branch written over `npcDispMain` at
#: `mod_prolog` fired 62,480 times across 90 s of gameplay.

PATCH_MAP_RESOLVER = """
extern void *mapDataPtr(const char *name);

/* spm/map_data.h: MapData.initScript. Populated and stable at _prolog, for maps
   never loaded as much as for loaded ones -- measured, D88. */
#define BLECK_MAP_INIT_SCRIPT 0x18

static u32 *bleck_map_init_script(const char *name)
{
    unsigned char *data = (unsigned char *) mapDataPtr(name);

    if (data == 0)
        return 0;
    return *(u32 **) (data + BLECK_MAP_INIT_SCRIPT);
}
"""

#: The one line `bleck_apply_patches` needs for map patches.
PATCH_MAP_RESOLVE = """        if (patch->kind == BLECK_PATCH_MAP)
            script = bleck_map_init_script(patch->target);
"""

#: Resolving `item:<id>`. ✅ The table's shape and contents are measured (D91);
#: 🔶 nothing has yet observed a patched item script being *entered*.
PATCH_ITEM_RESOLVER = """
/*
    Item use scripts.

    `itemEventDataTable` is 33 entries of {itemId, useScript, useMsgName} living
    in the DOL's own static data, so the pointer is valid at _prolog with no map
    resident -- an easier target than a map's init script (D91).

    RULED OUT: calling `getItemUseEvt`. item_event_data.h says it returns "a
    fallback if the item isn't in there", so an id the table does not hold would
    silently patch a script shared by everything. The table is walked instead,
    and an absent id gets its own status.

    WARNING: entries share scripts -- 22 distinct across 33. Patching one item
    id can change several, so the sharers are counted into
    bleck_patch_shared[].
*/

#define BLECK_ITEM_COUNT 33

typedef struct
{
    s32 itemId;
    u32 *useScript;
    const char *useMsgName;
} BleckItemEventData;

extern BleckItemEventData itemEventDataTable[];

static s32 bleck_item_index(s32 itemId)
{
    s32 i;

    for (i = 0; i < BLECK_ITEM_COUNT; i++)
        if (itemEventDataTable[i].itemId == itemId)
            return i;
    return -1;
}

static u32 bleck_item_sharers(const u32 *script)
{
    s32 i;
    u32 sharers = 0;

    for (i = 0; i < BLECK_ITEM_COUNT; i++)
        if (itemEventDataTable[i].useScript == script)
            sharers++;
    return sharers;
}
"""

#: The item arm of `bleck_apply_patches`. "No such id" is its own status: it is
#: a different mistake from "the guard refused".
PATCH_ITEM_RESOLVE = """        if (patch->kind == BLECK_PATCH_ITEM)
        {
            s32 index = bleck_item_index(patch->index);

            if (index < 0)
            {
                bleck_patch_status[i] = BLECK_PATCH_NOT_FOUND;
                continue;
            }
            script = itemEventDataTable[index].useScript;
            bleck_patch_shared[i] = bleck_item_sharers(script);
        }
"""

#: Resolving `door:<map>:<index>`. ✅ Every constant here is measured, not read
#: off a header — see the block comment for why that distinction cost two
#: decision entries.
PATCH_DOOR_RESOLVER = """
/*
    Door interact scripts.

    A map registers its doors by calling `evt_door_set_door_descs(descs, count)`
    from its own init script, so the descriptor array's address is sitting in
    the bytecode as that call's argument. Reading it needs only what map patches
    already do -- no interception, no trampoline.

    THE ARGUMENT COUNT IS MEASURED, NOT DECLARED. `spm-headers`' `evt_door.h`
    has `EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)`, meaning argc 2,
    directly below a comment reading `(DoorDesc *descs, s32 count)`, meaning
    argc 3. The game uses 3 (D102). Two decision entries concluded doors were
    unreachable because they searched for the macro's number (D93, D94).

    So this matches the header word `0x0003005C` because that word was read out
    of a running game, and `descs` is at +2 and `count` at +3 for the same
    reason. If a future map disagrees, the walk finds nothing and the patch is
    NO_SCRIPT rather than writing somewhere wrong.

    DoorDesc is 0x58 bytes (SIZE_ASSERT in evt_door.h, and consistent with what
    was read back). A selector names which of its three scripts it means;
    `interact` (+0x40) is the default because it is the one that runs when the
    player uses the door. `init` (+0x50) and `move` (+0x54) resolve the same way.

    Resolved once at load, like every other patch. The descriptor arrays were
    readable at `_prolog` for every map tried (D101, D102), which is what makes
    that possible -- but a map whose descriptors are built later would resolve
    to nothing and report NO_SCRIPT.
*/

extern void evt_door_set_door_descs(void);

/* Measured, D102. Header word for USER_FUNC with argc 3. */
#define BLECK_DOOR_SETTER_HEADER 0x0003005Cu

/* DoorDesc is 0x58 bytes and carries three EvtScriptCode * fields:
   interactScript +0x40, initScript +0x50, moveScript +0x54. Which one a patch
   means arrives in `doorOffset`, resolved from the selector at build time. */
#define BLECK_DOORDESC_SIZE 0x58

/* An init script that has not ended by here has desynced; stop rather than
   walk into unrelated memory. D93 nearly recorded a truncated walk as a
   finding, so the bound is generous and failure is silent-and-empty. */
#define BLECK_DOOR_WALK_LIMIT 4096

#define BLECK_EVT_END_SCRIPT 0x0001u
#define BLECK_EVT_MAX_OPCODE 0x0077u
#define BLECK_EVT_MAX_ARGC 16u

static u32 **bleck_door_field(const char *map, s32 index, s32 offset)
{
    u32 *script = bleck_map_init_script(map);
    u32 at = 0;

    if (script == 0 || index < 0 || offset < 0)
        return 0;

    while (at < BLECK_DOOR_WALK_LIMIT)
    {
        u32 header = script[at];
        u32 argc = header >> 16;
        u32 opcode = header & 0xFFFFu;

        if (opcode == BLECK_EVT_END_SCRIPT)
            return 0;
        if (opcode > BLECK_EVT_MAX_OPCODE || argc > BLECK_EVT_MAX_ARGC)
            return 0;

        /* Decoded, not searched: every header declares its argument count, so
           the next one is at a known offset. A scan for the address alone could
           match an argument that happens to hold it. */
        if (header == BLECK_DOOR_SETTER_HEADER
            && script[at + 1] == (u32) &evt_door_set_door_descs)
        {
            unsigned char *descs = (unsigned char *) script[at + 2];
            s32 count = (s32) script[at + 3];

            if (descs == 0 || index >= count)
                return 0;
            return (u32 **) (descs + index * BLECK_DOORDESC_SIZE + offset);
        }
        at += 1 + argc;
    }
    return 0;
}
"""

#: The value at that field. Split from the walk above so `code.replace` can reuse
#: the *address* to store a new pointer, without a second copy of the walk.
PATCH_DOOR_VALUE = """
static u32 *bleck_door_script(const char *map, s32 index, s32 offset)
{
    u32 **field = bleck_door_field(map, index, offset);

    return field == 0 ? 0 : *field;
}
"""

#: The door arm of `bleck_apply_patches`. No shared-script count: unlike item
#: scripts, nothing has measured whether doors share theirs.
PATCH_DOOR_RESOLVE = """        if (patch->kind == BLECK_PATCH_DOOR)
            script = bleck_door_script(patch->target, patch->index,
                                       patch->fieldOffset);
"""

#: Resolving `npcdrv:<template>:<script>`. Everything here is measured -- there
#: is no `NPCTemplate` in any header (D110, D111).
PATCH_NPC_RESOLVER = """
/*
    Enemy behaviour scripts.

    `npcEnemyTemplates` is a static table in DOL data, so a template's scripts
    are readable at load time -- before any NPC spawns, and with no interception.
    D107 concluded otherwise by finding the pointers on a live NPCEntry and
    inferring they existed nowhere else; they are copied there from here.

    LAYOUT IS MEASURED, NOT DECLARED. `NPCTemplate` is in no header. The stride
    came from three markers repeating every 0x68 bytes, and the field offsets
    from locating four addresses that had already been read off a live entry in
    a different run (D111). Entry n is template id n, which `bleck setup show`
    already prints for every enemy a map places.

    WARNING: TEMPLATES SHARE SCRIPTS. 0x80439F10 sits at +0x4C in entries 0, 1
    and 2, so patching one template's death script changes every template
    pointing at it -- the same hazard as item use scripts, where 33 entries hold
    22 distinct scripts. `bleck_patch_shared[]` reports how many, counted here
    rather than left for the author to discover in game.
*/

extern u32 npcEnemyTemplates[];

/* Measured, D111. */
#define BLECK_NPC_TEMPLATE_SIZE 0x68

/*
    How far the count is trusted. The table's end was never measured, so this is
    a bound on the SEARCH, not a claim about the game: a template beyond it
    reports NO_SCRIPT rather than reading whatever follows the table.
*/
#define BLECK_NPC_MAX_TEMPLATES 512

static u32 *bleck_npc_script(s32 template, s32 offset)
{
    unsigned char *base = (unsigned char *) npcEnemyTemplates;

    if (template < 0 || template >= BLECK_NPC_MAX_TEMPLATES || offset < 0)
        return 0;
    return *(u32 **) (base + template * BLECK_NPC_TEMPLATE_SIZE + offset);
}

/* Templates pointing at the same script, so an author is told how many enemies
   a patch actually changes. */
static u32 bleck_npc_sharers(const u32 *script, s32 offset)
{
    unsigned char *base = (unsigned char *) npcEnemyTemplates;
    u32 count = 0;
    s32 i;

    if (script == 0)
        return 0;
    for (i = 0; i < BLECK_NPC_MAX_TEMPLATES; i++)
        if (*(u32 **) (base + i * BLECK_NPC_TEMPLATE_SIZE + offset) == script)
            count += 1;
    return count;
}
"""

#: The npcdrv arm of `bleck_apply_patches`.
PATCH_NPC_RESOLVE = """        if (patch->kind == BLECK_PATCH_NPC)
        {
            script = bleck_npc_script(patch->index, patch->fieldOffset);
            bleck_patch_shared[i] = bleck_npc_sharers(script, patch->fieldOffset);
        }
"""

#: One patched script's name, held out of the table so it is a real string.
PATCH_TARGET = "static const char bleck_patch_target_{index}[] = {name};"

#: The mod's own hook, declared for its address only -- exactly as game
#: functions called by USER_FUNC are declared.
PATCH_CALL = "extern void {name}(void);"

#: A banner above each mod's own section of the merged module.
