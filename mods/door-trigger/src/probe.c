/*
    Can a door be used without a player?

    Every door finding so far has ended "needs a human to walk into it", which
    caps how fast this can move. `he1_01` door 0's interact script is reachable
    from code, and if running it drives the actual transition -- Lineland Road
    to `he1_06`, Bestovius's house -- then doors become testable unattended.

    ⚠️ NOTHING IS SWAPPED HERE. This runs the game's OWN script, unmodified.
    Mixing the swap into this run would leave two explanations for anything odd,
    which is the mistake D127 already paid for.

    THE OBSERVABLE IS THE MAP NAME. `scripts/ingame.py` prints `map=` every
    poll, so a transition to `he1_06` needs no probe word at all -- the rig
    already reports it, and it cannot be faked by a counter of mine.

    Report block at PROBE, big-endian u32:

      +0x000 ( 0)  magic 'DTRG'
      +0x004 ( 1)  SEQ_GAME frames
      +0x008 ( 2)  SEQ_MAPCHANGE frames -- climbs if the door transitions
      +0x00C ( 3)  the interact script pointer, 0 if unresolved
      +0x010 ( 4)  frame it was started, 0 if never
      +0x014 ( 5)  what evtEntry returned -- 0 means the VM refused it
      +0x018 ( 6)  times __assert2 fired
      +0x01C ( 7)  the line of the first one
      +0x020 ( 8)  the DoorDesc made active, 0 if not resolved
      +0x024 ( 9)  the flags halfword before and after, packed

    Read all 10 words.

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;
typedef unsigned char u8;

#define PROBE 0x80005000
#define MAGIC 0x44545247U /* 'DTRG' */

#define SEQ_COUNT 6
#define SEQ_GAME 2
#define SEQ_MAPCHANGE 3
#define REPORT_WORDS 10

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

/* Late enough that the map has finished assembling itself. */
#define FIRE_AT 900

/*
    The "active door" state, read out of `evtDoorGetActiveDoorDesc`
    (0x800e11b0): it returns `*(doorWork + 0x2D8)` when bit 11 of the flags
    halfword at +0 is set, and 0 otherwise. Running the interact script with no
    active door produced an EvtEntry and no transition, so this supplies the
    context the script was missing.

    🔶 A guess grounded in that one function, not a mapped state machine. If it
    still does not transition, the next step is finding what else the script
    reads rather than setting more bits hopefully.
*/
/* r13 (0x805B5F00) - 32480. ⚠️ I first wrote 0x805AD660 here, which is the
   arithmetic wrong by 0x9C0 -- it read a pointer out of unrelated memory and
   the game froze. Computed, not eyeballed. */
#define DOOR_WORK 0x805AE020
#define DOOR_ACTIVE_DESC 0x2D8
#define DOOR_ACTIVE_FLAG 0x0800

extern void *mapDataPtr(const char *name);
extern void *evtEntry(const s32 *script, u32 priority, u8 flags);
extern void evt_door_set_door_descs(void);

typedef void(SeqFunc)(void *);
typedef struct { SeqFunc *init; SeqFunc *main; SeqFunc *exit; } SeqDef;
extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define MAPCHANGE_FRAMES (probe[2])
#define SCRIPT (probe[3])
#define FIRED (probe[4])
#define ENTRY (probe[5])
#define ASSERTS (probe[6])
#define ASSERT_LINE (probe[7])
#define ACTIVE (probe[8])
#define FLAGS (probe[9])

static SeqFunc *realMain[SEQ_COUNT];

/* The descriptor itself, not the script inside it -- the active-door slot
   wants the record. */
static unsigned char *door_desc(const char *map, s32 index)
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
            return descs + index * DOORDESC_SIZE;
        }
        at += 1 + argc;
    }
    return 0;
}


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

void on_assert(const char *file, s32 line, const char *func, const char *expr)
{
    (void) file; (void) func; (void) expr;
    if (ASSERTS == 0)
        ASSERT_LINE = (u32) line;
    ASSERTS += 1;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_MAPCHANGE)
        MAPCHANGE_FRAMES += 1;
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        if (FIRED == 0 && GAME_FRAMES > FIRE_AT)
        {
            u32 *script = door_script(DOOR_MAP, DOOR_INDEX, DOOR_INTERACT);
            unsigned char *desc = door_desc(DOOR_MAP, DOOR_INDEX);
            unsigned char *work = *(unsigned char **) DOOR_WORK;

            /* ⚠️ Refuse an implausible pointer rather than writing through it.
               A wrong DOOR_WORK froze the game once already, and a freeze
               reports nothing. MEM1 is 0x80000000-0x81800000. */
            if ((u32) work < 0x80000000u || (u32) work >= 0x81800000u)
                work = 0;

            SCRIPT = (u32) script;
            ACTIVE = (u32) desc;
            if (script != 0 && desc != 0 && work != 0)
            {
                unsigned short before = *(unsigned short *) work;

                *(unsigned char **) (work + DOOR_ACTIVE_DESC) = desc;
                *(unsigned short *) work = (unsigned short) (before | DOOR_ACTIVE_FLAG);
                FLAGS = ((u32) before << 16) | (u32) *(unsigned short *) work;

                FIRED = GAME_FRAMES;
                ENTRY = (u32) evtEntry((const s32 *) script, 0, 0);
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

    for (i = 0; i < REPORT_WORDS; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
