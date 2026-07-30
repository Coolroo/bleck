/*
    The 🔶 D92 left open: an item patch has been APPLIED and never ENTERED.

    Using an item needs menu navigation and input cannot be injected (D48), so
    this is an attended test -- a human loads a save, opens the menu and uses
    an item while the rig reads memory.

    ⛔ THE FIRST ATTENDED RUN TESTED IDS THE TABLE NEVER HELD. It patched 0x50
    and 0xD4 on the guess that one was Shroom Shake; both reported NOT_FOUND,
    because `itemEventDataTable` holds 33 *effect* items and an item with no
    scripted use is simply absent (D109). That run cost a human twenty minutes
    and settled nothing.

    So this version removes both ways the run can fail for reasons unrelated to
    the question:

    1. IT PATCHES IDS MEASURED TO BE IN THE TABLE. 0x41-0x48 are the first eight
       entries, read off the live table in D91 -- Fire Burst, Ice Storm, Thunder
       Rage, Shooting Star, POW Block, Shell Shock, and the two Gold Bars. Each
       has its OWN handler, so the report says which item was used rather than
       needing it known in advance.

    2. IT GIVES THE PLAYER ONE. `pouchAddItem(0x41)` is called once, on the first
       frame the pouch exists, so the test does not depend on what the save
       happens to be carrying. That is also a finding in its own right: whether
       a mod can put an item in the pouch at all.

    ⚠️ `expect` is USER_FUNC argc 4, which D91 measured for entry 0 and which
    need not hold for the other seven. A wrong guess reports REFUSED -- so the
    probe also reads each script's real first word, and one run settles both.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'ITEM'
      +0x04 ( 1)  ENTERED -- times any handler ran. THE ANSWER
      +0x08 ( 2)  WHICH -- item id of the last handler to run, 0 if none
      +0x0C ( 3)  SEQ_GAME frames. The control: zero invalidates the run
      +0x10 ( 4)  pouch pointer as last read. The precondition for the grant
      +0x14 ( 5)  grant state -- see BLECK_GRANT_* below
      +0x18 ( 6)  .. (13)  status, one per id.  2 applied, 3 refused, 5 no such id
      +0x38 (14)  .. (21)  entries sharing that id's script
      +0x58 (22)  .. (29)  per-id enter counts
      +0x78 (30)  .. (37)  each id's useScript pointer, walked here
      +0x98 (38)  .. (45)  its first word -- what `expect` should have been
      +0xB8 (46)  .. (78)  every itemId the table holds, 33 of them

    Read all 79 words. They are free; a second attended run is not.

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

/* The eight ids patched, in manifest order. */
#define PATCHED 8
#define FIRST_ID 0x41

/* The one granted, so the run does not depend on the save's contents. */
#define GRANT_ID 0x41

/* probe[5]. Distinguishes "never tried" from "tried and refused". */
#define BLECK_GRANT_UNTRIED 0
#define BLECK_GRANT_NO_POUCH 1
#define BLECK_GRANT_ADDED 2
#define BLECK_GRANT_REFUSED 3

typedef struct
{
    s32 itemId;
    u32 *useScript;
    const char *useMsgName;
} ItemEventData;

extern ItemEventData itemEventDataTable[];
extern u32 bleck_patch_status[];
extern u32 bleck_patch_shared[];

/* mario_pouch.h. `pouchAddItem` returns bool; read as int, r3 either way. */
extern void *pouchGetPtr(void);
extern int pouchAddItem(s32 itemId);

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define ENTERED (probe[1])
#define WHICH (probe[2])
#define GAME_FRAMES (probe[3])
#define POUCH_PTR (probe[4])
#define GRANT (probe[5])
#define STATUS(i) (probe[6 + (i)])
#define SHARED(i) (probe[14 + (i)])
#define COUNT(i) (probe[22 + (i)])
#define SCRIPT(i) (probe[30 + (i)])
#define WORD(i) (probe[38 + (i)])
#define ID(i) (probe[46 + (i)])
#define REPORT_WORDS 79

static SeqFunc *realMain[SEQ_COUNT];

/*
    evt's user-func signature. Returning 2 lets the script advance, so the item
    still does whatever it did -- this observes, it does not replace.
*/
static s32 entered(u32 slot)
{
    ENTERED += 1;
    WHICH = FIRST_ID + slot;
    COUNT(slot) += 1;
    return 2;
}

/*
    Written out rather than macro-generated: `bleck` checks that every `call`
    named in the manifest is defined in these sources, and it reads the source
    text, so a macro-generated name is invisible to it and the build fails.
    That check is worth more than the brevity.
*/
s32 on_item_41(void *e, u32 f) { (void) e; (void) f; return entered(0); }
s32 on_item_42(void *e, u32 f) { (void) e; (void) f; return entered(1); }
s32 on_item_43(void *e, u32 f) { (void) e; (void) f; return entered(2); }
s32 on_item_44(void *e, u32 f) { (void) e; (void) f; return entered(3); }
s32 on_item_45(void *e, u32 f) { (void) e; (void) f; return entered(4); }
s32 on_item_46(void *e, u32 f) { (void) e; (void) f; return entered(5); }
s32 on_item_47(void *e, u32 f) { (void) e; (void) f; return entered(6); }
s32 on_item_48(void *e, u32 f) { (void) e; (void) f; return entered(7); }

static void readTable(void)
{
    u32 i;
    u32 slot;

    /*
        DUMP the ids, do not search for the eight.

        The first run asked "is 0x50 or 0xD4 in the table" and got NOT_FOUND for
        both, which is a correct answer to a question that could only confirm or
        deny a guess. `item_data_ids.h` is not the authority either -- the table
        is a subset of it, and D102 showed a header can simply be wrong.
    */
    for (i = 0; i < ITEM_TABLE_ENTRIES; i++)
    {
        s32 id = itemEventDataTable[i].itemId;
        u32 *script = itemEventDataTable[i].useScript;

        ID(i) = (u32) id;
        if (id < FIRST_ID || id >= FIRST_ID + PATCHED)
            continue;

        slot = (u32) (id - FIRST_ID);
        SCRIPT(slot) = (u32) script;
        if (script != 0)
            WORD(slot) = script[0];
    }
}

/*
    Put a Fire Burst in the pouch, once.

    The pouch does not exist during the attract demo -- `pouchGetPtr()` is null
    at every point D109 tried -- so this cannot run at mod_prolog. It runs per
    frame and reports the pointer it saw, because "the pouch was never there"
    and "the add was refused" are different failures that would otherwise look
    the same.
*/
static void grantOnce(void)
{
    void *pouch;

    if (GRANT >= BLECK_GRANT_ADDED)
        return;

    pouch = pouchGetPtr();
    POUCH_PTR = (u32) pouch;
    if (pouch == 0)
    {
        GRANT = BLECK_GRANT_NO_POUCH;
        return;
    }

    GRANT = pouchAddItem(GRANT_ID) ? BLECK_GRANT_ADDED : BLECK_GRANT_REFUSED;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        grantOnce();
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

    for (i = 0; i < PATCHED; i++)
    {
        STATUS(i) = bleck_patch_status[i];
        SHARED(i) = bleck_patch_shared[i];
    }
    readTable();

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
