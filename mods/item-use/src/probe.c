/*
    The 🔶 D92 left open: an item patch has been APPLIED and never ENTERED.

    Using an item needs menu navigation and input cannot be injected (D48), so
    this is the first attended test in the repository -- a human loads a save,
    opens the menu and uses the item while the rig reads memory.

    TWO IDS, because which one is "Shroom Shake" is a guess:
      0x50  ITEM_ID_USE_KINOKO_DRINK   "mushroom drink" -- the likely one
      0xD4  ITEM_ID_COOK_MIX_SHAKE     a cooked shake

    Both call the same handler, and `whichEntered` records which id's script it
    came from -- so using the item identifies it rather than needing it known in
    advance.

    ⚠️ `expect` is USER_FUNC argc 4, which D91 measured for item script 0 and
    which need not hold for these. A wrong guess reports REFUSED, so this also
    walks itemEventDataTable itself and reports each script's real first word.
    Then one attended run settles both the id and the opcode, instead of costing
    a second one.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'ITEM'
      +0x04 ( 1)  bleck_patch_status[0]  -- item 0x50.  2 applied, 3 refused,
                  5 no such id
      +0x08 ( 2)  bleck_patch_status[1]  -- item 0xD4
      +0x0C ( 3)  bleck_patch_shared[0]  -- entries sharing 0x50's script
      +0x10 ( 4)  bleck_patch_shared[1]
      +0x14 ( 5)  ENTERED -- times the handler ran. THE ANSWER
      +0x18 ( 6)  which id it came from, or 0
      +0x1C ( 7)  0x50's useScript pointer, walked here
      +0x20 ( 8)  its first word -- what `expect` should have been
      +0x24 ( 9)  0xD4's useScript pointer
      +0x28 (10)  its first word
      +0x2C (11)  entry 0's useScript first word -- what `expect` looks like
      +0x30 (12)  SEQ_GAME frames. The control: zero invalidates the run
      +0x34 (13)  every itemId the table holds, 33 of them

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x4954454DU /* 'ITEM' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

/* D91: 33 entries of {itemId, useScript, useMsgName}, 0xc bytes each. */
#define ITEM_TABLE_ENTRIES 33

typedef struct
{
    s32 itemId;
    u32 *useScript;
    const char *useMsgName;
} ItemEventData;

extern ItemEventData itemEventDataTable[];
extern u32 bleck_patch_status[];
extern u32 bleck_patch_shared[];

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define STATUS(i) (probe[1 + (i)])
#define SHARED(i) (probe[3 + (i)])
#define ENTERED (probe[5])
#define WHICH (probe[6])
#define SCRIPT_A (probe[7])
#define WORD_A (probe[8])
#define SCRIPT_B (probe[9])
#define WORD_B (probe[10])
#define ID(i) (probe[13 + (i)])
#define FIRST_WORD (probe[11])
#define GAME_FRAMES (probe[12])

static SeqFunc *realMain[SEQ_COUNT];

/*
    evt's user-func signature. Returning 2 lets the script advance, so the item
    still does whatever it did -- this observes, it does not replace.
*/
s32 on_item_use(void *entry, u32 firstCall)
{
    (void) entry;
    (void) firstCall;
    ENTERED += 1;
    return 2;
}

static void readTable(void)
{
    u32 i;

    /*
        DUMP the ids, do not search for two.

        The first run asked "is 0x50 or 0xD4 in the table" and got NOT_FOUND for
        both, with all 33 entries matching neither. That is a correct answer to
        a question that could only ever confirm or deny a guess -- and it cost an
        attended run to learn nothing about what the table actually holds.

        `item_data_ids.h` is not the authority here either: the table is a
        subset, and D102 already showed a header can simply be wrong. So this
        reports every id, and the next run picks from measurement.
    */
    for (i = 0; i < ITEM_TABLE_ENTRIES; i++)
    {
        ID(i) = (u32) itemEventDataTable[i].itemId;
        if (i == 0 && itemEventDataTable[i].useScript != 0)
            FIRST_WORD = itemEventDataTable[i].useScript[0];
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

    for (i = 0; i < 46; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    STATUS(0) = bleck_patch_status[0];
    STATUS(1) = bleck_patch_status[1];
    SHARED(0) = bleck_patch_shared[0];
    SHARED(1) = bleck_patch_shared[1];
    readTable();

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
