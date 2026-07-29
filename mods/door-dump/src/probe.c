/*
    Read the door's interact script, rather than guessing what it wants.

    D139 ran it twice and got an EvtEntry and no transition. The likely reason,
    from someone who has actually played the game: **a door is activated by
    standing on it and pressing up**, so the script almost certainly checks
    where Mario is and gives up immediately. Guessing at more engine state to
    satisfy is how D70-D74 burned six runs; the bytecode says what it checks.

    Copies the script verbatim into the report block. Decoding happens offline
    with `bleck`'s own opcode table -- nothing needs to be interpreted here,
    where a mistake costs a boot.

    Report block at PROBE, big-endian u32:

      +0x000 ( 0)  magic 'DDMP'
      +0x004 ( 1)  SEQ_GAME frames
      +0x008 ( 2)  the script's address, 0 if unresolved
      +0x00C ( 3)  words copied
      +0x010 ( 4) ..  the bytecode

    Read 4 + DUMP_WORDS.

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x44444D50U /* 'DDMP' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

/* Generous: an interact script that opens a door, plays a sound and changes
   map is not short, and reading too few words has already cost this session
   three re-runs. */
#define DUMP_WORDS 192

#define DOOR_MAP "he1_01"
#define DOOR_INDEX 0
#define DOORDESC_SIZE 0x58
#define DOOR_INTERACT 0x40

#define MAP_INIT_SCRIPT 0x18
#define EVT_USER_FUNC 0x005Cu
#define EVT_END_SCRIPT 0x0001u
#define EVT_MAX_OPCODE 0x0077u
#define EVT_MAX_ARGC 16u
#define WALK_LIMIT 4096

extern void *mapDataPtr(const char *name);
extern void evt_door_set_door_descs(void);

typedef void(SeqFunc)(void *);
typedef struct { SeqFunc *init; SeqFunc *main; SeqFunc *exit; } SeqDef;
extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define SCRIPT (probe[2])
#define COPIED (probe[3])

static SeqFunc *realMain[SEQ_COUNT];

static u32 *door_script(const char *map, s32 index, s32 offset)
{
    unsigned char *data = (unsigned char *) mapDataPtr(map);
    u32 *script;
    u32 at = 0;

    if (data == 0)
        return 0;
    script = *(u32 **) (data + MAP_INIT_SCRIPT);
    if (script == 0)
        return 0;
    while (at < WALK_LIMIT)
    {
        u32 header = script[at];
        u32 argc = header >> 16;
        u32 opcode = header & 0xFFFFu;

        if (opcode == EVT_END_SCRIPT)
            return 0;
        if (opcode > EVT_MAX_OPCODE || argc > EVT_MAX_ARGC)
            return 0;
        if (opcode == EVT_USER_FUNC && argc >= 3
            && script[at + 1] == (u32) &evt_door_set_door_descs)
        {
            unsigned char *descs = (unsigned char *) script[at + 2];

            if (descs == 0 || index >= (s32) script[at + 3])
                return 0;
            return *(u32 **) (descs + index * DOORDESC_SIZE + offset);
        }
        at += 1 + argc;
    }
    return 0;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        if (COPIED == 0 && GAME_FRAMES > 300)
        {
            u32 *script = door_script(DOOR_MAP, DOOR_INDEX, DOOR_INTERACT);

            SCRIPT = (u32) script;
            if ((u32) script >= 0x80000000u && (u32) script < 0x81800000u)
            {
                u32 i;

                for (i = 0; i < DUMP_WORDS; i++)
                    probe[4 + i] = script[i];
                COPIED = DUMP_WORDS;
            }
        }
    }
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

    for (i = 0; i < 4 + DUMP_WORDS; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
