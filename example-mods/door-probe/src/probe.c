/*
    Can a door's scripts be reached without hooking a game function?

    D91 ruled out reaching doors by name: `DoorDesc` has no lookup, and
    `evtDoorGetActiveDoorDesc()` returns the door currently in use, which is
    null at `mod_prolog`. The recorded fallback was intercepting
    `evt_door_set_door_descs` -- which means patching a PowerPC instruction and
    flushing caches, a capability bleck does not have.

    There may be no need. `evt_door_set_door_descs` is an *evt user func*, so a
    map's init script calls it through USER_FUNC, and the descriptor array's
    address is sitting in the bytecode as that call's argument. Reading it uses
    only what D89 already proved.

    `EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)` means the instruction is
    header argc=2, then [0x800e2610, descs].

    This walks each candidate map's init script instruction by instruction --
    decoding argc from every header rather than scanning for a value, so a
    number that merely looks like the target cannot match -- and stops at
    END_SCRIPT.

    DoorDesc is 0x58 bytes: interactScript +0x40, initScript +0x50,
    moveScript +0x54.

    Report block at PROBE, big-endian u32:

      +0x00  magic 'DOOR'
      +0x04  descs pointer found, per candidate map          [1..5]
      +0x18  words walked, per candidate map                 [6..10]
      +0x2C  first map index with doors, or -1               [11]
      +0x30  DoorDesc[0].interactScript                      [12]
      +0x34  DoorDesc[0].initScript                          [13]
      +0x38  DoorDesc[0].moveScript                          [14]
      +0x3C  first 4 words of whichever script is non-null   [15..18]
      +0x4C  SEQ_GAME frames                                 [19]

    Target: eu0. Nothing here writes to game memory.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x444F4F52U /* 'DOOR' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define MAP_INIT_OFFSET 0x18

#define DOOR_SETTER 0x800E2610U
#define USER_FUNC_2 0x0002005CU
/* D88: evt_hitobj_attr_onoff, called with argc=5 from he1_01's script. */
#define USER_FUNC_5 0x0005005CU
#define CONTROL_FUNC 0x800EB72CU

#define OP_END_SCRIPT 0x0001U
#define WALK_LIMIT 4096

#define DOOR_INTERACT 0x40
#define DOOR_INIT 0x50
#define DOOR_MOVE 0x54

#define CANDIDATES 5

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

#define DESCS(i) (probe[1 + (i)])
#define WALKED(i) (probe[6 + (i)])
#define FOUND_AT (probe[11])
#define D_INTERACT (probe[12])
#define D_INIT (probe[13])
#define D_MOVE (probe[14])
#define WORD(i) (probe[15 + (i)])
#define GAME_FRAMES (probe[19])
#define CONTROL_HITS (probe[20])

/* Flipside first -- it is the hub and is dense with doors. */
static const char *const candidates[CANDIDATES] = {
    "mac_01", "he1_01", "aa4_01", "ls4_12", "he2_01",
};

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

static u32 *initScriptOf(const char *name)
{
    unsigned char *entry = (unsigned char *) mapDataPtr(name);

    if (entry == 0)
        return 0;
    return *(u32 **) (entry + MAP_INIT_OFFSET);
}

/* Walk the script properly: every header declares its argument count, so the
   next header is at a known offset. A naive search for DOOR_SETTER could match
   an argument that happens to hold that value. */
static u32 findDescs(u32 *script, u32 *walkedOut)
{
    u32 at = 0;
    u32 found = 0;

    while (at < WALK_LIMIT)
    {
        u32 header = script[at];
        u32 argc = header >> 16;
        u32 opcode = header & 0xFFFFU;

        if (opcode == OP_END_SCRIPT)
            break;
        /* A header whose opcode is out of range means the walk has desynced;
           stop rather than wander into unrelated memory. */
        if (opcode > 0x77U || argc > 16U)
            break;

        if (header == USER_FUNC_2 && script[at + 1] == DOOR_SETTER && found == 0)
            found = script[at + 2];

        /* Positive control. D88 recorded that he1_01's script contains
           USER_FUNC argc=5 to evt_hitobj_attr_onoff. If the walker cannot find
           a call it is known to contain, "no door setter" says nothing about
           the game and everything about this loop. */
        if (header == USER_FUNC_5 && script[at + 1] == CONTROL_FUNC)
            CONTROL_HITS += 1;

        at += 1 + argc;
    }

    *walkedOut = at;
    return found;
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
    u32 firstDescs = 0;
    u32 i;

    for (i = 0; i < 22; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    FOUND_AT = 0xFFFFFFFFU;

    for (i = 0; i < CANDIDATES; i++)
    {
        u32 *script = initScriptOf(candidates[i]);
        u32 walked = 0;
        u32 descs = 0;

        if (script != 0)
            descs = findDescs(script, &walked);

        DESCS(i) = descs;
        WALKED(i) = walked;

        if (descs != 0 && firstDescs == 0)
        {
            firstDescs = descs;
            FOUND_AT = i;
        }
    }

    if (firstDescs != 0)
    {
        unsigned char *door = (unsigned char *) firstDescs;
        u32 *script;

        D_INTERACT = *(u32 *) (door + DOOR_INTERACT);
        D_INIT = *(u32 *) (door + DOOR_INIT);
        D_MOVE = *(u32 *) (door + DOOR_MOVE);

        script = (u32 *) (D_INIT != 0 ? D_INIT : D_INTERACT);
        if (script != 0)
            for (i = 0; i < 4; i++)
                WORD(i) = script[i];
    }

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
