/*
    What argument count do the door setter calls actually declare?

    D101 found the calls by matching the function pointer alone, at whatever
    argc the header declared -- deliberately, because assuming an argc is what
    made D93 miss them. That leaves the argc itself unmeasured, and D92's
    replacement carries the SAME argument count as the instruction it
    overwrites. Patching at the wrong size corrupts the script rather than
    failing, so this has to be read rather than inferred.

    ⚠️ `evt_door.h` cannot answer it. Its
    `EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)` says argc 2, and the
    comment directly above it says `(DoorDesc *descs, s32 count)`, which is
    argc 3. One of them is wrong; D101 showed the macro is. So the header is
    not evidence here, and the bytecode is.

    Also fixes a gap in D101's own probe, which recorded the first
    `set_door_descs` argument without recording WHICH MAP it came from.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'DARG'
      +0x04 ( 1)  set_door_descs      header word, first call seen
      +0x08 ( 2)  set_door_descs      map index of that call, else -1
      +0x0C ( 3)  set_door_descs      word at +2 (the descs pointer)
      +0x10 ( 4)  set_door_descs      word at +3 (the count, if argc >= 3)
      +0x14 ( 5)  set_map_door_descs  header word
      +0x18 ( 6)  set_map_door_descs  map index
      +0x1C ( 7)  set_map_door_descs  word at +2
      +0x20 ( 8)  set_map_door_descs  word at +3
      +0x24 ( 9)  set_dokan_descs     header word
      +0x28 (10)  set_dokan_descs     map index
      +0x2C (11)  CONTROL: evt_hitobj_attr_onoff header word. ⚠️ D88 recorded
                  this call with argc 5, so this MUST read 0x0005005C -- it is
                  the check that the header word is being read from the right
                  offset at all
      +0x30 (12)  CONTROL hits. Zero invalidates the run
      +0x34 (13)  DoorDesc[0].interactScript   from the found descs
      +0x38 (14)  DoorDesc[0].initScript
      +0x3C (15)  DoorDesc[0].moveScript
      +0x40 (16)  MapDoorDesc[0].destMapName bytes 0..3  -- must spell a map
      +0x44 (17)  ... bytes 4..7
      +0x48 (18)  MapDoorDesc[0].destDoorName bytes 0..3
      +0x4C (19)  ... bytes 4..7
      +0x50 (20)  walks truncated at the limit. Non-zero invalidates the run
      +0x54 (21)  SEQ_GAME frames

    Run with:  scripts/ingame.py door-argc --words 24 --seconds 90
    Target: eu0. Nothing here writes to game memory.
*/

typedef unsigned int u32;
typedef unsigned char u8;

#define PROBE 0x80005000
#define MAGIC 0x44415247U /* 'DARG' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define MAP_INIT_OFFSET 0x18
#define OP_USER_FUNC 0x005CU
#define OP_END_SCRIPT 0x0001U
#define WALK_LIMIT 4096

#define DOOR_INTERACT 0x40
#define DOOR_INIT 0x50
#define DOOR_MOVE 0x54

#define MAPDOOR_DEST_MAP 0x14
#define MAPDOOR_DEST_DOOR 0x18

#define CANDIDATES 5
#define NAME_WORDS 2

#define FN_DOOR 0x800E2610U
#define FN_MAPDOOR 0x800E4118U
#define FN_DOKAN 0x800E3588U
#define FN_CONTROL 0x800EB72CU

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern void *mapDataPtr(const char *name);

static volatile u32 *const probe = (volatile u32 *) PROBE;

/* Four words each for the two setters whose arguments matter. */
#define DOOR_HEADER (probe[1])
#define DOOR_MAP (probe[2])
#define DOOR_ARG0 (probe[3])
#define DOOR_ARG1 (probe[4])
#define MAPDOOR_HEADER (probe[5])
#define MAPDOOR_MAP (probe[6])
#define MAPDOOR_ARG0 (probe[7])
#define MAPDOOR_ARG1 (probe[8])
#define DOKAN_HEADER (probe[9])
#define DOKAN_MAP (probe[10])
#define CONTROL_HEADER (probe[11])
#define CONTROL_HITS (probe[12])
#define D_INTERACT (probe[13])
#define D_INIT (probe[14])
#define D_MOVE (probe[15])
#define TRUNCATED (probe[20])
#define GAME_FRAMES (probe[21])

static const char *const candidates[CANDIDATES] = {
    "mac_01", "he1_01", "aa4_01", "ls4_12", "he2_01",
};

static SeqFunc *realMain[SEQ_COUNT];

static void copyName(const char *name, volatile u32 *out)
{
    const u8 *bytes = (const u8 *) name;
    u32 i;

    for (i = 0; i < NAME_WORDS; i++)
        out[i] = 0;
    if (name == 0)
        return;
    for (i = 0; i < NAME_WORDS * 4; i++)
    {
        if (bytes[i] == 0)
            break;
        out[i / 4] |= ((u32) bytes[i]) << (24 - 8 * (i % 4));
    }
}

static u32 *initScriptOf(const char *name)
{
    unsigned char *entry = (unsigned char *) mapDataPtr(name);

    if (entry == 0)
        return 0;
    return *(u32 **) (entry + MAP_INIT_OFFSET);
}

/* Record the header WORD, not a decoded count: the word is what a patch guard
   compares against, so it is the thing worth carrying back verbatim. */
static void record(u32 target, u32 header, u32 *at, u32 mapIndex)
{
    u32 argc = header >> 16;

    if (target == FN_DOOR && DOOR_HEADER == 0)
    {
        DOOR_HEADER = header;
        DOOR_MAP = mapIndex;
        DOOR_ARG0 = argc >= 2 ? at[2] : 0;
        DOOR_ARG1 = argc >= 3 ? at[3] : 0;
    }
    else if (target == FN_MAPDOOR && MAPDOOR_HEADER == 0)
    {
        MAPDOOR_HEADER = header;
        MAPDOOR_MAP = mapIndex;
        MAPDOOR_ARG0 = argc >= 2 ? at[2] : 0;
        MAPDOOR_ARG1 = argc >= 3 ? at[3] : 0;
    }
    else if (target == FN_DOKAN && DOKAN_HEADER == 0)
    {
        DOKAN_HEADER = header;
        DOKAN_MAP = mapIndex;
    }
    else if (target == FN_CONTROL)
    {
        CONTROL_HEADER = header;
        CONTROL_HITS += 1;
    }
}

static u32 scan(u32 *script, u32 mapIndex, u32 *hitLimit)
{
    u32 at = 0;

    while (at < WALK_LIMIT)
    {
        u32 header = script[at];
        u32 argc = header >> 16;
        u32 opcode = header & 0xFFFFU;

        if (opcode == OP_END_SCRIPT || opcode > 0x77U || argc > 16U)
        {
            *hitLimit = 0;
            return at;
        }
        if (opcode == OP_USER_FUNC && argc >= 1)
            record(script[at + 1], header, &script[at], mapIndex);
        at += 1 + argc;
    }
    *hitLimit = 1;
    return at;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
        GAME_FRAMES += 1;
    if (realMain[seq] != 0)
        realMain[seq](work);
}

static void seq0(void *w) { onSequenceFrame(0, w); }
static void seq1(void *w) { onSequenceFrame(1, w); }
static void seq2(void *w) { onSequenceFrame(2, w); }
static void seq3(void *w) { onSequenceFrame(3, w); }
static void seq4(void *w) { onSequenceFrame(4, w); }
static void seq5(void *w) { onSequenceFrame(5, w); }

static SeqFunc *const hooks[SEQ_COUNT] = {seq0, seq1, seq2, seq3, seq4, seq5};

void mod_prolog(void)
{
    u32 i;

    for (i = 0; i < 22; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    DOOR_MAP = 0xFFFFFFFFU;
    MAPDOOR_MAP = 0xFFFFFFFFU;
    DOKAN_MAP = 0xFFFFFFFFU;

    for (i = 0; i < CANDIDATES; i++)
    {
        u32 *script = initScriptOf(candidates[i]);
        u32 limit = 0;

        if (script == 0)
            continue;
        scan(script, i, &limit);
        TRUNCATED += limit;
    }

    if (DOOR_ARG0 != 0)
    {
        unsigned char *door = (unsigned char *) DOOR_ARG0;

        D_INTERACT = *(u32 *) (door + DOOR_INTERACT);
        D_INIT = *(u32 *) (door + DOOR_INIT);
        D_MOVE = *(u32 *) (door + DOOR_MOVE);
    }
    if (MAPDOOR_ARG0 != 0)
    {
        unsigned char *zone = (unsigned char *) MAPDOOR_ARG0;

        copyName(*(const char **) (zone + MAPDOOR_DEST_MAP), &probe[16]);
        copyName(*(const char **) (zone + MAPDOOR_DEST_DOOR), &probe[18]);
    }

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
