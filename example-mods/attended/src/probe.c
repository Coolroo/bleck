/*
    The two questions that need a human, answered in one boot.

    Both have the same shape: a patch has been APPLIED and never observed to be
    ENTERED. Using an item needs menu navigation and hurting an enemy needs a
    jump, and input cannot be injected (D48), so a person has to play.

      - item   -- 🔶 since D92
      - npcdrv -- 🔶 since D112

    ⚠️ MERGED ON PURPOSE. They share a save, a map and a boot: he1_01 places two
    Goombas (template 2) and the player carries a pouch. As two mods they would
    cost two boots, two save loads and two walks to the same room -- and both
    write their report to the same address, so they cannot simply run side by
    side. One report block with disjoint words is the whole trick.

    ⛔ WHAT THE LAST ATTENDED RUN GOT WRONG. It patched item ids 0x50 and 0xD4 on
    the guess that one was Shroom Shake. Both reported NOT_FOUND. Twenty minutes
    of a human's time settled nothing.

    So this removes every way the run can fail for a reason unrelated to the
    question being asked:

    1. EVERY ID THE TABLE HOLDS IS PATCHED -- all 33, read off the live table
       rather than guessed, so whatever the player is carrying is covered.
       ⚠️ 22 distinct scripts across 33 entries (D91), so ids sharing a script
       overwrite each other's patch. They all call the SAME handler, which makes
       that harmless; per-id attribution would have been false precision.
    2. THE PLAYER IS GIVEN ONE ANYWAY. `pouchAddItem(0x41)` -- Fire Burst --
       retries until it lands, so the run does not depend on the save's
       contents. Whether a mod can add an item at all is a finding in itself.
    3. A NEGATIVE CONTROL. `npcdrv:999` is past the template range and MUST
       report NO_SCRIPT. A run where all three npc patches agree proves nothing.
    4. EVERY PATCH'S STATUS IS REPORTED, per id. ⚠️ This is the one that matters:
       a REFUSED patch and a hook that never fires produce the same zero. Without
       the status table, using an item whose script the guard declined would read
       as "the item hook does not work".
    5. EVERY PRECONDITION IS REPORTED, not assumed -- the pouch pointer, the
       frame counter, and each target script's real first word. Five instrument
       errors in two days were all of the form "a probe reported the value it
       went looking for and not the precondition it depended on".

    ⚠️ `expect` is USER_FUNC argc 4 for items and argc 3/4 for npc. Where a
    script opens with something else the guard refuses -- correctly -- and the
    dumped first word says what it should have been, so no run is wasted on it.

    Report block at PROBE, big-endian u32. Read ALL of it; words are free and an
    attended run is not.

      +0x000 (  0)  magic 'ATTN'
      +0x004 (  1)  SEQ_GAME frames. The control: zero invalidates the run

      -- item half --
      +0x008 (  2)  ITEM_ENTERED -- times any item script's hook ran. THE ANSWER
      +0x00C (  3)  pouch pointer as last read
      +0x010 (  4)  grant state -- see BLECK_GRANT_* below
      +0x014 (  5)  add attempts
      +0x018 (  6)  adds that returned true
      +0x01C (  7)  the pouch the last successful add went into

      -- npc half --
      +0x020 (  8)  NPC_ENTERED -- times either npc hook ran. THE ANSWER
      +0x024 (  9)  NPC_WHICH -- 1 onhit, 2 death, 0 none
      +0x028 ( 10)  onhit enter count
      +0x02C ( 11)  death enter count
      +0x030 ( 12) .. (14)  status: 2:onhit, 2:death, 999:onhit (MUST be 4)
      +0x03C ( 15) .. (16)  templates sharing 2:onhit / 2:death
      +0x044 ( 17)  template 2's onhit pointer, read here
      +0x048 ( 18)  its first word
      +0x04C ( 19)  template 2's death pointer
      +0x050 ( 20)  its first word

      -- the item table, 33 entries, one word each per row --
      +0x054 ( 21) .. ( 53)  itemId
      +0x0D8 ( 54) .. ( 86)  patch status.  2 applied, 3 refused, 5 no such id
      +0x15C ( 87) .. (119)  first word of its useScript -- the real `expect`
      +0x1E0 (120) .. (152)  entries sharing that script

      -- what a REFUSED item script actually opens with --
      +0x264 (153) .. (160)  first eight words of id 0x46's script

    Target: eu0.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x4154544EU /* 'ATTN' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

/* D91: 33 entries of {itemId, useScript, useMsgName}, 0xc bytes each. */
#define ITEM_TABLE_ENTRIES 33

/* The item patches come first in the manifest, so the status indices line up. */
#define ITEM_PATCHES ITEM_TABLE_ENTRIES

/* Granted so the run does not depend on the save's contents. 0x41, Fire Burst. */
#define GRANT_ID 0x41

/* D112: stride 0x68, and these offsets. D111 had them all 4 bytes high. */
#define TEMPLATE_SIZE 0x68
#define ONHIT 0x3C
#define DEATH 0x48
#define WATCHED_TEMPLATE 2

/* Which entry's script head to dump: 0x46, whose guard refused at `at: 0`. */
#define REFUSED_ID 0x46
#define REFUSED_WORDS 8

/* probe[4]. Distinguishes "never tried" from "tried and refused". */
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
extern u32 npcEnemyTemplates[];
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

#define GAME_FRAMES (probe[1])

#define ITEM_ENTERED (probe[2])
#define POUCH_PTR (probe[3])
#define GRANT (probe[4])
#define GRANT_TRIES (probe[5])
#define GRANT_ADDS (probe[6])
#define GRANT_POUCH (probe[7])

#define NPC_ENTERED (probe[8])
#define NPC_WHICH (probe[9])
#define NPC_COUNT(i) (probe[10 + (i)])
#define NPC_STATUS(i) (probe[12 + (i)])
#define NPC_SHARED(i) (probe[15 + (i)])
#define NPC_ONHIT_PTR (probe[17])
#define NPC_ONHIT_WORD (probe[18])
#define NPC_DEATH_PTR (probe[19])
#define NPC_DEATH_WORD (probe[20])

#define ITEM_ID(i) (probe[21 + (i)])
#define ITEM_STATUS(i) (probe[54 + (i)])
#define ITEM_WORD(i) (probe[87 + (i)])
#define ITEM_SHARED(i) (probe[120 + (i)])
#define REFUSED_WORD(i) (probe[153 + (i)])

#define REPORT_WORDS 161

static SeqFunc *realMain[SEQ_COUNT];

/*
    evt's user-func signature. Returning 2 lets the script advance, so the item
    or the enemy still does whatever it did -- this observes, it does not
    replace. A handler returning 0 would stall the script it sits in, which on
    an enemy's onhit script is a Goomba that cannot be hurt.
*/
s32 on_item_used(void *entry, u32 firstCall)
{
    (void) entry;
    (void) firstCall;
    ITEM_ENTERED += 1;
    return 2;
}

s32 on_npc_hit(void *entry, u32 firstCall)
{
    (void) entry;
    (void) firstCall;
    NPC_ENTERED += 1;
    NPC_WHICH = 1;
    NPC_COUNT(0) += 1;
    return 2;
}

s32 on_npc_death(void *entry, u32 firstCall)
{
    (void) entry;
    (void) firstCall;
    NPC_ENTERED += 1;
    NPC_WHICH = 2;
    NPC_COUNT(1) += 1;
    return 2;
}

static void readItemTable(void)
{
    u32 i;

    /*
        DUMP the table, do not search it.

        The first attended run asked "is 0x50 or 0xD4 in the table" and got
        NOT_FOUND for both -- a correct answer to a question that could only
        confirm or deny a guess. `item_data_ids.h` is not the authority either:
        the table is a subset of it, and D102 showed a header can be wrong.
    */
    for (i = 0; i < ITEM_TABLE_ENTRIES; i++)
    {
        s32 id = itemEventDataTable[i].itemId;
        u32 *script = itemEventDataTable[i].useScript;

        ITEM_ID(i) = (u32) id;
        ITEM_STATUS(i) = bleck_patch_status[i];
        ITEM_SHARED(i) = bleck_patch_shared[i];
        if (script != 0)
            ITEM_WORD(i) = script[0];

        /*
            0x46-0x48 open with `00020032` -- argc 2, opcode 0x32, not
            USER_FUNC -- so the guard refuses them at `at: 0` and is right to.
            Dump one head, so the offset of its first USER_FUNC is a reading
            rather than another guess.
        */
        if (id == REFUSED_ID && script != 0)
        {
            u32 w;

            for (w = 0; w < REFUSED_WORDS; w++)
                REFUSED_WORD(w) = script[w];
        }
    }
}

static void readTemplate(void)
{
    unsigned char *t = (unsigned char *) npcEnemyTemplates;
    u32 *onhit;
    u32 *death;

    t += WATCHED_TEMPLATE * TEMPLATE_SIZE;
    onhit = *(u32 **) (t + ONHIT);
    death = *(u32 **) (t + DEATH);

    NPC_ONHIT_PTR = (u32) onhit;
    NPC_DEATH_PTR = (u32) death;
    if (onhit != 0)
        NPC_ONHIT_WORD = onhit[0];
    if (death != 0)
        NPC_DEATH_WORD = death[0];
}

/*
    Put a Fire Burst in the pouch.

    ⚠️ ONCE PER POUCH, NOT ONCE PER RUN. The verification boot found
    `pouchGetPtr()` NON-NULL during the attract demo -- which D109 recorded as
    null -- and `pouchAddItem` refusing every frame. So "the demo has no pouch"
    is not the shape of this: there is a pouch, and it will not take the item.

    Granting once would therefore burn the only attempt on the demo's pouch and
    leave nothing for the player's, which is the one that matters. So it retries
    while refused, and grants AGAIN if the pouch pointer moves -- a new pointer
    is a new session, and the item has to land in the session the player holds.
*/
static void grantOnce(void)
{
    void *pouch = pouchGetPtr();

    POUCH_PTR = (u32) pouch;
    if (pouch == 0)
    {
        GRANT = BLECK_GRANT_NO_POUCH;
        return;
    }

    /* Already landed one in *this* pouch. Nothing more until it moves. */
    if (GRANT == BLECK_GRANT_ADDED && GRANT_POUCH == (u32) pouch)
        return;

    GRANT_TRIES += 1;
    if (pouchAddItem(GRANT_ID))
    {
        GRANT = BLECK_GRANT_ADDED;
        GRANT_ADDS += 1;
        GRANT_POUCH = (u32) pouch;
    }
    else
    {
        GRANT = BLECK_GRANT_REFUSED;
    }
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

    for (i = 0; i < 3; i++)
        NPC_STATUS(i) = bleck_patch_status[ITEM_PATCHES + i];
    NPC_SHARED(0) = bleck_patch_shared[ITEM_PATCHES + 0];
    NPC_SHARED(1) = bleck_patch_shared[ITEM_PATCHES + 1];

    readItemTable();
    readTemplate();

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
