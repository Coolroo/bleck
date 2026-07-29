/*
    Does a door patch ENTER? 🔶 open since D103, and the last selector never
    observed running -- `map:`, `item:` and `npcdrv:` have all now been seen to
    fire in a live game (D88, D115).

    Using a door needs a controller (D48), so this is attended. `he1_01`
    registers exactly ONE door (D102), and the player's save is in that map,
    which is what makes it a short ask.

    FOUR PATCHES, and the fourth is the control:

      door:he1_01:0:interact   runs when the player uses the door
      door:he1_01:0:init       🔶 when this runs has never been established
      door:he1_01:0:move       🔶 likewise
      door:he1_01:9:interact   index past the end -- MUST report NO_SCRIPT

    A run where all four agree proves nothing, whichever way they agree.

    ⚠️ `expect` is `MULF` for all three, which D103 MEASURED for `interact` and
    which D104 found does NOT hold for `init` or `move` -- both refused, and
    what they open with was never recorded. So this probe re-walks the map's
    init script and reports the first four words of all three, making a refusal
    self-correcting rather than costing another boot.

    ⚠️ THE INTERACT SCRIPT IS READ BACK AFTER PATCHING, so its first word shows
    the USER_FUNC that was written, not the original `MULF`. That is D103's
    same-size rule visible in memory, not a contradiction.

    ⛔ D104 SHIPPED A LAYOUT DEFECT: `STATUS(3)` was `probe[5]`, which
    `GAME_FRAMES` also wrote, so the out-of-bounds row's status was overwritten
    every frame and never observed. The layout below keeps every field disjoint;
    that is the whole reason this is a new mod rather than a rerun of
    `door-patch`.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'DOOR'
      +0x04 ( 1)  SEQ_GAME frames. The control: zero invalidates the run
      +0x08 ( 2)  ENTERED -- times any door hook ran. THE ANSWER
      +0x0C ( 3)  WHICH -- 1 interact, 2 init, 3 move, 0 none
      +0x10 ( 4)  interact enter count
      +0x14 ( 5)  init enter count
      +0x18 ( 6)  move enter count
      +0x1C ( 7) .. (10)  status: interact, init, move, index 9 (MUST be 4)
      +0x2C (11)  descriptor count the map registered -- D102 read 1
      +0x30 (12)  DoorDesc[0].interactScript -- D102 read 0x80D2FB78
      +0x34 (13)  DoorDesc[0].initScript     -- D102 read 0x80D2F9E0
      +0x38 (14)  DoorDesc[0].moveScript     -- D102 read 0x80D2FB70
      +0x3C (15) .. (18)  interactScript words 0-3 (post-patch, see above)
      +0x4C (19) .. (22)  initScript words 0-3 -- the `expect` D104 lacked
      +0x5C (23) .. (26)  moveScript words 0-3

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x444F4F52U /* 'DOOR' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define PATCH_COUNT 4

extern u32 bleck_patch_status[];

/*
    The same lookup the generated resolver does, repeated here to report the
    WORDS each door script opens with. The resolver cannot report this itself --
    it has no report block -- so the probe re-walks rather than the runtime
    growing a debug channel.
*/
extern void *mapDataPtr(const char *name);
extern void evt_door_set_door_descs(void);

#define DOOR_SETTER_HEADER 0x0003005CU
#define MAP_INIT_OFFSET 0x18
#define DOORDESC_INTERACT 0x40
#define DOORDESC_INIT 0x50
#define DOORDESC_MOVE 0x54
#define WALK_LIMIT 4096
#define HEAD_WORDS 4

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define GAME_FRAMES (probe[1])
#define ENTERED (probe[2])
#define WHICH (probe[3])
#define COUNT(i) (probe[4 + (i)])
#define STATUS(i) (probe[7 + (i)])
#define DOOR_COUNT (probe[11])
#define PTR(i) (probe[12 + (i)])
#define HEAD(script, word) (probe[15 + (script) * HEAD_WORDS + (word)])

#define REPORT_WORDS 27

static SeqFunc *realMain[SEQ_COUNT];

/*
    evt user-func signature. Returning 2 lets the script advance, so the door
    still does whatever it did -- this observes, it does not replace. Returning
    0 here would stall the script, which on a door's interact script is a door
    that cannot be opened.
*/
static s32 entered(u32 which)
{
    ENTERED += 1;
    WHICH = which;
    COUNT(which - 1) += 1;
    return 2;
}

s32 on_door_interact(void *e, u32 f) { (void) e; (void) f; return entered(1); }
s32 on_door_init(void *e, u32 f) { (void) e; (void) f; return entered(2); }
s32 on_door_move(void *e, u32 f) { (void) e; (void) f; return entered(3); }

static void readHead(u32 slot, u32 *script)
{
    u32 i;

    PTR(slot) = (u32) script;
    if (script == 0)
        return;
    for (i = 0; i < HEAD_WORDS; i++)
        HEAD(slot, i) = script[i];
}

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

            DOOR_COUNT = script[at + 3];
            if (descs == 0)
                return;
            readHead(0, *(u32 **) (descs + DOORDESC_INTERACT));
            readHead(1, *(u32 **) (descs + DOORDESC_INIT));
            readHead(2, *(u32 **) (descs + DOORDESC_MOVE));
            return;
        }
        at += 1 + argc;
    }
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

    for (i = 0; i < REPORT_WORDS; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    for (i = 0; i < PATCH_COUNT; i++)
        STATUS(i) = bleck_patch_status[i];
    readDoorZero();

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
