/*
    D93 searched for ONE door function at ONE argument count. This searches for
    all of them.

    ⚠️ WHY THE EARLIER NEGATIVE IS NOT TRUSTWORTHY. D93's walker matched
    `header == 0x0002005C && script[at+1] == 0x800E2610` -- `evt_door_set_door_descs`
    with argc 2. `spm.eu0.lst` and `evt_door.h` list several more descriptor
    setters, and they do not all take one argument:

      evt_door_set_door_descs       800E2610  EVT_DECLARE_USER_FUNC(_, 1) -> argc 2
      evt_door_set_map_door_descs   800E4118  EVT_DECLARE_USER_FUNC(_, 2) -> argc 3
      evt_door_set_dokan_descs      800E3588  EVT_DECLARE_USER_FUNC(_, 2) -> argc 3

    So a map that registers its loading zones through `set_map_door_descs` would
    have read as "no doors" to D93 no matter how many it had. The negative was
    about the instrument's reach, not about the game.

    That is the same failure D70/D73/D74 recorded: a control does not help when
    it is measured with the same broken ruler. D93 *had* a positive control, and
    the control passed -- it proved the walker could decode instructions, which
    was never the thing in doubt.

    This matches on the FUNCTION POINTER ALONE, at whatever argc the header
    declares, so no argument count can hide a call.

    EVIDENCE, NOT COUNTS. A hit count is a number that could mean anything. If a
    MapDoorDesc array is found, this reads `destMapName` out of its first entry
    and copies the STRING into the report. MapDoorDesc is 0x20 bytes with
    destMapName at +0x14. A correct find spells a map name; a wrong one does not.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'DOR2'
      +0x04 ( 1)  set_door_descs        calls found, all maps
      +0x08 ( 2)  set_map_door_descs    calls found
      +0x0C ( 3)  set_dokan_descs       calls found
      +0x10 ( 4)  enable_disable_door_desc  calls found
      +0x14 ( 5)  set_event             calls found
      +0x18 ( 6)  openable_onoff        calls found
      +0x1C ( 7)  CONTROL: evt_hitobj_attr_onoff calls. ⚠️ Zero invalidates the
                  run -- D88 recorded this call in he1_01's script
      +0x20 ( 8)  first set_door_descs argument (DoorDesc *)
      +0x24 ( 9)  first set_map_door_descs argument (MapDoorDesc *)
      +0x28 (10)  index of the map the map_door_descs came from, else -1
      +0x2C (11)  MapDoorDesc[0].destMapName pointer
      +0x30 (12)  destMapName bytes 0..3   -- readable, or the find is wrong
      +0x34 (13)  destMapName bytes 4..7
      +0x38 (14)  destMapName bytes 8..11
      +0x3C (15)  maps whose init script resolved at all
      +0x40 (16)  words walked, map 0
      +0x44 (17)  ... map 1
      +0x48 (18)  ... map 2
      +0x4C (19)  ... map 3
      +0x50 (20)  ... map 4
      +0x54 (21)  walks that stopped on the 4096-word limit rather than
                  END_SCRIPT. ⚠️ Non-zero means a truncated walk, and D93 nearly
                  recorded one of those as a finding
      +0x58 (22)  SEQ_GAME frames

    Run with:  scripts/ingame.py door-scan --words 24 --seconds 90
    Target: eu0. Nothing here writes to game memory.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;

#define PROBE 0x80005000
#define MAGIC 0x444F5232U /* 'DOR2' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define MAP_INIT_OFFSET 0x18

#define OP_USER_FUNC 0x005CU
#define OP_END_SCRIPT 0x0001U
#define WALK_LIMIT 4096

/* MapDoorDesc is 0x20 bytes; destMapName sits at +0x14. */
#define MAPDOOR_DEST_MAP 0x14

#define WATCHED 6
#define CANDIDATES 5
#define NAME_WORDS 3

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

#define HITS(i) (probe[1 + (i)])
#define CONTROL_HITS (probe[7])
#define DOOR_DESCS (probe[8])
#define MAPDOOR_DESCS (probe[9])
#define FOUND_AT (probe[10])
#define DEST_NAME_PTR (probe[11])
#define WALKED(i) (probe[16 + (i)])
#define RESOLVED (probe[15])
#define TRUNCATED (probe[21])
#define GAME_FRAMES (probe[22])

/* Matched on the pointer alone, at whatever argc the instruction declares. */
static const u32 watched[WATCHED] = {
    0x800E2610U, /* evt_door_set_door_descs */
    0x800E4118U, /* evt_door_set_map_door_descs */
    0x800E3588U, /* evt_door_set_dokan_descs */
    0x800E2908U, /* evt_door_enable_disable_door_desc */
    0x800E45C8U, /* evt_door_set_event */
    0x800E468CU, /* evt_door_openable_onoff */
};

/* D88 recorded this call in he1_01's init script. If the walk cannot find a
   call it is known to contain, every zero above says nothing. */
#define CONTROL_FUNC 0x800EB72CU

/* Flipside first -- it is the hub and is dense with doors. */
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

/*
    Decode the script instruction by instruction. Every header declares its
    argument count, so the next header is at a known offset -- a naive search
    for one of the watched addresses could match an argument that happens to
    hold that value.

    Returns the words walked; sets `*hitLimit` when it stopped on WALK_LIMIT
    rather than END_SCRIPT.
*/
static u32 scan(u32 *script, u32 mapIndex, u32 *hitLimit)
{
    u32 at = 0;

    while (at < WALK_LIMIT)
    {
        u32 header = script[at];
        u32 argc = header >> 16;
        u32 opcode = header & 0xFFFFU;
        u32 i;

        if (opcode == OP_END_SCRIPT)
        {
            *hitLimit = 0;
            return at;
        }
        /* An opcode out of range means the walk has desynced; stop rather than
           wander into unrelated memory and report whatever it finds. */
        if (opcode > 0x77U || argc > 16U)
        {
            *hitLimit = 0;
            return at;
        }

        if (opcode == OP_USER_FUNC && argc >= 1)
        {
            u32 target = script[at + 1];

            for (i = 0; i < WATCHED; i++)
            {
                if (target != watched[i])
                    continue;
                HITS(i) += 1;
                /* argc counts the function pointer, so the first real argument
                   is at +2 and only exists when argc >= 2. */
                if (argc < 2)
                    break;
                if (i == 0 && DOOR_DESCS == 0)
                    DOOR_DESCS = script[at + 2];
                if (i == 1 && MAPDOOR_DESCS == 0)
                {
                    MAPDOOR_DESCS = script[at + 2];
                    FOUND_AT = mapIndex;
                }
                break;
            }
            if (target == CONTROL_FUNC)
                CONTROL_HITS += 1;
        }

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

    for (i = 0; i < 23; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    FOUND_AT = 0xFFFFFFFFU;

    for (i = 0; i < CANDIDATES; i++)
    {
        u32 *script = initScriptOf(candidates[i]);
        u32 limit = 0;

        if (script == 0)
            continue;
        RESOLVED += 1;
        WALKED(i) = scan(script, i, &limit);
        TRUNCATED += limit;
    }

    if (MAPDOOR_DESCS != 0)
    {
        unsigned char *desc = (unsigned char *) MAPDOOR_DESCS;
        const char *dest = *(const char **) (desc + MAPDOOR_DEST_MAP);

        DEST_NAME_PTR = (u32) dest;
        copyName(dest, &probe[12]);
    }

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
