/*
    Which door is which, by name.

    "Door 0" is a position in the array a map registers with
    `evt_door_set_door_descs(descs, count)` -- registration order, not an id and
    not anything visible in game (D103). Asking a person to "use the first door"
    is therefore unanswerable without this.

    `DoorDesc` carries names the developers used (`evt_door.h`, MIT):

        +0x0C  name
        +0x2C  mapGrpName     the model group in the map
        +0x30  hitGrpName1    the collision the player touches

    This reports all three for every door on the map, plus each one's
    `interactScript` pointer so the swapped door is identifiable in the same
    dump.

    ⚠️ Read only. This changes nothing -- it is meant to run alongside the swap
    so one boot answers both "which door did we take" and "is the swap live".

    Report block at NAMES, big-endian u32:

      +0x000 (  0)  magic 'DOOR'
      +0x004 (  1)  door count, -1 if the descriptor array was not found
      +0x008 (  2)  the descriptor array's address
      +0x00C (  3)  spare
      then 20 words per door, up to DOOR_MAX:
        +0   interactScript pointer
        +1 .. +6   name, 24 bytes
        +7 .. +12  mapGrpName, 24 bytes
        +13 .. +18 hitGrpName1, 24 bytes
        +19  spare

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

/* Its own block, well clear of the swap probe at 0x80005000. */
#define NAMES 0x80005400
#define NAMES_MAGIC 0x444F4F52U /* 'DOOR' */

#define DOOR_MAX 8
#define PER_DOOR 20
#define TEXT_WORDS 6
#define TEXT_BYTES (TEXT_WORDS * 4)

#define DOORDESC_SIZE 0x58
#define DOOR_NAME 0x0C
#define DOOR_MAPGRP 0x2C
#define DOOR_HITGRP 0x30
#define DOOR_INTERACT 0x40

#define MAP_INIT_SCRIPT 0x18
#define DOOR_SETTER_HEADER 0x0003005Cu
#define EVT_USER_FUNC 0x005Cu
#define EVT_END_SCRIPT 0x0001u
#define EVT_MAX_OPCODE 0x0077u
#define EVT_MAX_ARGC 16u
#define DOOR_WALK_LIMIT 4096

extern void *mapDataPtr(const char *name);
extern void evt_door_set_door_descs(void);
extern void evt_door_set_map_door_descs(void);

static volatile u32 *const names = (volatile u32 *) NAMES;

static void copy_text(u32 slot, const char *text)
{
    volatile unsigned char *out = (volatile unsigned char *) (names + slot);
    u32 i;

    for (i = 0; i < TEXT_BYTES; i++)
        out[i] = 0;
    if (text == 0)
        return;
    for (i = 0; i < TEXT_BYTES - 1 && text[i] != 0; i++)
        out[i] = (unsigned char) text[i];
}

/*
    The array a given setter was called with, read out of the init script's
    bytecode -- the address is sitting there as the call's argument.

    ⚠️ Matched on the FUNCTION POINTER, not on a header word. The door setter's
    argc was measured at 3 (D102) against a header that declares 1, so assuming
    an argc for a second setter would be repeating that mistake rather than
    learning from it. Any `USER_FUNC` calling the wanted function counts.
*/
static unsigned char *setter_array(const char *map, void *fn, s32 *count)
{
    unsigned char *data = (unsigned char *) mapDataPtr(map);
    u32 *script;
    u32 at = 0;

    *count = -1;
    if (data == 0)
        return 0;
    script = *(u32 **) (data + MAP_INIT_SCRIPT);
    if (script == 0)
        return 0;

    while (at < DOOR_WALK_LIMIT)
    {
        u32 header = script[at];
        u32 argc = header >> 16;
        u32 opcode = header & 0xFFFFu;

        if (opcode == EVT_END_SCRIPT)
            return 0;
        if (opcode > EVT_MAX_OPCODE || argc > EVT_MAX_ARGC)
            return 0;
        if (opcode == EVT_USER_FUNC && argc >= 3 && script[at + 1] == (u32) fn)
        {
            *count = (s32) script[at + 3];
            return (unsigned char *) script[at + 2];
        }
        at += 1 + argc;
    }
    return 0;
}

void bleck_dump_door_names(const char *map)
{
    unsigned char *descs;
    s32 count = -1;
    s32 i;
    u32 word;

    for (word = 0; word < 4 + DOOR_MAX * PER_DOOR; word++)
        names[word] = 0;
    names[0] = NAMES_MAGIC;

    descs = setter_array(map, (void *) &evt_door_set_door_descs, &count);
    names[1] = (u32) count;
    names[2] = (u32) descs;
    if (descs == 0 || count <= 0)
        return;

    for (i = 0; i < count && i < DOOR_MAX; i++)
    {
        unsigned char *desc = descs + i * DOORDESC_SIZE;
        u32 base = 4 + (u32) i * PER_DOOR;

        names[base] = *(u32 *) (desc + DOOR_INTERACT);
        copy_text(base + 1, *(const char **) (desc + DOOR_NAME));
        copy_text(base + 7, *(const char **) (desc + DOOR_MAPGRP));
        copy_text(base + 13, *(const char **) (desc + DOOR_HITGRP));
    }
}

/*
    The OTHER kind of door.

    ⚠️ A map's visible doorways are not all `DoorDesc`s. `MapDoorDesc` is 0x20
    and carries a destination instead of scripts:

        +0x04 name_l   +0x14 destMapName
        +0x08 name_r   +0x18 destDoorName

    **These have no scripts at all**, so `code.patches`' `door:` selector cannot
    reach them and never will -- there is nothing there to patch. Reporting
    them is what makes "the map has three doors but a count of one" legible
    rather than looking like a broken read.
*/
#define MAPDOOR_SIZE 0x20
#define MAPDOOR_NAME_L 0x04
#define MAPDOOR_DEST_MAP 0x14
#define MAPDOOR_DEST_DOOR 0x18

#define ZONES 0x80005800
#define ZONES_MAGIC 0x5A4F4E45U /* 'ZONE' */

#define PER_ZONE 19

static volatile u32 *const zones = (volatile u32 *) ZONES;

static void copy_zone_text(u32 slot, const char *text)
{
    volatile unsigned char *out = (volatile unsigned char *) (zones + slot);
    u32 i;

    for (i = 0; i < TEXT_BYTES; i++)
        out[i] = 0;
    if (text == 0)
        return;
    for (i = 0; i < TEXT_BYTES - 1 && text[i] != 0; i++)
        out[i] = (unsigned char) text[i];
}

void bleck_dump_map_doors(const char *map)
{
    unsigned char *descs;
    s32 count = -1;
    s32 i;
    u32 word;

    for (word = 0; word < 4 + DOOR_MAX * PER_ZONE; word++)
        zones[word] = 0;
    zones[0] = ZONES_MAGIC;

    descs = setter_array(map, (void *) &evt_door_set_map_door_descs, &count);
    zones[1] = (u32) count;
    zones[2] = (u32) descs;
    if (descs == 0 || count <= 0)
        return;

    for (i = 0; i < count && i < DOOR_MAX; i++)
    {
        unsigned char *desc = descs + i * MAPDOOR_SIZE;
        u32 base = 4 + (u32) i * PER_ZONE;

        copy_zone_text(base, *(const char **) (desc + MAPDOOR_NAME_L));
        copy_zone_text(base + 6, *(const char **) (desc + MAPDOOR_DEST_MAP));
        copy_zone_text(base + 12, *(const char **) (desc + MAPDOOR_DEST_DOOR));
    }
}
