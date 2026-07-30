/*
    Are an NPC's behaviour scripts reachable, and when?

    `npcdrv.h` gives every live NPCEntry ten script pointers -- init, move,
    onHit, pickup, throw, kouraKick, death, atk, misc -- and every comment says
    they come "from spawning SetupEnemyTemplate". So unlike doors, maps and
    items, these are NOT in static data readable at `mod_prolog`: they are
    copied into an instance when it spawns.

    That distinction decides the whole feature. If the scripts only exist on
    live entries, `npcdrv:` cannot be a build-time patch the way `door:` is, and
    the route is `code.hooks` interception of a spawn function instead.

    WHAT IS BEING ESTABLISHED, in order:

      1. Is `npcGetWorkPtr()` usable during gameplay at all?
      2. Does the attract demo's maps even contain NPCs -- `num` above zero?
         A zero here invalidates everything below it rather than meaning "no
         scripts", which is the D94 trap: a measurement of the wrong maps.
      3. Do live entries carry non-null script pointers?
      4. Does a script pointer point at something that decodes as bytecode?
         A pointer is not evidence; a plausible evt header is.

    ⚠️ Nothing here is read at `mod_prolog`. The whole question is what exists
    DURING gameplay, so every read is in the sequence hook.

    Report block at PROBE, big-endian u32:

      +0x00 ( 0)  magic 'NPCD'
      +0x04 ( 1)  npcGetWorkPtr()
      +0x08 ( 2)  work->num, most recent
      +0x0C ( 3)  the largest num seen
      +0x10 ( 4)  work->entries
      +0x14 ( 5)  work->setupFile -- the file bleck already edits
      +0x18 ( 6)  entries[0].templateinitScript   (+0x348)
      +0x1C ( 7)  entries[0].templatemoveScript   (+0x360)
      +0x20 ( 8)  entries[0].templateonHitScript  (+0x364)
      +0x24 ( 9)  entries[0].templatedeathScript  (+0x374)
      +0x28 (10)  first word of whichever of those is non-null
      +0x2C (11)  its opcode, masked -- a real script decodes, garbage does not
      +0x30 (12)  frames on which num was above zero
      +0x34 (13)  SEQ_GAME frames. The control: zero invalidates the run
      +0x38 (14)  index of the first entry carrying any script, else -1
      +0x3C (15)  how many of the `num` entries carry one
      +0x40 (16)  CONTROL: slots whose head word is non-zero -- i.e. live at all
      +0x44 (17)  the first such slot, else -1
      +0x48 (18)  its head word

    Run with:  scripts/ingame.py npc-probe --words 15 --seconds 75
    Target: eu0. Nothing here writes to game memory.
*/

typedef unsigned int u32;

#define PROBE 0x80005000
#define MAGIC 0x4E504344U /* 'NPCD' */

#define SEQ_COUNT 6
#define SEQ_GAME 2

/* npcdrv.h: NPCWork */
#define WORK_NUM 0x04
#define WORK_ENTRIES 0x08
#define WORK_SETUPFILE 0x18

/* npcdrv.h: NPCEntry, 0x748 bytes */
#define NPC_INIT_SCRIPT 0x348
#define NPC_MOVE_SCRIPT 0x360
#define NPC_ONHIT_SCRIPT 0x364
#define NPC_DEATH_SCRIPT 0x374
#define NPC_ENTRY_SIZE 0x748

typedef void(SeqFunc)(void *);

typedef struct
{
    SeqFunc *init;
    SeqFunc *main;
    SeqFunc *exit;
} SeqDef;

extern SeqDef seq_data[];
extern void *npcGetWorkPtr(void);

static volatile u32 *const probe = (volatile u32 *) PROBE;

#define WORK_PTR (probe[1])
#define NUM (probe[2])
#define MAX_NUM (probe[3])
#define ENTRIES (probe[4])
#define SETUP_FILE (probe[5])
#define SCRIPT(i) (probe[6 + (i)])
#define FIRST_WORD (probe[10])
#define FIRST_OPCODE (probe[11])
#define FOUND_AT (probe[14])
#define WITH_SCRIPTS (probe[15])
#define LIVE_SLOTS (probe[16])
#define LIVE_AT (probe[17])
#define LIVE_WORD (probe[18])
#define POPULATED_FRAMES (probe[12])
#define GAME_FRAMES (probe[13])

static SeqFunc *realMain[SEQ_COUNT];

static u32 readField(unsigned char *entry, u32 offset)
{
    return *(u32 *) (entry + offset);
}

static void sample(void)
{
    unsigned char *work = (unsigned char *) npcGetWorkPtr();
    unsigned char *entries;
    u32 num;
    u32 i;

    WORK_PTR = (u32) work;
    if (work == 0)
        return;

    num = readField(work, WORK_NUM);
    entries = (unsigned char *) readField(work, WORK_ENTRIES);
    NUM = num;
    ENTRIES = (u32) entries;
    SETUP_FILE = readField(work, WORK_SETUPFILE);
    if (num > MAX_NUM)
        MAX_NUM = num;
    if (num == 0 || entries == 0)
        return;

    POPULATED_FRAMES += 1;
    WITH_SCRIPTS = 0;
    LIVE_SLOTS = 0;

    /*
        SCAN, do not index slot 0.

        The first run read entries[0] and found four null pointers, then
        reported them -- but `num` sat at exactly 80 for the whole run and never
        moved, which is a CAPACITY, not a live count (`npcGetMaxEntries` is a
        separate symbol). Slot 0 was simply unused, so "the scripts are null"
        was a fact about the slot and not about NPCs.

        That is D93 restated: a measurement of the wrong place reads exactly
        like a measurement of nothing. So this walks every slot and reports the
        first that carries any script, plus how many do -- and a count of zero
        now means something, because the walk covered the array.
    */
    for (i = 0; i < num && i < 128; i++)
    {
        unsigned char *entry = entries + i * NPC_ENTRY_SIZE;
        u32 init = readField(entry, NPC_INIT_SCRIPT);
        u32 move = readField(entry, NPC_MOVE_SCRIPT);
        u32 onhit = readField(entry, NPC_ONHIT_SCRIPT);
        u32 death = readField(entry, NPC_DEATH_SCRIPT);

        /*
            THE CONTROL. Run 2 reported "no entry carries a script" across all
            80 slots -- but nothing showed the walk could see an NPC at all, so
            that zero was equally consistent with "these maps have none" and
            with "the offsets are wrong". A negative needs a positive beside it.

            A live entry cannot be all zeroes. Counting slots with any non-zero
            head word says whether NPCs exist here, independently of whether the
            script offsets are right.
        */
        if (readField(entry, 0) != 0)
        {
            LIVE_SLOTS += 1;
            if (LIVE_AT == 0xFFFFFFFFU)
            {
                LIVE_AT = i;
                LIVE_WORD = readField(entry, 0);
            }
        }

        if ((init | move | onhit | death) == 0)
            continue;

        WITH_SCRIPTS += 1;
        if (FOUND_AT != 0xFFFFFFFFU)
            continue;

        FOUND_AT = i;
        SCRIPT(0) = init;
        SCRIPT(1) = move;
        SCRIPT(2) = onhit;
        SCRIPT(3) = death;
        if (init != 0)
        {
            FIRST_WORD = *(u32 *) init;
            FIRST_OPCODE = FIRST_WORD & 0xFFFFU;
        }
    }
}

static void onSequenceFrame(u32 seq, void *work)
{
    if (seq == SEQ_GAME)
    {
        GAME_FRAMES += 1;
        sample();
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

    for (i = 0; i < 19; i++)
        probe[i] = 0;
    probe[0] = MAGIC;
    FOUND_AT = 0xFFFFFFFFU;
    LIVE_AT = 0xFFFFFFFFU;

    for (i = 0; i < SEQ_COUNT; i++)
    {
        realMain[i] = seq_data[i].main;
        seq_data[i].main = hooks[i];
    }
}
