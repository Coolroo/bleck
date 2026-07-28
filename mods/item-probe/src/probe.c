/*
    Are item use scripts reachable and patchable the way map init scripts are?

    D88/D89/D90 settled `map:`. This asks the same three questions of items,
    read-only, before anything writes:

      1. Is the script pointer populated at `mod_prolog`?
      2. Does it decode as evt bytecode?
      3. Does it stay put once the game is running?

    `itemEventDataTable` (0x803fbc10) is 33 entries of
    `{s32 itemId, EvtScriptCode *useScript, const char *useMsgName}` in the
    DOL's data. Read directly rather than through `getItemUseEvt`, which the
    header says returns "a fallback if the item isn't in there" -- so several
    ids can share one script, and patching by id could hit far more than the
    item asked for.

    Report block at PROBE, big-endian u32:

      +0x00  magic 'ITMP'
      +0x04  8 entries as (itemId, useScript) pairs        [1..16]
      +0x44  first 4 words of entry 0's script             [17..20]
      +0x54  entry 0's useScript, re-read during SEQ_GAME  [21]
      +0x58  distinct useScript pointers among the 33      [22]
      +0x5C  SEQ_GAME frames                               [23]

    Target: eu0. Nothing here writes to game memory.
*/

typedef int s32;
typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x49544D50U /* 'ITMP' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

#define ITEM_COUNT 33
#define REPORTED 8

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

typedef struct
{
    s32 itemId;
    u32 *useScript;
    const char *useMsgName;
} ItemEventData;

extern SeqDef seq_data[];
extern ItemEventData itemEventDataTable[];

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define ENTRY_ID(i) (probe[1 + (i) * 2])
#define ENTRY_SCRIPT(i) (probe[2 + (i) * 2])
#define WORD(i) (probe[17 + (i)])
#define LIVE_SCRIPT (probe[21])
#define DISTINCT (probe[22])
#define GAME_FRAMES (probe[23])

static SeqFunc *realMain[SEQ_COUNT] = {
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
    (SeqFunc *) 1, (SeqFunc *) 1, (SeqFunc *) 1,
};

/* How many of the 33 scripts are unique. If items share one, a patch aimed at
   a single item would change every item sharing it. */
static u32 countDistinct(void)
{
    u32 distinct = 0;
    u32 i, j;

    for (i = 0; i < ITEM_COUNT; i++)
    {
        u32 *script = itemEventDataTable[i].useScript;
        int seen = 0;

        if (script == 0)
            continue;
        for (j = 0; j < i; j++)
            if (itemEventDataTable[j].useScript == script)
                seen = 1;
        if (!seen)
            distinct += 1;
    }
    return distinct;
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        if (GAME_FRAMES == 1)
            LIVE_SCRIPT = (u32) itemEventDataTable[0].useScript;
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
    u32 *first;
    u32 i;

    for (i = 0; i < 24; i++)
        probe[i] = 0;
    probe[0] = MAGIC;

    for (i = 0; i < REPORTED; i++)
    {
        ENTRY_ID(i) = (u32) itemEventDataTable[i].itemId;
        ENTRY_SCRIPT(i) = (u32) itemEventDataTable[i].useScript;
    }

    first = itemEventDataTable[0].useScript;
    if (first != 0)
        for (i = 0; i < 4; i++)
            WORD(i) = first[i];

    DISTINCT = countDistinct();

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
