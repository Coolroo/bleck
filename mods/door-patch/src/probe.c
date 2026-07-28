/*
    Does `door:<map>:<index>` reach a real door's interact script?

    Two patches, and the pair is the point:

      door:he1_01:0   he1_01 registers exactly ONE door (D102), so index 0 must
                      resolve to a script.
      door:he1_01:9   the same map, an index past the end. Must report NO_SCRIPT
                      rather than reading past the descriptor array -- the count
                      argument beside the array is what bounds it.

    A run where both report the same thing proves nothing, whichever thing it
    is. The negative is what shows the bounds check exists rather than the
    resolver merely returning something plausible.

    `expect` is 0x0004005C -- USER_FUNC argc 4 -- which is a GUESS about what a
    door interact script opens with. If it is wrong the status reads REFUSED,
    which is still informative: REFUSED means the script was FOUND and the guard
    declined, so the resolution worked and only the offset is wrong. NO_SCRIPT
    on index 0 would mean the resolver failed.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'DPAT'
      +0x04 ( 1)  bleck_patch_count -- 2
      +0x08 ( 2)  status[0], door 0.  2 applied, 3 refused, 4 no script
      +0x0C ( 3)  status[1], door 9.  MUST be 4
      +0x10 ( 4)  entries into the patched script's hook
      +0x14 ( 5)  SEQ_GAME frames
      +0x18 ( 6)  sentinel, written once at mod_prolog
      +0x1C ( 7)  door 0's interactScript pointer
      +0x20 ( 8)  its first word -- the header `expect` has to name
      +0x24 ( 9)  its second word
      +0x28 (10)  its third word
      +0x2C (11)  descriptor count the map registered

    Run with:  scripts/ingame.py door-patch --words 8 --seconds 75
    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x44504154U /* 'DPAT' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

extern u32 bleck_patch_status[];
extern const u32 bleck_patch_count;

/*
    The same lookup the generated resolver does, repeated here for one reason:
    to report the WORD a door interact script opens with. `expect` in the
    manifest above is a guess, and a guess is why status[0] reads REFUSED. The
    resolver cannot report this itself -- it has no report block -- so the probe
    re-walks rather than the runtime growing a debug channel.
*/
extern void *mapDataPtr(const char *name);
extern void evt_door_set_door_descs(void);

#define DOOR_SETTER_HEADER 0x0003005CU
#define MAP_INIT_OFFSET 0x18
#define DOORDESC_SIZE 0x58
#define DOORDESC_INTERACT 0x40
#define WALK_LIMIT 4096

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define PATCH_COUNT (probe[1])
#define STATUS(i) (probe[2 + (i)])
#define ENTERED (probe[4])
#define GAME_FRAMES (probe[5])
#define SENTINEL (probe[6])
#define SCRIPT_PTR (probe[7])
#define WORD(i) (probe[8 + (i)])
#define DOOR_COUNT (probe[11])

static void readDoorZero(void)
{
    unsigned char *data = (unsigned char *) mapDataPtr("he1_01");
    u32 *script;
    u32 at = 0;

    if (data == 0)
        return;
    script = *(u32 **) (data + MAP_INIT_OFFSET);
    if (script == 0)
        return;

    while (at < WALK_LIMIT)
    {
        u32 header = script[at];
        u32 argc = header >> 16;
        u32 opcode = header & 0xFFFFU;

        if (opcode == 0x0001U || opcode > 0x77U || argc > 16U)
            return;
        if (header == DOOR_SETTER_HEADER
            && script[at + 1] == (u32) &evt_door_set_door_descs)
        {
            unsigned char *descs = (unsigned char *) script[at + 2];
            u32 *interact;
            u32 i;

            DOOR_COUNT = script[at + 3];
            if (descs == 0)
                return;
            interact = *(u32 **) (descs + DOORDESC_INTERACT);
            SCRIPT_PTR = (u32) interact;
            if (interact == 0)
                return;
            for (i = 0; i < 3; i++)
                WORD(i) = interact[i];
            return;
        }
        at += 1 + argc;
    }
}

static SeqFunc *realMain[SEQ_COUNT];

/* evt user-func signature. Returning 2 lets the script advance. */
s32 on_door(void *entry, u32 firstCall)
{
    (void) entry;
    (void) firstCall;
    ENTERED += 1;
    return 2;
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

    for (i = 0; i < 12; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    SENTINEL = 0xD00D0000U;

    PATCH_COUNT = bleck_patch_count;
    STATUS(0) = bleck_patch_status[0];
    STATUS(1) = bleck_patch_status[1];
    readDoorZero();

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
